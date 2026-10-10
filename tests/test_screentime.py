# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Screen Time: reading the day, week and hour files, and the tab in the
window."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from file_index import FileIndex
from ios_apps import screentime as st
from ios_apps.export_util import describe_duration
from tests import fixture_screentime as fs
from tests.gui_apps import AppGuiCase


def make_index(files):
    rows = [(f"id{n}", d, p, 1, len(data), 0, 0)
            for n, (d, p, data) in enumerate(files)]
    return FileIndex(rows)


class ReaderCase(unittest.TestCase):
    def setUp(self, **kw):
        self.tmp = tempfile.mkdtemp(prefix="ibe-st-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        files = fs.backup_files(**kw)
        self.index = make_index(files)
        for path in st.discover(self.index):
            data = next(d for _x, p, d in files if f"{fs.DOMAIN}/{p}" == path)
            with open(os.path.join(self.tmp, st.local_name(path)),
                      "wb") as handle:
                handle.write(data)
        self.data = {d.key: d for d in st.datasets(self.tmp)}


class FilesTests(unittest.TestCase):
    def test_what_is_copied(self):
        paths = st.discover(make_index(fs.backup_files()))
        kinds = [st.kind_of(p) for p in paths]
        self.assertEqual(kinds, ["Daily"] * 5 + ["Weekly"] + ["Hourly"] * 3)
        # (the broken ones are listed; they are skipped when read)
        self.assertEqual(len(paths), 9)
        self.assertEqual(len(set(map(st.local_name, paths))), 9)

    def test_only_the_recent_hours(self):
        index = make_index(fs.backup_files(hours=5))
        with mock.patch.object(st, "HOURS_KEPT", 2):
            hours = [p for p in st.discover(index)
                     if st.kind_of(p) == "Hourly"]
        self.assertEqual([p.rsplit("/", 1)[1] for p in hours], [
            f"{fs.cocoa(fs.DAY1) + 4 * 3600}.plist",
            f"{fs.cocoa(fs.DAY1) + 3 * 3600}.plist"])

    def test_names_of_copies_keep_kinds_and_devices_apart(self):
        daily = f"{st.FOLDER}/z/{fs.DEVICE_A}/Daily/ActivitySegments/5.0.plist"
        hourly = daily.replace("/Daily/", "/Hourly/")
        other = daily.replace(fs.DEVICE_A, fs.DEVICE_B)
        self.assertEqual(st.local_name(daily), "Daily-DD5B9B00-5.0.plist")
        names = {st.local_name(p) for p in (daily, hourly, other)}
        self.assertEqual(len(names), 3)

    def test_nothing(self):
        self.assertEqual(st.discover(None), [])
        self.assertEqual(st.discover(make_index([])), [])
        self.assertEqual(st.kind_of("a/b"), "")


class DaysTests(ReaderCase):
    def test_the_days(self):
        rows = {r["day"]: r for r in self.data["days"].rows}
        self.assertEqual(sorted(rows), ["2025-03-03", "2025-03-04",
                                        "2025-03-05"])
        first = rows["2025-03-03"]
        self.assertEqual((first["total"], first["pickups"], first["alerts"],
                          first["apps"]), (3600, 14, 13, 3))
        self.assertEqual((first["top_app"], first["top_time"]),
                         ("Safari", 2000))
        self.assertEqual(rows["2025-03-04"]["pickups"], 10)

    def test_a_day_with_no_use(self):
        empty = {r["day"]: r for r in self.data["days"].rows}["2025-03-05"]
        self.assertEqual((empty["total"], empty["pickups"], empty["apps"],
                          empty["top_app"]), (0, 0, 0, ""))

    def test_days_are_dated_where_the_phone_was(self):
        # the days begin at 04:00 UTC: local midnight in a zone 4 hours
        # behind UTC, so the 3rd begins on the 3rd (not on the 2nd or 4th)
        self.assertEqual(st._zone_offset([fs.cocoa(fs.DAY1)]), -4 * 3600)
        self.assertEqual(st._zone_offset([fs.cocoa(fs.DAY1) - 4 * 3600
                                          - 3600 * 2]), 2 * 3600)
        self.assertEqual(st._zone_offset([]), 0)

    def test_the_details(self):
        text = self.data["days"].details(self.data["days"].rows[0])
        self.assertIn("Pickups:", text)
        self.assertIn("Most used: Safari", text)

    def test_the_order_is_newest_first(self):
        data = self.data["days"]
        self.assertEqual([r["day"] for r in data.sorted_rows(data.rows)],
                         ["2025-03-05", "2025-03-04", "2025-03-03"])

    def test_broken_files_are_skipped(self):
        self.assertEqual(len(self.data["days"].rows), 3)
        self.assertIsNone(st.read_record(os.path.join(self.tmp, "nothing")))


class OtherTablesTests(ReaderCase):
    def test_apps(self):
        rows = {r["bundle"]: r for r in self.data["apps"].rows}
        safari = rows["com.apple.mobilesafari"]
        self.assertEqual((safari["app"], safari["time"], safari["days_used"],
                          safari["per_day"], safari["pickups"],
                          safari["alerts"], safari["last"]),
                         ("Safari", 7000, 2, 3500, 13, 4, "2025-03-04"))
        game = rows["com.example.game"]
        self.assertEqual((game["app"], game["time"]),
                         ("com.example.game", 3000))
        self.assertEqual(rows["com.apple.MobileSMS"]["days_used"], 1)

    def test_websites(self):
        rows = {r["site"]: r for r in self.data["sites"].rows}
        self.assertEqual((rows["example.com"]["time"],
                          rows["example.com"]["days_used"]), (1000, 2))
        self.assertEqual(rows["news.example.org"]["days_used"], 1)

    def test_weeks(self):
        (week,) = self.data["weeks"].rows
        self.assertEqual((week["week"], week["total"], week["pickups"]),
                         ("2025-03-03", 10800, 17))
        self.assertAlmostEqual(week["per_day"], 10800 / 7)

    def test_hours(self):
        rows = {r["hour"]: r for r in self.data["hours"].rows}
        self.assertEqual(sorted(rows), ["2025-03-03 00:00",
                                        "2025-03-03 01:00",
                                        "2025-03-03 02:00"])
        self.assertEqual((rows["2025-03-03 01:00"]["total"],
                          rows["2025-03-03 01:00"]["pickups"],
                          rows["2025-03-03 01:00"]["top_app"]),
                         (1200, 2, "Safari"))

    def test_app_names(self):
        self.assertEqual(st.app_name("com.apple.mobilesafari"), "Safari")
        self.assertEqual(st.app_name("com.example.x"), "com.example.x")

    def test_without_hours_or_weeks_those_tables_are_missing(self):
        ReaderCase.setUp(self, hours=0)
        self.assertNotIn("hours", self.data)

    def test_a_second_device_adds_a_column_and_rows(self):
        ReaderCase.setUp(self, second_device=True)
        self.assertEqual(len(self.data["days"].rows), 4)
        self.assertIn("device", [c.key for c in self.data["days"].columns])
        self.assertIn("com.example.tablet",
                      [r["bundle"] for r in self.data["apps"].rows])

    def test_one_device_has_no_device_column(self):
        self.assertNotIn("device",
                         [c.key for c in self.data["days"].columns])


class ScreenTimeGuiCase(AppGuiCase):
    def open_screentime(self, encrypted=False, **kw):
        self.open_files(fs.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Screen Time")

    def show(self):
        tab = self.show_tab("Screen Time")
        self.wait_for(lambda: tab.datasets, "the screen time tables")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]


class WindowTests(ScreenTimeGuiCase):
    def test_the_tab_appears_only_with_the_data(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertNotIn("Screen Time", self.tab_titles())
        self.open_screentime()
        self.assertIn("Screen Time", self.tab_titles())

    def test_the_tables(self):
        self.open_screentime()
        tab = self.show()
        self.assertEqual(list(tab.datasets),
                         ["days", "weeks", "apps", "sites", "hours"])
        self.assertEqual(self.column("day"),
                         ["2025-03-05", "2025-03-04", "2025-03-03"])
        self.assertEqual(self.column("total"),
                         [describe_duration(x) for x in (0, 7200, 3600)])
        tab.dataset_var.set("Apps")
        tab.choose_dataset()
        self.assertEqual(self.column("app")[0], "Safari")

    def test_the_same_start_time_in_two_kinds_does_not_clash(self):
        # the first day and the first hour begin at the same moment, and so
        # have the same file name; both must arrive
        self.open_screentime()
        tab = self.show()
        self.assertEqual(len(tab.datasets["days"].rows), 3)
        self.assertEqual(len(tab.datasets["hours"].rows), 3)

    def test_search(self):
        self.open_screentime()
        tab = self.show()
        tab.dataset_var.set("Apps")
        tab.choose_dataset()
        tab.search_var.set("game")
        tab.refresh()
        self.assertEqual(self.column("app"), ["com.example.game"])

    def test_original_files(self):
        self.open_screentime()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        index = self.explorer.apps.index
        wanted = {index.get(p).file_id
                  for p in st.discover(index)}
        self.assertEqual(set(ids), wanted)
        self.assertEqual(len(ids), 9)

    def test_an_encrypted_backup(self):
        self.open_screentime(encrypted=True)
        tab = self.show()
        self.assertEqual(len(tab.datasets["days"].rows), 3)


if __name__ == "__main__":
    unittest.main()
