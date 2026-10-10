# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Calendar: reading, exporting (iCalendar) and the tab in the window."""

import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from ios_apps import calendar_events as ce
from ios_apps import ics
from ios_apps import records_export as rx
from ios_apps import records_view as rv
from ios_apps.common import APPLE_EPOCH, format_datetime
from tests import fixture_calendar as fc
from tests.fixture_apps import T0, database_bytes
from tests.gui_apps import AppGuiCase

DAY = fc.DAY


def connect(testcase, builder=fc.build):
    folder = tempfile.mkdtemp(prefix="ibe-cal-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, "Calendar.sqlitedb")
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


def slurp(path, mode="r", encoding="utf-8"):
    options = {} if "b" in mode else {"encoding": encoding, "newline": ""}
    with open(path, mode, **options) as handle:
        return handle.read()


class CalendarCase(unittest.TestCase):
    def setUp(self):
        self.data = {d.key: d for d in ce.datasets(connect(self))}
        self.events = self.data["events"].rows
        self.by = {r["id"]: r for r in self.events}


class ReaderTests(CalendarCase):
    def test_events_and_calendars(self):
        self.assertEqual(list(self.data), ["events", "calendars"])
        self.assertEqual(len(self.events), 10)          # not the reminder
        self.assertNotIn(20, self.by)

    def test_the_default_order_is_newest_first(self):
        data = self.data["events"]
        ordered = data.sorted_rows(data.rows)
        starts = [r["start"] for r in ordered]
        self.assertEqual(starts, sorted(starts, reverse=True))

    def test_what_an_event_knows(self):
        dentist = self.by[10]
        self.assertEqual((dentist["title"], dentist["calendar"],
                          dentist["account"], dentist["place"]),
                         ("Dentist", "Home", "iCloud",
                          "Office 1 Main St, Springfield"))
        self.assertEqual(dentist["start"], T0 + 9 * 3600 + APPLE_EPOCH)
        self.assertIn("second line", dentist["notes"])
        self.assertEqual(self.by[15]["url"], "https://example.com/vitamins")
        self.assertEqual(self.by[18]["title"], "")

    def test_repeats(self):
        self.assertEqual(self.by[12]["repeat"], "Every year")
        self.assertEqual(self.by[13]["repeat"], "Every 2 weeks")
        self.assertEqual(self.by[15]["repeat"], "Every day")
        self.assertEqual(self.by[10]["repeat"], "")

    def test_the_calendars(self):
        rows = {r["calendar"]: r for r in self.data["calendars"].rows}
        self.assertEqual(rows["Home"]["events"], 6)
        self.assertEqual(rows["Work <team>"]["events"], 2)
        self.assertEqual(rows["US Holidays"]["account"], "Holidays")
        self.assertEqual(rows["Home"]["first"] < rows["Home"]["last"], True)

    def test_how_the_time_is_written(self):
        text = {pk: ce.when_text(r) for pk, r in self.by.items()}
        start = format_datetime(self.by[10]["start"])
        self.assertEqual(text[10], f"{start} - "
                         f"{format_datetime(self.by[10]['end'])[11:]}")
        self.assertRegex(text[11], r"^\d{4}-\d\d-\d\d$")        # one whole day
        self.assertRegex(text[16], r"^\d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d$")
        self.assertEqual(text[16].split(" to ")[1],
                         ics_date(self.by[16]["start"] + 2 * DAY))
        self.assertRegex(text[17], r"^\d\d-\d\d \(year not set\)$")

    def test_an_event_past_midnight_names_both_days(self):
        row = dict(self.by[19])
        stamp = 1_700_000_000 - 1_700_000_000 % DAY      # midnight UTC
        row["start"], row["end"] = stamp + 3600, stamp + 7200
        with mock.patch("ios_apps.common.format_datetime",
                        lambda t: ics.utc(t)[:4] + "-01-" + ics.utc(t)[6:8]
                        + " " + ics.utc(t)[9:11] + ":00"):
            self.assertEqual(ce.when_text(row),
                             "2023-01-14 01:00 - 02:00")
            row["end"] = stamp + DAY + 7200
            self.assertEqual(ce.when_text(row),
                             "2023-01-14 01:00 - 2023-01-15 02:00")

    def test_an_all_day_event_keeps_its_date_in_any_time_zone(self):
        for zone in ("UTC", "Pacific/Auckland", "America/Los_Angeles"):
            with self.subTest(zone=zone):
                with mock.patch.dict(os.environ, {"TZ": zone}):
                    if hasattr(__import__("time"), "tzset"):
                        __import__("time").tzset()
                    self.assertEqual(ce.when_text(self.by[11]),
                                     ics_date(self.by[11]["start"]))
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()

    def test_a_database_with_only_the_events_table(self):
        def build(conn):
            conn.execute("CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY "
                         "KEY, summary TEXT, start_date REAL, end_date REAL, "
                         "all_day INTEGER)")
            conn.execute("INSERT INTO CalendarItem VALUES (1, 'Lonely', 1000, "
                         "2000, 0)")
            conn.commit()

        data = ce.datasets(connect(self, build))
        (row,) = data[0].rows
        self.assertEqual((row["title"], row["calendar"], row["place"]),
                         ("Lonely", "", ""))

    def test_an_empty_database_gives_no_tables(self):
        def build(conn):
            conn.execute("CREATE TABLE other (x)")
            conn.commit()

        self.assertEqual(ce.datasets(connect(self, build)), [])


def ics_date(stamp):
    text = ics.day(stamp)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def unfold(text):
    return text.replace("\r\n ", "")


class IcsTests(CalendarCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="ibe-ics-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.path,) = rx.export(self.data["events"], self.events, "ics",
                                 self.tmp)
        self.text = unfold(slurp(self.path, "r", "utf-8"))
        self.events_text = {}
        for block in re.findall(r"BEGIN:VEVENT\r\n(.*?)END:VEVENT",
                                self.text, re.S):
            uid = re.search(r"UID:(.*)", block.replace("\r", "")).group(1)
            self.events_text[uid] = block.replace("\r\n", "\n")

    def event(self, pk):
        return self.events_text[f"UUID-{pk}"]

    def test_the_file_is_a_calendar(self):
        self.assertTrue(self.text.startswith(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))
        self.assertTrue(self.text.endswith("END:VCALENDAR\r\n"))
        self.assertEqual(len(self.events_text), 10)
        self.assertNotIn("\n", self.text.replace("\r\n", ""))     # CRLF only

    def test_lines_are_short(self):
        raw = slurp(self.path, "rb", None).decode("utf-8")
        for line in raw.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)

    def test_timed_events_are_in_utc(self):
        text = self.event(10)
        start = self.by[10]["start"]
        self.assertIn(f"DTSTART:{ics.utc(start)}\n", text)
        self.assertIn(f"DTEND:{ics.utc(self.by[10]['end'])}\n", text)
        # written out in full, so the helpers are not only checked against
        # themselves
        self.assertIn("DTSTART:20250828T000640Z" + chr(10), text)
        self.assertIn("DTEND:20250828T010640Z" + chr(10), text)
        self.assertIn("DTSTART;VALUE=DATE:20250828" + chr(10), self.event(11))

    def test_all_day_events_are_dates_and_end_the_day_after(self):
        one = self.event(11)
        start = self.by[11]["start"]
        self.assertIn(f"DTSTART;VALUE=DATE:{ics.day(start)}\n", one)
        self.assertIn(f"DTEND;VALUE=DATE:{ics.day(start + DAY)}\n", one)
        three = self.event(16)
        start = self.by[16]["start"]
        self.assertIn(f"DTEND;VALUE=DATE:{ics.day(start + 3 * DAY)}\n", three)

    def test_text_is_escaped(self):
        text = self.event(10)
        self.assertIn("DESCRIPTION:Bring the form\\;\\nsecond line\\, with a "
                      "comma\n", text)
        self.assertIn("LOCATION:Office 1 Main St\\, Springfield\n", text)
        self.assertIn("SUMMARY:Team <offsite>\n", self.event(11))
        self.assertIn("SUMMARY:(no title)\n", self.event(18))

    def test_repeats(self):
        self.assertIn("RRULE:FREQ=YEARLY\n", self.event(12))
        self.assertIn("RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=5\n", self.event(13))
        until = ics.utc(self.by[15]["repeat_rule"]["end_date"] + APPLE_EPOCH)
        self.assertIn(f"RRULE:FREQ=DAILY;UNTIL={until}\n", self.event(15))
        month = int(ics.day(self.by[14]["start"])[4:6])
        self.assertIn(f"RRULE:FREQ=YEARLY;BYDAY=-1MO;BYMONTH={month};"
                      "COUNT=6\n", self.event(14))
        self.assertNotIn("RRULE", self.event(10))

    def test_the_web_address_is_kept(self):
        self.assertIn("URL:https://example.com/vitamins\n", self.event(15))

    def test_the_other_formats_still_work(self):
        for fmt in ("csv", "html", "txt", "json"):
            with self.subTest(fmt=fmt):
                (path,) = rx.export(self.data["events"], self.events, fmt,
                                    self.tmp)
                self.assertTrue(os.path.isfile(path))
        page = slurp(os.path.join(self.tmp, "events.html"))
        self.assertIn("Team &lt;offsite&gt;", page)
        self.assertNotIn("<offsite>", page)

    def test_the_formats_offered(self):
        self.assertEqual(list(rx.formats_for(self.data["events"]))[-1], "ics")
        self.assertNotIn("ics", rx.formats_for(self.data["calendars"]))


class CalendarGuiCase(AppGuiCase):
    def open_calendar(self, encrypted=False):
        self.open_files(fc.backup_files(), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Calendar")

    def show(self):
        tab = self.show_tab("Calendar")
        self.wait_for(lambda: tab.datasets, "the tables")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]


class WindowTests(CalendarGuiCase):
    def test_the_tab_appears_only_with_a_calendar(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        self.open_calendar()
        self.assertEqual(self.tab_titles(), ["Files", "Calendar"])

    def test_the_events(self):
        self.open_calendar()
        tab = self.show()
        self.assertEqual(tab.state_var.get(), "10 rows")
        starts = [tab._items[i]["start"] for i in tab.tree.get_children()]
        self.assertEqual(starts, sorted(starts, reverse=True))
        self.assertIn("Dentist", self.column("title"))
        self.assertIn("(year not set)", " ".join(self.column("start")))

    def test_the_details_of_an_event(self):
        self.open_calendar()
        tab = self.show()
        row = next(r for r, v in tab._items.items() if v["title"] == "Dentist")
        tab.tree.selection_set(row)
        self.root.update()
        text = tab.detail.get("1.0", "end")
        for expected in ("Dentist", "Calendar: Home",
                         "Place: Office 1 Main St, Springfield",
                         "Notes: Bring the form;"):
            self.assertIn(expected, text)

    def test_search_in_the_notes_and_the_calendar_name(self):
        self.open_calendar()
        tab = self.show()
        tab.search_var.set("second line")
        tab.refresh()
        self.assertEqual(self.column("title"), ["Dentist"])
        tab.search_var.set("us holidays")
        tab.refresh()
        self.assertEqual(sorted(self.column("title")),
                         ["Birthday, no year", "Memorial Day"])

    def test_the_calendars_table(self):
        self.open_calendar()
        tab = self.show()
        tab.dataset_var.set("Calendars")
        tab.choose_dataset()
        self.assertEqual(sorted(self.column("calendar")),
                         ["Home", "US Holidays", "Work <team>"])

    def test_export_as_a_calendar_file(self):
        self.open_calendar()
        tab = self.show()
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(rv, "ask_export",
                               return_value=("ics", "all", out)) as ask:
            tab.export()
            self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo")
        self.assertIn("ics", ask.call_args.args[2])
        self.assertTrue(slurp(os.path.join(out, "events.ics")).startswith(
            "BEGIN:VCALENDAR"))

    def test_original_files(self):
        self.open_calendar()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        self.assertEqual(ids, [self.ids[(
            "HomeDomain", "Library/Calendar/Calendar.sqlitedb")]])

    def test_an_encrypted_backup(self):
        self.open_calendar(encrypted=True)
        self.show()
        self.assertEqual(len(self.column("title")), 10)


if __name__ == "__main__":
    unittest.main()
