# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Sleep per night: joining the stages into nights and placing each on a day,
where the phone was (a time zone database is needed for that)."""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from ios_apps import health as hl
from ios_apps import health_sleep as hs
from tests import fixture_health as fh

NEEDS_ZONES = unittest.skipUnless(hs.database_available(),
                                  "no time zone database (install tzdata)")


def at(year, month, day, hour=0, minute=0):
    """Unix seconds for a UTC moment."""
    return datetime(year, month, day, hour, minute,
                    tzinfo=timezone.utc).timestamp()


def sample(start, end, stage, zone="America/New_York", source="Phone"):
    return {"start": start, "end": end, "stage": stage, "zone": zone,
            "source": source}


class UnionTests(unittest.TestCase):
    def test_overlaps_are_counted_once(self):
        self.assertEqual(hs.union_seconds([(0, 10), (5, 20), (30, 40)]), 30)
        self.assertEqual(hs.union_seconds([(0, 10), (0, 10)]), 10)
        self.assertEqual(hs.union_seconds([(0, 10), (2, 3)]), 10)
        self.assertEqual(hs.union_seconds([(10, 20), (0, 10)]), 20)
        self.assertEqual(hs.union_seconds([]), 0)

    def test_a_gap_is_not_counted(self):
        self.assertEqual(hs.union_seconds([(0, 10), (11, 20)]), 19)


class GroupingTests(unittest.TestCase):
    def test_a_gap_of_more_than_four_hours_starts_a_new_night(self):
        base = at(2026, 3, 2, 3)
        four = 4 * 3600
        joined = hs.split_into_nights([
            sample(base, base + 100, 1),
            sample(base + 100 + four, base + 200 + four, 1)])
        self.assertEqual(len(joined), 1)
        split = hs.split_into_nights([
            sample(base, base + 100, 1),
            sample(base + 100 + four + 1, base + 200 + four, 1)])
        self.assertEqual(len(split), 2)

    def test_the_latest_end_counts_not_the_last_record(self):
        base = at(2026, 3, 2, 3)
        groups = hs.split_into_nights([
            sample(base, base + 10 * 3600, 0),            # a long "in bed"
            sample(base + 3600, base + 7200, 3),
            sample(base + 9 * 3600, base + 9 * 3600 + 60, 2)])
        self.assertEqual(len(groups), 1)

    def test_records_in_any_order(self):
        base = at(2026, 3, 2, 3)
        groups = hs.split_into_nights([
            sample(base + 7200, base + 7300, 3), sample(base, base + 100, 3),
            sample(base + 3600, base + 3700, 4)])
        self.assertEqual(len(groups), 1)
        self.assertEqual([s["start"] for s in groups[0]],
                         [base, base + 3600, base + 7200])


@NEEDS_ZONES
class NightTests(unittest.TestCase):
    def one(self, samples):
        rows, problem = hs.per_night(samples)
        self.assertIsNone(problem)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def day_of(self, row):
        return datetime.fromtimestamp(row["night"], timezone.utc).date()

    def test_a_night_belongs_to_the_day_you_woke_up(self):
        # 23:00 Monday to 07:00 Tuesday in New York (UTC-5 in January)
        row = self.one([sample(at(2026, 1, 13, 4), at(2026, 1, 13, 12), 3)])
        self.assertEqual(str(self.day_of(row)), "2026-01-13")
        self.assertEqual((row["bed"], row["woke"]), ("23:00", "07:00"))
        self.assertEqual(row["asleep"], 8 * 3600)

    def test_the_stages_add_up(self):
        base = at(2026, 1, 13, 4)
        row = self.one([
            sample(base - 600, base + 8 * 3600 + 600, 0),
            sample(base, base + 3600, 3), sample(base + 3600, base + 5400, 4),
            sample(base + 5400, base + 7200, 5),
            sample(base + 7200, base + 7500, 2),
            sample(base + 7500, base + 8 * 3600, 1)])
        self.assertEqual(row["core"], 3600)
        self.assertEqual(row["deep"], 1800)
        self.assertEqual(row["rem"], 1800)
        self.assertEqual(row["awake"], 300)
        self.assertEqual(row["other"], 8 * 3600 - 7500)
        self.assertEqual(row["asleep"], 3600 + 1800 + 1800
                         + (8 * 3600 - 7500))
        self.assertEqual(row["in_bed"], 8 * 3600 + 1200)
        self.assertEqual(row["bed"], "22:50")
        self.assertEqual(row["asleep_at"], "23:00")

    def test_two_devices_are_not_added_together(self):
        base = at(2026, 1, 13, 4)
        row = self.one([
            sample(base, base + 8 * 3600, 1, source="Phone"),
            sample(base + 600, base + 8 * 3600 - 600, 3, source="Watch"),
            sample(base + 600, base + 8 * 3600 - 600, 3, source="Watch 2")])
        self.assertEqual(row["asleep"], 8 * 3600)
        self.assertEqual(row["core"], 8 * 3600 - 1200)
        self.assertEqual(row["source"], "Phone, Watch, Watch 2")

    def test_a_nap_is_a_night_of_its_own(self):
        rows, problem = hs.per_night([
            sample(at(2026, 1, 13, 4), at(2026, 1, 13, 12), 3),
            sample(at(2026, 1, 13, 19), at(2026, 1, 13, 20, 30), 3)])
        self.assertIsNone(problem)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["woke"] for r in rows], ["15:30", "07:00"])
        self.assertEqual(rows[0]["night"], rows[1]["night"])   # the same day

    def test_newest_first(self):
        rows, _ = hs.per_night([
            sample(at(2026, 1, 12, 4), at(2026, 1, 12, 12), 3),
            sample(at(2026, 1, 14, 4), at(2026, 1, 14, 12), 3),
            sample(at(2026, 1, 13, 4), at(2026, 1, 13, 12), 3)])
        self.assertEqual([r["woke"] for r in rows], ["07:00"] * 3)
        self.assertEqual([str(self.day_of(r)) for r in rows],
                         ["2026-01-14", "2026-01-13", "2026-01-12"])

    def test_waking_just_after_midnight_is_that_days(self):
        # 20:30 to 00:30 the next day in New York
        row = self.one([sample(at(2026, 1, 13, 1, 30), at(2026, 1, 13, 5, 30),
                               3)])
        self.assertEqual(str(self.day_of(row)), "2026-01-13")
        self.assertEqual(row["woke"], "00:30")

    def test_the_day_is_where_the_phone_woke_up(self):
        # went to bed in New York, woke in Tokyo: the last record decides
        row = self.one([
            sample(at(2026, 1, 13, 4), at(2026, 1, 13, 8), 3,
                   zone="America/New_York"),
            sample(at(2026, 1, 13, 8), at(2026, 1, 13, 12), 3,
                   zone="Asia/Tokyo")])
        self.assertEqual(str(self.day_of(row)), "2026-01-13")   # 21:00 Tokyo
        self.assertEqual(row["zone"], "Asia/Tokyo")
        self.assertEqual(row["woke"], "21:00")

    def test_clocks_going_forward_shorten_the_night_not_the_sleep(self):
        # US clocks went forward on 8 March 2026: 22:00 to 06:00 local is
        # seven hours of sleep
        row = self.one([sample(at(2026, 3, 8, 3), at(2026, 3, 8, 10), 3)])
        self.assertEqual((row["bed"], row["woke"]), ("22:00", "06:00"))
        self.assertEqual(row["asleep"], 7 * 3600)

    def test_a_record_with_no_zone_borrows_the_nights(self):
        row = self.one([
            sample(at(2026, 1, 13, 4), at(2026, 1, 13, 8), 3, zone=None),
            sample(at(2026, 1, 13, 8), at(2026, 1, 13, 12), 3)])
        self.assertEqual(row["zone"], "America/New_York")

    def test_what_cannot_be_placed_is_told(self):
        rows, problem = hs.per_night([
            sample(at(2026, 1, 13, 4), at(2026, 1, 13, 12), 3, zone=None),
            sample(at(2026, 1, 15, 4), at(2026, 1, 15, 12), 3)])
        self.assertEqual(len(rows), 1)
        self.assertIn("1 night could not be placed", problem)
        self.assertIn("no time zone", problem)
        rows, problem = hs.per_night([
            sample(at(2026, 1, 13, 4), at(2026, 1, 13, 12), 3,
                   zone="Nowhere/Atlantis")])
        self.assertEqual(rows, [])
        self.assertIn("one this computer does not know", problem)

    def test_odd_records_are_skipped(self):
        rows, problem = hs.per_night([
            sample(None, 5, 3), sample(5, None, 3), sample(10, 10, 3),
            sample(10, 5, 3), sample(0, 5, "x")])
        self.assertEqual((rows, problem), ([], None))


class WithoutADatabaseTests(unittest.TestCase):
    """What happens on a computer with no time zone database."""

    def setUp(self):
        hs.zone.cache_clear()
        self.addCleanup(hs.zone.cache_clear)

    def test_the_stages_are_not_added_up_and_the_reason_is_given(self):
        with mock.patch.dict(sys.modules, {"zoneinfo": None}):
            hs.zone.cache_clear()
            self.assertFalse(hs.database_available())
            rows, problem = hs.per_night([
                sample(at(2026, 1, 13, 4), at(2026, 1, 13, 12), 3)])
        self.assertEqual(rows, [])
        self.assertIn("pip install tzdata", problem)
        self.assertIn("no time zone database", problem)

    def test_a_missing_name_is_none_not_an_error(self):
        self.assertIsNone(hs.zone(None))
        self.assertIsNone(hs.zone(""))
        self.assertIsNone(hs.zone("Nowhere/Atlantis"))


@NEEDS_ZONES
class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-sleep-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def datasets(self, nights):
        path = os.path.join(self.tmp, "healthdb_secure.sqlite")
        conn = sqlite3.connect(path)
        fh.build_health_with_sleep(conn, nights)
        conn.close()
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        return {d.key: d for d in hl.HealthReader(conn).datasets()}

    def test_the_table_is_there_beside_the_stages(self):
        sets = self.datasets([(fh.NEW_YORK, [
            (fh.utc(2026, 1, 13, 4), fh.utc(2026, 1, 13, 6), 3),
            (fh.utc(2026, 1, 13, 6), fh.utc(2026, 1, 13, 7), 4),
            (fh.utc(2026, 1, 13, 7), fh.utc(2026, 1, 13, 8), 2)])])
        self.assertLess(list(sets).index("sleep_nights"),
                        list(sets).index("sleep"))
        self.assertEqual(len(sets["sleep"].rows), 3)
        row, = sets["sleep_nights"].rows
        self.assertEqual((row["core"], row["deep"], row["awake"]),
                         (7200, 3600, 3600))
        self.assertEqual(sets["sleep_nights"].title, "Sleep per night")
        self.assertEqual(sets["sleep"].note, "")
        self.assertIn("woke up", sets["sleep_nights"].note)

    def test_the_provenance_decides_the_time_zone(self):
        sets = self.datasets([
            (fh.NEW_YORK, [(fh.utc(2026, 1, 13, 4), fh.utc(2026, 1, 13, 12),
                            3)]),
            (fh.TOKYO, [(fh.utc(2026, 1, 20, 14), fh.utc(2026, 1, 20, 21),
                         3)])])
        rows = sets["sleep_nights"].rows
        self.assertEqual([r["woke"] for r in rows], ["06:00", "07:00"])
        self.assertEqual([r["zone"] for r in rows],
                         ["Asia/Tokyo", "America/New_York"])
        self.assertIn("Asia/Tokyo", sets["sleep_nights"].details(rows[0]))

    def test_records_with_no_zone_are_told_in_the_note(self):
        sets = self.datasets([
            (fh.NO_ZONE, [(fh.utc(2026, 1, 13, 4), fh.utc(2026, 1, 13, 12),
                           3)]),
            (fh.NEW_YORK, [(fh.utc(2026, 1, 15, 4), fh.utc(2026, 1, 15, 12),
                            3)])])
        self.assertEqual(len(sets["sleep_nights"].rows), 1)
        self.assertIn("1 night could not be placed",
                      sets["sleep_nights"].note)

    def test_with_no_placeable_night_there_is_no_table_and_a_note(self):
        sets = self.datasets([(fh.UNKNOWN_ZONE, [
            (fh.utc(2026, 1, 13, 4), fh.utc(2026, 1, 13, 12), 3)])])
        self.assertNotIn("sleep_nights", sets)
        self.assertIn("Sleep per night is not shown", sets["sleep"].note)

    def test_the_table_exports_like_the_others(self):
        sets = self.datasets([(fh.NEW_YORK, [
            (fh.utc(2026, 1, 13, 4), fh.utc(2026, 1, 13, 12), 3)])])
        table = sets["sleep_nights"]
        row = table.rows[0]
        self.assertEqual(table.columns[0].show(row["night"], row),
                         "2026-01-13")
        self.assertEqual(table.columns[3].show(row["asleep"], row), "8:00:00")


class OlderDatabaseTests(unittest.TestCase):
    """iOS versions whose provenances do not say a time zone."""

    def test_no_column_means_nothing_can_be_placed_and_nothing_breaks(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        fh.build_health(conn)
        sets = {d.key: d for d in hl.HealthReader(conn).datasets()}
        self.assertNotIn("sleep_nights", sets)
        self.assertEqual(len(sets["sleep"].rows), 7)
        self.assertIn("no time zone", sets["sleep"].note)


if __name__ == "__main__":
    unittest.main()
