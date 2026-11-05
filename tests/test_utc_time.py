import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "postmortem-timeline" / "scripts"))

import utc_time  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("America/New_York")
    HAVE_ZONE_DATA = True
except Exception:  # no zoneinfo module or no time zone data on this machine
    HAVE_ZONE_DATA = False


def utc(value, **kwargs):
    return utc_time.iso_utc(utc_time.resolve(value, **kwargs)["utc"])


def problem(value, **kwargs):
    return utc_time.resolve(value, **kwargs)["problem"]


class OffsetTests(unittest.TestCase):
    def test_accepted_forms(self):
        self.assertEqual(utc_time.parse_offset("Z"), timedelta(0))
        self.assertEqual(utc_time.parse_offset("utc"), timedelta(0))
        self.assertEqual(utc_time.parse_offset("+05:30"), timedelta(hours=5, minutes=30))
        self.assertEqual(utc_time.parse_offset("+0530"), timedelta(hours=5, minutes=30))
        self.assertEqual(utc_time.parse_offset("+05"), timedelta(hours=5))
        self.assertEqual(utc_time.parse_offset("-07:00"), timedelta(hours=-7))
        self.assertEqual(utc_time.parse_offset("+14:00"), timedelta(hours=14))

    def test_rejected_forms(self):
        for text in ("+5", "+5:30", "+14:30", "-15:00", "+05:60", "UTC+5", "EST", ""):
            self.assertIsNone(utc_time.parse_offset(text), text)

    def test_format_round_trip(self):
        for text in ("+05:30", "-07:00", "+00:00", "-03:30", "+12:45"):
            self.assertEqual(utc_time.format_offset(utc_time.parse_offset(text)), text)


class ResolveTests(unittest.TestCase):
    def test_z_and_utc_words(self):
        self.assertEqual(utc("2026-03-14T09:10:02Z"), "2026-03-14T09:10:02Z")
        self.assertEqual(utc("2026-03-14 09:10:02 UTC"), "2026-03-14T09:10:02Z")
        self.assertEqual(utc_time.resolve("2026-03-14T09:10:02Z")["zone"], "utc")

    def test_offsets_are_subtracted(self):
        self.assertEqual(utc("2026-03-14T14:22:05+05:30"), "2026-03-14T08:52:05Z")
        self.assertEqual(utc("2026-03-14T02:05:00-07:00"), "2026-03-14T09:05:00Z")
        self.assertEqual(utc("2026-03-14 14:22:05 +0530"), "2026-03-14T08:52:05Z")
        self.assertEqual(utc("2026-03-14T14:22:05+05"), "2026-03-14T09:22:05Z")

    def test_offset_can_cross_midnight(self):
        self.assertEqual(utc("2026-05-09T01:41:07+02:00"), "2026-05-08T23:41:07Z")
        self.assertEqual(utc("2026-12-31T20:00:00-05:00"), "2027-01-01T01:00:00Z")

    def test_fraction_with_dot_or_comma(self):
        self.assertEqual(utc("2026-03-14T09:10:02.5Z"), "2026-03-14T09:10:02.500000Z")
        self.assertEqual(utc("2026-03-14 09:10:02,123+00:00"), "2026-03-14T09:10:02.123000Z")
        self.assertEqual(utc("2026-03-14T09:10:02.123456789Z"), "2026-03-14T09:10:02.123456Z")

    def test_minute_precision_is_recorded(self):
        found = utc_time.resolve("2026-03-14 09:10Z")
        self.assertTrue(found["minute_precision"])
        self.assertFalse(utc_time.resolve("2026-03-14 09:10:00Z")["minute_precision"])

    def test_epoch_seconds_and_milliseconds(self):
        self.assertEqual(utc(1773479610), "2026-03-14T09:13:30Z")
        self.assertEqual(utc("1773479610"), "2026-03-14T09:13:30Z")
        self.assertEqual(utc("1773479610.000200"), "2026-03-14T09:13:30.000200Z")
        self.assertEqual(utc(1773479610123), "2026-03-14T09:13:30.123000Z")
        self.assertEqual(utc_time.resolve(1773479610)["zone"], "epoch")

    def test_other_number_magnitudes_are_refused(self):
        for value in ("20260314091205", "1773479610123456", 1773479610123456789, 12345, 0):
            self.assertEqual(problem(value), "bad-timestamp", value)

    def test_no_zone_is_not_placed(self):
        found = utc_time.resolve("2026-03-14 14:02:11")
        self.assertEqual(found["problem"], "no-zone")
        self.assertIsNone(found["utc"])
        self.assertIsNone(found["zone"])

    def test_assumed_offset_places_and_marks_the_event(self):
        found = utc_time.resolve("2026-03-14 14:02:11", assumed=utc_time.zone_spec("+05:00"))
        self.assertEqual(utc_time.iso_utc(found["utc"]), "2026-03-14T09:02:11Z")
        self.assertEqual((found["zone"], found["zone_detail"]), ("assumed", "+05:00"))

    def test_assumed_zone_does_not_override_a_zone_in_the_data(self):
        found = utc_time.resolve("2026-03-14T09:10:02Z", assumed=utc_time.zone_spec("+05:00"))
        self.assertEqual(utc_time.iso_utc(found["utc"]), "2026-03-14T09:10:02Z")
        self.assertEqual(found["zone"], "utc")

    def test_abbreviations_are_never_guessed(self):
        for text in ("2026-03-14 14:32 IST", "2026-03-14 04:02:00 EST", "2026-03-14 10:02 CEST"):
            self.assertEqual(problem(text), "ambiguous-zone", text)

    def test_abbreviation_with_declared_offset(self):
        found = utc_time.resolve("2026-03-14 14:32 IST", zone_offsets={"IST": timedelta(hours=5, minutes=30)})
        self.assertEqual(utc_time.iso_utc(found["utc"]), "2026-03-14T09:02:00Z")
        self.assertEqual((found["zone"], found["zone_detail"]), ("assumed", "IST=+05:30"))

    def test_unreadable_values(self):
        for value in (None, "", "   ", True, [], {}, "yesterday", "2026-03-14", "09:10:02",
                      "2026-02-30T09:00:00Z", "2026-03-14T25:00:00Z", "2026-03-14T09:00:00+15:00",
                      "2026-03-14 09:00 UTC+5", "Sat, 14 Mar 2026 09:12:05 +0500",
                      "2026-03-14T09:00:00-04:00[America/New_York]"):
            self.assertEqual(problem(value), "bad-timestamp", value)

    def test_zone_name_without_zone_data_is_not_placed(self):
        with mock.patch.object(utc_time, "named_zone_offset", return_value=(None, "unresolved-zone")):
            found = utc_time.resolve("2026-03-14 09:00 America/New_York")
        self.assertEqual(found["problem"], "unresolved-zone")
        self.assertIsNone(found["utc"])

    def test_zone_name_with_declared_offset_needs_no_zone_data(self):
        with mock.patch.object(utc_time, "named_zone_offset", return_value=(None, "unresolved-zone")):
            found = utc_time.resolve("2026-03-14 09:00 America/New_York",
                                     zone_offsets={"America/New_York": timedelta(hours=-4)})
        self.assertEqual(utc_time.iso_utc(found["utc"]), "2026-03-14T13:00:00Z")

    def test_unknown_zone_name_is_unresolved(self):
        self.assertEqual(problem("2026-03-14 09:00 Nowhere/Nonexistent_City"), "unresolved-zone")

    def test_zone_spec_rejects_what_it_cannot_resolve(self):
        with self.assertRaises(utc_time.InputError):
            utc_time.zone_spec("Nowhere/Nonexistent_City")
        with self.assertRaises(utc_time.InputError):
            utc_time.zone_spec("EST")

    def test_zone_offset_pair(self):
        self.assertEqual(utc_time.zone_offset_pair("IST=+05:30"), ("IST", timedelta(hours=5, minutes=30)))
        for text in ("IST", "IST=", "=+05:30", "IST=EST", "a b=+01:00"):
            with self.assertRaises(utc_time.InputError):
                utc_time.zone_offset_pair(text)


@unittest.skipUnless(HAVE_ZONE_DATA, "this machine has no time zone data for zoneinfo")
class ZoneDataTests(unittest.TestCase):
    def test_zone_name_uses_the_offset_for_that_date(self):
        self.assertEqual(utc("2026-01-14 09:00 America/New_York"), "2026-01-14T14:00:00Z")
        self.assertEqual(utc("2026-07-14 09:00 America/New_York"), "2026-07-14T13:00:00Z")
        self.assertEqual(utc_time.resolve("2026-07-14 09:00 America/New_York")["zone"], "named")

    def test_repeated_hour_is_refused(self):
        self.assertEqual(problem("2026-11-01 01:30 America/New_York"), "dst-transition")

    def test_skipped_hour_is_refused(self):
        self.assertEqual(problem("2026-03-08 02:30 America/New_York"), "dst-transition")

    def test_assumed_zone_name(self):
        found = utc_time.resolve("2026-07-14 09:00:00", assumed=utc_time.zone_spec("America/New_York"))
        self.assertEqual(utc_time.iso_utc(found["utc"]), "2026-07-14T13:00:00Z")
        self.assertEqual((found["zone"], found["zone_detail"]), ("assumed", "America/New_York"))


class EpochTests(unittest.TestCase):
    def test_range_edges(self):
        self.assertEqual(utc_time.parse_epoch("1000000000"), datetime(2001, 9, 9, 1, 46, 40))
        self.assertIsNone(utc_time.parse_epoch("999999999"))
        self.assertIsNone(utc_time.parse_epoch("10000000000"))
        self.assertEqual(utc_time.parse_epoch("1000000000000"), datetime(2001, 9, 9, 1, 46, 40))


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = utc_time.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_all_converted_exits_zero(self):
        code, out, _ = self.run_main(["2026-03-14T14:22:05+05:30", "1773479610"])
        self.assertEqual(code, 0)
        self.assertIn("2026-03-14T08:52:05Z", out)
        self.assertIn("2026-03-14T09:13:30Z", out)

    def test_unplaced_exits_one_and_names_the_problem(self):
        code, out, _ = self.run_main(["2026-03-14 14:02:11"])
        self.assertEqual(code, 1)
        self.assertIn("NOT PLACED, no-zone", out)

    def test_assume_zone_and_json(self):
        code, out, _ = self.run_main(["--assume-zone", "+05:00", "--json", "2026-03-14 14:02:11"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(rows[0]["utc"], "2026-03-14T09:02:11Z")
        self.assertEqual(rows[0]["zone"], "assumed")
        self.assertEqual(rows[0]["raw"], "2026-03-14 14:02:11")

    def test_bad_zone_argument_is_a_usage_error(self):
        code, _, err = self.run_main(["--assume-zone", "EST", "2026-03-14 14:02:11"])
        self.assertEqual(code, 2)
        self.assertIn("--assume-zone", err)
        code, _, _ = self.run_main(["--zone-offset", "IST", "2026-03-14 14:02 IST"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
