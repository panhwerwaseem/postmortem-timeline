#!/usr/bin/env python3
"""Show how a timestamp is converted to UTC, or why it cannot be.

This is the timestamp reader that build_timeline.py imports. Run it directly
to check one or more timestamps before building a timeline.

Accepted:
  - An ISO 8601 date and time, "T" or a space between them, seconds and a
    fraction optional, followed by Z, UTC, GMT or a numeric offset
    (+05:30, +0530, +05).
  - An epoch number: 10-digit seconds or 13-digit milliseconds, with an
    optional fraction (Slack's "ts" is the first kind).
  - The same date and time followed by a zone name such as Europe/Oslo, if
    this machine has time zone data for it.

Not placed, by design:
  - No zone or offset at all (no-zone). Pass --assume-zone once you know it.
  - A zone abbreviation such as IST or CST (ambiguous-zone). Abbreviations do
    not identify one offset. Pass --zone-offset IST=+05:30.
  - A zone name this machine cannot resolve (unresolved-zone).
  - A local time in a repeated or skipped daylight-saving hour (dst-transition).
  - Anything else, including date-only values, RFC 2822 dates and forms such
    as "UTC+5" (bad-timestamp).

Examples:
  utc_time.py "2026-03-14T14:22:05+05:30" 1773479610 "2026-03-14 14:02:11"
  utc_time.py --assume-zone +05:00 "2026-03-14 14:02:11"
  utc_time.py --zone-offset IST=+05:30 --json "2026-03-14 14:32 IST"

Exit codes: 0 = every timestamp was converted, 1 = at least one could not be
converted, 2 = usage error. Standard library only. Reads only its arguments.
Writes only to stdout. Makes no network calls.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal

EPOCH = datetime(1970, 1, 1)
MAX_OFFSET = timedelta(hours=14)  # real offsets run from -12:00 to +14:00
STAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?")
OFFSET_RE = re.compile(r"^([+-])(\d{2})(?::?(\d{2}))?$")
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
IANA_RE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+-]+)+$")
ABBREV_RE = re.compile(r"^[A-Za-z]{2,6}$")
# problem code -> (what is wrong, what to do about it)
PROBLEMS = {
    "no-zone": ("no zone or offset in the timestamp",
                "Find out which zone the source records in, then pass --assume-zone."),
    "ambiguous-zone": ("a zone abbreviation that does not identify one offset",
                       "Pass --zone-offset NAME=+HH:MM once the offset is known."),
    "unresolved-zone": ("a zone name this machine has no time zone data for",
                        "Pass --zone-offset NAME=+HH:MM with the offset that applied on that date."),
    "dst-transition": ("a local time in a repeated or skipped daylight-saving hour",
                       "Rewrite the timestamp with a numeric offset."),
    "bad-timestamp": ("a missing or unreadable timestamp",
                      "Accepted: ISO 8601 date and time, or epoch seconds or milliseconds."),
}


class InputError(Exception):
    """A problem with the command line or an input file. Exit code 2."""


def parse_offset(text):
    """Return a timedelta for Z, UTC, GMT, +HH, +HHMM or +HH:MM; None for anything else."""
    if text.upper() in ("Z", "UTC", "GMT"):
        return timedelta(0)
    match = OFFSET_RE.match(text)
    if not match:
        return None
    minutes = int(match.group(3) or 0)
    offset = timedelta(hours=int(match.group(2)), minutes=minutes)
    if minutes > 59 or offset > MAX_OFFSET:
        return None
    return -offset if match.group(1) == "-" else offset


def format_offset(offset):
    minutes = int(offset.total_seconds() // 60)
    return "%s%02d:%02d" % ("-" if minutes < 0 else "+", abs(minutes) // 60, abs(minutes) % 60)


def parse_epoch(text):
    """UTC datetime for 10-digit epoch seconds or 13-digit epoch milliseconds, else None.

    Other magnitudes are refused instead of guessed: 20260314091205 is a
    compact date, and 16 or 19 digits are micro- or nanoseconds.
    """
    number = Decimal(text)
    if 10 ** 9 <= number < 10 ** 10:
        seconds = number
    elif 10 ** 12 <= number < 10 ** 13:
        seconds = number / 1000
    else:
        return None
    whole = int(seconds)
    return EPOCH + timedelta(seconds=whole, microseconds=int((seconds - whole) * 1000000))


def parse_timestamp(value):
    """Classify one raw timestamp. Returns (kind, moment, detail, minute_only).

    kind: "epoch" (moment is UTC), "utc" or "offset" (detail is the timedelta
    to subtract from moment), "naive" (no zone text), "word" (detail is a zone
    name or abbreviation), "bad" (detail says why).
    """
    if value is None or isinstance(value, (bool, list, dict)) or not str(value).strip():
        return "bad", None, "no timestamp", False
    text = str(value).strip()
    if NUMBER_RE.match(text):
        moment = parse_epoch(text)
        if moment is None:
            return "bad", None, "%s is not 10-digit epoch seconds or 13-digit milliseconds" % text, False
        return "epoch", moment, None, False
    match = STAMP_RE.match(text)
    if not match:
        return "bad", None, "%r is not an ISO 8601 date and time" % text, False
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    micro = int((match.group(7) or "")[:6].ljust(6, "0"))
    try:
        local = datetime(year, month, day, hour, minute, int(match.group(6) or 0), micro)
    except ValueError:
        return "bad", None, "%r is not a valid date and time" % text, False
    minute_only = match.group(6) is None
    rest = text[match.end():].strip()
    if not rest:
        return "naive", local, None, minute_only
    offset = parse_offset(rest)
    if offset is not None:
        kind = "utc" if rest.upper() in ("Z", "UTC", "GMT") else "offset"
        return kind, local, offset, minute_only
    if IANA_RE.match(rest) or ABBREV_RE.match(rest):
        return "word", local, rest, minute_only
    return "bad", None, "%r has zone text that is not Z, an offset or a zone name" % text, False


def named_zone_offset(name, local):
    """Offset of an IANA zone at a local time: (timedelta, None) or (None, problem code).

    Uses zoneinfo only if it and its time zone data are present. A local time
    in a repeated or skipped hour is refused, because the two readings of it
    are an hour apart.
    """
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(name)
    except (ImportError, KeyError, ValueError, OSError):
        return None, "unresolved-zone"
    first = local.replace(tzinfo=zone, fold=0).utcoffset()
    second = local.replace(tzinfo=zone, fold=1).utcoffset()
    if first is None or first != second:
        return None, "dst-transition"
    return first, None


def zone_spec(text):
    """Parse the ZONE of --assume-zone: an offset, UTC, or a resolvable zone name."""
    offset = parse_offset(text)
    if offset is not None:
        return {"label": format_offset(offset), "offset": offset, "name": None}
    if IANA_RE.match(text) and named_zone_offset(text, datetime(2000, 1, 1, 12))[1] != "unresolved-zone":
        return {"label": text, "offset": None, "name": text}
    raise InputError("--assume-zone: %r is not an offset such as +05:00 or a zone name this "
                     "machine can resolve. Pass a numeric offset." % text)


def zone_offset_pair(text):
    """Parse one --zone-offset value such as IST=+05:30 into (name, timedelta)."""
    name, _, value = text.rpartition("=")
    offset = parse_offset(value.strip())
    if offset is None or not (IANA_RE.match(name.strip()) or ABBREV_RE.match(name.strip())):
        raise InputError("--zone-offset %r must look like IST=+05:30" % text)
    return name.strip(), offset


def resolve(value, assumed=None, zone_offsets=None):
    """Convert one raw timestamp to UTC without guessing.

    assumed is a zone_spec() result applied only when the timestamp has no
    zone text. zone_offsets maps zone names or abbreviations to timedeltas.
    Returns a dict: utc (naive datetime in UTC, or None), zone ("epoch", "utc",
    "offset", "named", "assumed" or None), zone_detail, problem (a PROBLEMS
    code or None) and minute_precision.
    """
    kind, local, detail, minute_only = parse_timestamp(value)
    offset, problem, zone, note = None, None, kind, None
    if kind == "bad":
        problem, note = "bad-timestamp", detail
    elif kind in ("utc", "epoch"):
        offset = timedelta(0)
    elif kind == "offset":
        offset, note = detail, format_offset(detail)
    elif kind == "naive":
        if assumed is None:
            problem = "no-zone"
        else:
            zone, note, offset = "assumed", assumed["label"], assumed["offset"]
            if assumed["name"]:
                offset, problem = named_zone_offset(assumed["name"], local)
    elif detail in (zone_offsets or {}):
        zone, offset = "assumed", zone_offsets[detail]
        note = "%s=%s" % (detail, format_offset(offset))
    elif "/" in detail:
        zone, note = "named", detail
        offset, problem = named_zone_offset(detail, local)
    else:
        problem, note = "ambiguous-zone", detail
    return {"utc": None if problem else local - offset, "zone": None if problem else zone,
            "zone_detail": note, "problem": problem, "minute_precision": minute_only}


def iso_utc(moment):
    return None if moment is None else moment.isoformat() + "Z"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("timestamps", nargs="+", metavar="TIMESTAMP", help="a timestamp to convert")
    parser.add_argument("--assume-zone", metavar="ZONE",
                        help="zone for timestamps that carry none: +05:00, UTC, or a zone name "
                             "such as Europe/Oslo if this machine can resolve it")
    parser.add_argument("--zone-offset", action="append", default=[], metavar="NAME=OFFSET",
                        help="offset of a zone abbreviation or name, e.g. IST=+05:30; repeatable")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)
    try:
        assumed = zone_spec(args.assume_zone) if args.assume_zone else None
        zone_offsets = dict(zone_offset_pair(text) for text in args.zone_offset)
    except InputError as exc:
        print("utc_time.py: error: %s" % exc, file=sys.stderr)
        return 2
    rows = []
    for raw in args.timestamps:
        found = resolve(raw, assumed, zone_offsets)
        found["utc"] = iso_utc(found["utc"])
        rows.append(dict(found, raw=raw))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            if row["problem"]:
                what = PROBLEMS[row["problem"]][0]
                detail = " (%s)" % row["zone_detail"] if row["zone_detail"] else ""
                print("%s  ->  NOT PLACED, %s: %s%s" % (row["raw"], row["problem"], what, detail))
            else:
                note = "zone assumed: %s" % row["zone_detail"] if row["zone"] == "assumed" else row["zone"]
                print("%s  ->  %s  (%s)" % (row["raw"], row["utc"], note))
        for code in sorted(set(row["problem"] for row in rows if row["problem"])):
            print("%s: %s" % (code, PROBLEMS[code][1]))
    return 1 if any(row["problem"] for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
