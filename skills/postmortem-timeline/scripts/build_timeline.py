#!/usr/bin/env python3
"""Merge timestamped incident evidence into one UTC-ordered timeline.

Reads alerts, deploy records, chat exports and git history, converts every
timestamp to UTC, sorts the events, marks gaps, and computes the durations
between tagged milestones. An event whose time zone cannot be established is
listed separately and is never placed by guesswork.

Inputs (each option can be repeated):
  --events FILE    Neutral events: JSONL, one object per line, or CSV with a
                   header row when the name ends in .csv. Fields: timestamp,
                   source, text; optional tag and actor.
  --git-log FILE   Output of:  git log --pretty=format:'%h%x09%cI%x09%s'
                   (hash, TAB, committer date in strict ISO 8601, TAB, subject)
  --chat FILE      Chat export: a JSON array of messages, or an object with a
                   "messages" array. Each message has "ts" (epoch seconds, as
                   Slack exports them) or "timestamp", and "text" or "content".
  --git-log and --chat accept NAME=FILE to set the source label (default: git, chat).

Timestamp rules are in utc_time.py (run it with --help). In short: a
timestamp needs Z, a numeric offset, or to be an epoch number. One with no
zone, or with an abbreviation such as IST, is an error and stays out of the
timeline until --assume-zone or --zone-offset settles it. Gaps and durations
use times truncated to whole seconds.

Examples:
  build_timeline.py --events alerts.jsonl --events deploys.csv --git-log git-log.txt --chat channel.json
  build_timeline.py --events deploys.csv --assume-zone deploys=+05:00 --json
  build_timeline.py --events alerts.jsonl --chat chat.json --tag detected=alerts.jsonl:2 --tag resolved=chat.json#/14
  build_timeline.py --events alerts.jsonl --chat chat.json --roles roles.json --out timeline.md

Exit codes: 0 = timeline built with no blocking finding, 1 = at least one
blocking finding (errors; warnings too with --fail-on warning), 2 = usage or
input error. Standard library only. Reads the files you name. Writes only to
--out or stdout. Makes no network calls.
"""
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

from utc_time import PROBLEMS, InputError, iso_utc, resolve, zone_offset_pair, zone_spec

MILESTONES = ("started", "detected", "acknowledged", "mitigated", "resolved")
DURATION_PAIRS = (("started", "detected"), ("detected", "acknowledged"), ("detected", "mitigated"),
                  ("detected", "resolved"), ("started", "mitigated"), ("started", "resolved"))
MAX_TEXT = 200  # characters of event text shown in a Markdown table cell
LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
HASH_RE = re.compile(r"^[0-9a-fA-F]{4,64}$")
GIT_FORMAT = "git log --pretty=format:'%h%x09%cI%x09%s'"


def read_text(path):
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError("cannot read %s: %s" % (path, exc))


def new_event(value, source, text, name, position, ref, tag=None, actor=None):
    return {"utc": None, "raw": "" if value is None else str(value), "_value": value,
            "source": source, "text": text, "actor": actor if isinstance(actor, str) and actor else None,
            "tag": str(tag).strip().lower() if tag else None, "ref": ref, "_pos": (name, position)}


def load_events(path, events):
    text, rows = read_text(path), []
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        try:
            reader.fieldnames = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
            if not {"timestamp", "source", "text"} <= set(reader.fieldnames):
                raise InputError("%s: the CSV header must have the columns timestamp, source, text" % path)
            for row in reader:
                rows.append((reader.line_num, row))
        except csv.Error as exc:
            raise InputError("%s: not readable as CSV: %s" % (path, exc))
    else:
        for number, line in enumerate(text.split("\n"), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if not isinstance(row, dict):
                raise InputError("%s:%d: not a JSON object. --events takes JSONL (one object "
                                 "per line) or a file ending in .csv" % (path, number))
            rows.append((number, row))
    for number, row in rows:
        ref = "%s:%d" % (path.name, number)
        source, body = row.get("source"), row.get("text")
        if not isinstance(source, str) or not source.strip() or not isinstance(body, str):
            raise InputError("%s: each event needs a 'source' and a 'text'" % ref)
        events.append(new_event(row.get("timestamp"), source.strip(), body, path.name, number, ref,
                                row.get("tag"), row.get("actor")))


def load_git_log(path, source, events):
    for number, line in enumerate(read_text(path).split("\n"), 1):
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2 or not HASH_RE.match(parts[0].strip()):
            raise InputError("%s:%d: expected '<hash><TAB><ISO date><TAB><subject>'. Produce it with: %s"
                             % (path, number, GIT_FORMAT))
        subject = parts[2].strip() if len(parts) > 2 else ""
        events.append(new_event(parts[1], source, "commit %s: %s" % (parts[0].strip(), subject),
                                path.name, number, "%s:%d" % (path.name, number)))


def first_string(message, keys):
    for key in keys:
        if isinstance(message.get(key), str) and message[key]:
            return message[key]
    return None


def load_chat(path, source, events):
    try:
        data = json.loads(read_text(path))
    except ValueError as exc:
        raise InputError("%s: not valid JSON: %s" % (path, exc))
    pointer = ""
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        data, pointer = data["messages"], "/messages"
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise InputError("%s: expected a JSON array of message objects, or an object with a "
                         "'messages' array" % path)
    for index, message in enumerate(data):
        stamp = message.get("ts") if message.get("ts") is not None else message.get("timestamp")
        events.append(new_event(
            stamp, source, first_string(message, ("text", "content")) or "(no text)", path.name, index,
            "%s#%s/%d" % (path.name, pointer, index), message.get("tag"),
            first_string(message, ("user_name", "username", "user", "author"))))


def apply_roles(events, roles):
    """Replace names with roles in actor and text. Returns refs of actors with no role."""
    names = sorted(roles, key=lambda name: (-len(name), name))  # longest first
    pattern = re.compile("|".join(r"<@%s>|(?<!\w)%s(?!\w)" % (re.escape(n), re.escape(n)) for n in names))

    def swap(match):
        found = match.group(0)
        return roles[found] if found in roles else roles[found[2:-1]]  # second case: <@NAME>

    missing = []
    for event in events:
        if event["actor"] is not None and event["actor"] not in roles:
            missing.append(event["ref"])
        event["actor"] = roles.get(event["actor"], event["actor"])
        if names:
            event["text"] = pattern.sub(swap, event["text"])
    return missing


def format_duration(seconds):
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return "%dd %dh %02dm %02ds" % (days, hours, minutes, secs)
    if hours:
        return "%dh %02dm %02ds" % (hours, minutes, secs)
    return "%dm %02ds" % (minutes, secs) if minutes else "%ds" % secs


def whole(event):
    return event["_utc"].replace(microsecond=0)


def finding(level, code, evidence, message):
    return {"level": level, "code": code, "message": message, "evidence": evidence}


def analyse(events, gap_seconds, findings):
    """Order the events, then report unplaced groups, milestones, durations and gaps."""
    ordered = sorted(events, key=lambda e: e["_pos"])
    placed = sorted((e for e in ordered if e["_utc"] is not None), key=lambda e: (e["_utc"], e["_pos"]))
    unplaced = [e for e in ordered if e["_utc"] is None]

    groups = {}
    for event in unplaced:
        groups.setdefault((event["problem"], event["source"]), []).append(event)
    for (code, source), members in sorted(groups.items()):
        details = sorted(set(e["zone_detail"] for e in members if e["zone_detail"]))
        what, fix = PROBLEMS[code]
        if code == "no-zone":
            fix = ("Find out which zone this source records in, then pass --assume-zone %s=+HH:MM."
                   % source)
        findings.append(finding("error", code, [e["ref"] for e in members],
                                "%d event(s) from source '%s' are not placed: %s%s. %s" % (
                                    len(members), source, what,
                                    " (%s)" % "; ".join(details) if details else "", fix)))

    tagged, milestones, unusable = {}, {}, {}
    for event in ordered:
        if event["tag"] in MILESTONES:
            tagged.setdefault(event["tag"], []).append(event)
        elif event["tag"]:
            findings.append(finding("warning", "unknown-tag", [event["ref"]],
                                    "Tag '%s' is not a milestone (%s). It is shown but not used for "
                                    "durations." % (event["tag"], ", ".join(MILESTONES))))
    for tag, members in tagged.items():
        if len(members) > 1:
            unusable[tag] = "'%s' is tagged on %d events" % (tag, len(members))
            findings.append(finding("error", "duplicate-milestone", [e["ref"] for e in members],
                                    "Tag '%s' is on %d events. A milestone is one event; keep the "
                                    "tag on one evidence line." % (tag, len(members))))
        elif members[0]["_utc"] is None:
            unusable[tag] = "'%s' is on an event that is not placed (%s)" % (tag, members[0]["ref"])
        else:
            milestones[tag] = members[0]
    present = [tag for tag in MILESTONES if tag in milestones]
    for earlier, later in zip(present, present[1:]):
        if whole(milestones[later]) < whole(milestones[earlier]):
            unusable[later] = unusable[earlier] = "'%s' is earlier than '%s'" % (later, earlier)
            findings.append(finding(
                "error", "milestone-order", [milestones[earlier]["ref"], milestones[later]["ref"]],
                "'%s' (%s) is earlier than '%s' (%s). Check both tags and the zone of both sources."
                % (later, milestones[later]["utc"], earlier, milestones[earlier]["utc"])))
    durations = []
    for start, end in DURATION_PAIRS:
        if start in tagged and end in tagged:
            entry = {"from": start, "to": end, "seconds": None, "text": None,
                     "reason": unusable.get(start) or unusable.get(end)}
            if entry["reason"] is None:
                entry["seconds"] = int((whole(milestones[end]) - whole(milestones[start])).total_seconds())
                entry["text"] = format_duration(entry["seconds"])
            durations.append(entry)

    window = [whole(e) for e in milestones.values()]
    gaps = []
    for before, after in zip(placed, placed[1:]):
        seconds = int((whole(after) - whole(before)).total_seconds())
        if seconds <= gap_seconds:
            continue
        inside = None  # unknown unless two milestones define an incident window
        if len(window) > 1:
            inside = whole(before) < max(window) and whole(after) > min(window)
        start, end = iso_utc(whole(before)), iso_utc(whole(after))
        gaps.append({"after_ref": before["ref"], "before_ref": after["ref"], "start_utc": start,
                     "end_utc": end, "seconds": seconds, "text": format_duration(seconds),
                     "in_incident_window": inside})
        where = {True: " inside the incident window", False: " outside the incident window", None: ""}
        findings.append(finding("warning", "gap", [before["ref"], after["ref"]],
                                "No events from any source for %s%s, between %s and %s. Look for "
                                "another source, or keep the gap marked as unknown."
                                % (format_duration(seconds), where[inside], start, end)))
    return placed, unplaced, milestones, durations, gaps


def cell(text):
    text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT].rstrip() + " [...]"


def describe(event):
    return cell("%s: %s" % (event["actor"], event["text"]) if event["actor"] else event["text"])


def finding_lines(result):
    lines = []
    for item in result["findings"]:
        refs = item["evidence"][:4]
        if len(item["evidence"]) > 4:
            refs.append("and %d more" % (len(item["evidence"]) - 4))
        lines.append("- %s %s: %s [%s]" % (item["level"].upper(), item["code"], item["message"],
                                           ", ".join(refs)))
    summary = result["summary"]
    lines.append("- Result: %s (%d error(s), %d warning(s))" % (
        "BLOCKED" if summary["blocked"] else "OK", summary["errors"], summary["warnings"]))
    return lines


def render_markdown(result):
    summary = result["summary"]
    lines = ["# Incident timeline (UTC)", "",
             "Placed %d of %d events from %d file(s). Gaps over %s: %d. Errors: %d. Warnings: %d."
             % (summary["placed"], summary["events"], len(result["inputs"]),
                format_duration(summary["gap_threshold_seconds"]), summary["gaps"],
                summary["errors"], summary["warnings"]),
             "", "| Time (UTC) | Source | Event | Tag | Evidence |", "|---|---|---|---|---|"]
    gaps = {gap["after_ref"]: gap for gap in result["gaps"]}
    for event in result["timeline"]:
        stamp = event["utc"][:16 if event["minute_precision"] else 19].replace("T", " ")
        if event["zone"] == "assumed":
            stamp += " (zone assumed: %s)" % event["zone_detail"]
        lines.append("| %s | %s | %s | %s | %s |" % (
            stamp, cell(event["source"]), describe(event), event["tag"] or "", event["ref"]))
        gap = gaps.get(event["ref"])
        if gap:
            where = " (inside the incident window)" if gap["in_incident_window"] else ""
            lines.append("| | | **GAP: no events from any source for %s**%s | | %s to %s |" % (
                gap["text"], where, gap["after_ref"], gap["before_ref"]))
    if result["not_placed"]:
        lines += ["", "## Not placed", "",
                  "These events have no established UTC time. They are not in the timeline above.", "",
                  "| Raw timestamp | Source | Event | Tag | Reason | Evidence |", "|---|---|---|---|---|---|"]
        for event in result["not_placed"]:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                cell(event["raw"]) or "(none)", cell(event["source"]), describe(event),
                event["tag"] or "", event["problem"], event["ref"]))
    lines += ["", "## Durations", ""]
    for entry in result["durations"]:
        if entry["seconds"] is None:
            lines.append("- %s to %s: not computed, %s" % (entry["from"], entry["to"], entry["reason"]))
        else:
            lines.append("- %s to %s: %s (%s to %s)" % (
                entry["from"], entry["to"], entry["text"],
                result["milestones"][entry["from"]]["ref"], result["milestones"][entry["to"]]["ref"]))
    untagged = [tag for tag in MILESTONES if tag not in result["tags_present"]]
    if untagged:
        lines.append("- No event is tagged: %s. Tag one evidence line with --tag TAG=EVIDENCE."
                     % ", ".join(untagged))
    return "\n".join(lines + ["", "## Findings", ""] + finding_lines(result)) + "\n"


def input_files(args):
    """Return (kind, source label, path) for every input, sorted by file name."""
    files = [("events", None, Path(arg)) for arg in args.events]
    for kind, default, values in (("git-log", "git", args.git_log), ("chat", "chat", args.chat)):
        for arg in values:
            head, sep, tail = arg.partition("=")
            if sep and tail and LABEL_RE.match(head) and not Path(arg).exists():
                files.append((kind, head, Path(tail)))
            else:
                files.append((kind, default, Path(arg)))
    if not files:
        raise InputError("give at least one of --events, --git-log, --chat")
    names = [path.name for _, _, path in files]
    for name in sorted(set(names)):
        if names.count(name) > 1:
            raise InputError("two inputs are both named %s; rename one so evidence references "
                             "stay unique" % name)
    return sorted(files, key=lambda item: item[2].name)


def split_pair(text, option, last=False):
    head, sep, tail = text.rpartition("=") if last else text.partition("=")
    if not sep or not head.strip() or not tail.strip():
        raise InputError("%s %r must look like NAME=VALUE" % (option, text))
    return head.strip(), tail.strip()


def build(args):
    if args.gap_minutes <= 0:
        raise InputError("--gap-minutes must be greater than 0")
    events, inputs, findings = [], [], []
    for kind, source, path in input_files(args):
        before = len(events)
        if kind == "events":
            load_events(path, events)
        elif kind == "git-log":
            load_git_log(path, source, events)
        else:
            load_chat(path, source, events)
        inputs.append({"file": path.name, "kind": kind, "events": len(events) - before})
    if not events:
        raise InputError("the inputs contain no events")

    sources = sorted(set(e["source"] for e in events))
    assume = {}
    for text in args.assume_zone:
        source, zone = split_pair(text, "--assume-zone", last=True)
        if source not in sources:
            raise InputError("--assume-zone names source %r, which is not in the inputs (sources: %s)"
                             % (source, ", ".join(sources)))
        assume[source] = zone_spec(zone)
    zone_offsets = dict(zone_offset_pair(text) for text in args.zone_offset)
    by_ref = {e["ref"]: e for e in events}
    for text in args.tag:
        tag, ref = split_pair(text, "--tag")
        if ref not in by_ref:
            raise InputError("--tag %s: no event has the evidence reference %r" % (tag, ref))
        by_ref[ref]["tag"] = tag.lower()
    if args.roles:
        try:
            roles = json.loads(read_text(Path(args.roles)))
        except ValueError as exc:
            raise InputError("%s: not valid JSON: %s" % (args.roles, exc))
        if not isinstance(roles, dict) or not all(isinstance(v, str) and k for k, v in roles.items()):
            raise InputError("%s: expected a JSON object that maps each name to a role" % args.roles)
        missing = apply_roles(events, roles)
        if missing:
            findings.append(finding("warning", "no-role", missing,
                                    "%d event(s) have an actor with no entry in the roles file, so "
                                    "a name is still shown." % len(missing)))

    assumed = {}
    for event in events:
        found = resolve(event.pop("_value"), assume.get(event["source"]), zone_offsets)
        event["_utc"] = found.pop("utc")
        event["utc"] = iso_utc(event["_utc"])
        event.update(found)
        if event["zone"] == "assumed":
            assumed.setdefault(event["source"], []).append(event["ref"])
    for source, refs in sorted(assumed.items()):
        findings.append(finding("warning", "assumed-zone", refs,
                                "%d event(s) from source '%s' are placed with a zone you supplied, "
                                "not one in the data. State the basis for it in the postmortem."
                                % (len(refs), source)))

    placed, unplaced, milestones, durations, gaps = analyse(events, args.gap_minutes * 60, findings)
    findings.sort(key=lambda f: (f["level"] != "error", f["code"], f["evidence"]))
    errors = sum(1 for f in findings if f["level"] == "error")
    warnings = len(findings) - errors

    def public(event):
        return {key: value for key, value in event.items() if not key.startswith("_")}

    return {
        "summary": {"events": len(events), "placed": len(placed), "not_placed": len(unplaced),
                    "gaps": len(gaps), "gap_threshold_seconds": int(args.gap_minutes * 60),
                    "errors": errors, "warnings": warnings,
                    "blocked": bool(errors or (warnings and args.fail_on == "warning"))},
        "inputs": inputs,
        "timeline": [public(e) for e in placed],
        "gaps": gaps,
        "not_placed": [public(e) for e in unplaced],
        "milestones": {tag: {"utc": e["utc"], "ref": e["ref"]} for tag, e in sorted(milestones.items())},
        "tags_present": [tag for tag in MILESTONES if any(e["tag"] == tag for e in events)],
        "durations": durations,
        "findings": findings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", action="append", default=[], metavar="FILE",
                        help="neutral events, JSONL or .csv")
    parser.add_argument("--git-log", action="append", default=[], metavar="[NAME=]FILE",
                        help="git log output in the documented format")
    parser.add_argument("--chat", action="append", default=[], metavar="[NAME=]FILE",
                        help="chat export with epoch timestamps")
    parser.add_argument("--assume-zone", action="append", default=[], metavar="SOURCE=ZONE",
                        help="place this source's zone-less timestamps in ZONE (+05:00, UTC, or a "
                             "zone name such as Europe/Oslo if this machine can resolve it)")
    parser.add_argument("--zone-offset", action="append", default=[], metavar="NAME=OFFSET",
                        help="offset of a zone abbreviation or name used in timestamps, e.g. IST=+05:30")
    parser.add_argument("--tag", action="append", default=[], metavar="TAG=EVIDENCE",
                        help="tag one event by its evidence reference, e.g. detected=alerts.jsonl:2. "
                             "Milestones: " + ", ".join(MILESTONES))
    parser.add_argument("--roles", metavar="FILE",
                        help="JSON object mapping names or user IDs to roles; replaces them in the output")
    parser.add_argument("--gap-minutes", type=float, default=15.0, metavar="N",
                        help="mark a gap when no source has an event for longer than this (default 15)")
    parser.add_argument("--fail-on", choices=("error", "warning"), default="error",
                        help="lowest finding level that makes the exit code 1 (default error)")
    parser.add_argument("--json", action="store_true", help="output JSON instead of Markdown")
    parser.add_argument("--out", metavar="PATH", help="write the output here instead of stdout")
    args = parser.parse_args(argv)
    try:
        result = build(args)
        output = json.dumps(result, indent=2) + "\n" if args.json else render_markdown(result)
        if args.out:
            try:
                Path(args.out).write_text(output, encoding="utf-8")
            except OSError as exc:
                raise InputError("cannot write %s: %s" % (args.out, exc))
            print("\n".join(["wrote %s" % args.out] + finding_lines(result)))
        else:
            sys.stdout.write(output)
    except InputError as exc:
        print("build_timeline.py: error: %s" % exc, file=sys.stderr)
        return 2
    return 1 if result["summary"]["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
