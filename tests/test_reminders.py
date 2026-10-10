# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reminders: reading several account databases, exporting (to-do file) and
the tab in the window."""

import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from file_index import FileIndex
from ios_apps import records_export as rx
from ios_apps import records_view as rv
from ios_apps import reminders as rm
from ios_apps.common import APPLE_EPOCH
from tests import fixture_reminders as fr
from tests.fixture_apps import T0
from tests.gui_apps import AppGuiCase

DAY = fr.DAY


def make_index(files):
    rows = [(f"id{n}", d, p, 1, len(data), 0, 0)
            for n, (d, p, data) in enumerate(files)]
    return FileIndex(rows)


class ReaderCase(unittest.TestCase):
    def setUp(self, **kw):
        self.tmp = tempfile.mkdtemp(prefix="ibe-rem-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        files = fr.backup_files(**kw)
        self.index = make_index(files)
        for _domain, path, data in files:
            with open(os.path.join(self.tmp, os.path.basename(path)),
                      "wb") as handle:
                handle.write(data)
        found = rm.discover(self.index)
        self.paths = found
        self.conn = sqlite3.connect(os.path.join(
            self.tmp, os.path.basename(found[0])))
        self.addCleanup(self.conn.close)
        self.data = {d.key: d for d in rm.datasets(self.conn, self.index)}
        self.rows = self.data["reminders"].rows
        self.by = {r["title"] or "(none)": r for r in self.rows}


class ReaderTests(ReaderCase):
    def test_stores_are_found_largest_first(self):
        self.assertEqual(self.paths[0], f"HomeDomain/{fr.STORE_A}")
        self.assertEqual(len(self.paths), 3)
        self.assertEqual(sorted(p.rsplit("/", 1)[1] for p in self.paths),
                         ["Data-AAAA.sqlite", "Data-BBBB.sqlite",
                          "Data-local.sqlite"])        # no -wal, no notes
        self.assertEqual(rm.discover(None), [])
        self.assertEqual(rm.discover(make_index([])), [])

    def test_every_store_is_read(self):
        self.assertEqual(sorted(self.by), sorted([
            "Buy milk", "Call plumber", "Send report", "Check the wording",
            "(none)", "Thrown away", "Nowhere", "Water the plants"]))

    def test_lists_and_accounts(self):
        self.assertEqual((self.by["Buy milk"]["list"],
                          self.by["Buy milk"]["account"]),
                         ("Groceries <home>", "iCloud"))
        self.assertEqual((self.by["Send report"]["list"]), "Work")
        self.assertEqual((self.by["Water the plants"]["list"],
                          self.by["Water the plants"]["account"]),
                         ("Local list", "On My iPhone"))
        self.assertEqual(self.by["Nowhere"]["list"], "")

    def test_due_dates(self):
        milk = self.by["Buy milk"]
        self.assertEqual(milk["due"], fr.D0 + 2 * DAY + APPLE_EPOCH)
        self.assertTrue(milk["all_day"])
        self.assertIsNone(self.by["Call plumber"]["due"])
        self.assertEqual(self.by["Send report"]["due"],
                         T0 + 3600 + APPLE_EPOCH)

    def test_what_is_known_of_a_reminder(self):
        milk = self.by["Buy milk"]
        self.assertEqual((milk["priority"], milk["flagged"], milk["done"]),
                         ("High", True, False))
        self.assertIn("not oat", milk["notes"])
        report = self.by["Send report"]
        self.assertEqual((report["priority"], report["status"],
                          report["completed"]),
                         ("Medium", "Done", T0 + 7200 + APPLE_EPOCH))
        self.assertEqual(self.by["Check the wording"]["priority"], "Low")
        self.assertEqual(self.by["Nowhere"]["priority"], "")   # 99: unknown

    def test_subtasks_name_their_parent(self):
        sub = self.by["Check the wording"]
        self.assertTrue(sub["is_subtask"])
        self.assertEqual(sub["parent"], "Send report")
        self.assertFalse(self.by["Buy milk"]["is_subtask"])

    def test_deleted_ones_are_marked(self):
        self.assertEqual(self.by["Thrown away"]["status"], "Deleted")

    def test_the_lists_table(self):
        rows = {(r["account"], r["list"]): r
                for r in self.data["lists"].rows}
        self.assertEqual(rows[("iCloud", "Groceries <home>")]["total"], 3)
        # (the deleted one is not counted)
        self.assertEqual(rows[("iCloud", "Work")]["total"], 2)
        self.assertEqual(rows[("iCloud", "Work")]["open"], 1)
        self.assertEqual(rows[("On My iPhone", "Local list")]["open"], 1)
        self.assertNotIn(("iCloud", "Gone list"), rows)
        # a list of a deleted account is shown under the account that is left
        self.assertEqual(rows[("iCloud", "Orphan list")]["total"], 0)

    def test_one_store_alone(self):
        ReaderCase.setUp(self, second=False, local=False)
        self.assertNotIn("Water the plants", self.by)
        self.assertEqual(len(self.paths), 1)

    def test_nothing_at_all(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(rm.datasets(conn, make_index([])), [])


def todo_blocks(text):
    text = text.replace("\r\n ", "")
    return re.findall(r"BEGIN:VTODO\r\n(.*?)END:VTODO", text, re.S)


class ToDoFileTests(ReaderCase):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "out")
        (path,) = rx.export(self.data["reminders"], self.rows, "ics",
                            self.out)
        with open(path, "rb") as handle:
            self.text = handle.read().decode("utf-8")
        self.blocks = todo_blocks(self.text)

    def block(self, word):
        return next(b for b in self.blocks if f"SUMMARY:{word}" in b)

    def test_a_calendar_of_to_dos(self):
        self.assertTrue(self.text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertEqual(len(self.blocks), 7)       # not the deleted one
        self.assertNotIn("Thrown away", self.text)

    def test_all_day_due_dates_are_dates(self):
        block = self.block("Buy milk")
        self.assertIn("DUE;VALUE=DATE:20250829", block)
        self.assertIn("PRIORITY:1", block)
        self.assertIn("CATEGORIES:Groceries <home>", block)
        self.assertIn("DESCRIPTION:Semi-skimmed\\;\\nnot oat\\, please", block)
        self.assertIn("STATUS:NEEDS-ACTION", block)

    def test_timed_ones_are_in_utc_and_done_ones_say_so(self):
        block = self.block("Send report")
        self.assertIn("DUE:20250827T160640Z", block)
        self.assertIn("STATUS:COMPLETED", block)
        self.assertIn("COMPLETED:20250827T170640Z", block)
        self.assertIn("PRIORITY:5", block)

    def test_no_due_date_no_due_line(self):
        self.assertNotIn("DUE", self.block("Call plumber"))

    def test_unique_and_untitled(self):
        uids = re.findall(r"UID:(.*)", self.text.replace("\r", ""))
        self.assertEqual(len(uids), len(set(uids)))
        self.assertIn("SUMMARY:(no title)", self.text)

    def test_the_formats_offered(self):
        self.assertEqual(list(rx.formats_for(self.data["reminders"]))[-1],
                         "ics")
        self.assertNotIn("ics", rx.formats_for(self.data["lists"]))


class RemindersGuiCase(AppGuiCase):
    def open_reminders(self, encrypted=False, **kw):
        self.open_files(fr.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Reminders")

    def show(self):
        tab = self.show_tab("Reminders")
        self.wait_for(lambda: tab.datasets, "the reminders")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]


class WindowTests(RemindersGuiCase):
    def test_the_tab_appears_only_with_reminders(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertNotIn("Reminders", self.tab_titles())
        self.open_reminders()
        self.assertIn("Reminders", self.tab_titles())

    def test_the_table(self):
        self.open_reminders()
        tab = self.show()
        self.assertEqual(tab.state_var.get(), "8 rows")
        titles = self.column("title")
        self.assertIn("Buy milk", titles)
        dues = self.column("due")
        self.assertIn("2025-08-29", dues)               # all day: a date
        self.assertEqual(sum(1 for d in dues if d), 3)
        self.assertEqual(dues[-5:], [""] * 5)           # none: last
        self.assertIn("Done", self.column("status"))
        self.assertIn("Deleted", self.column("status"))

    def test_the_details(self):
        self.open_reminders()
        tab = self.show()
        row = next(r for r, v in tab._items.items()
                   if v["title"] == "Check the wording")
        tab.tree.selection_set(row)
        self.root.update()
        text = tab.detail.get("1.0", "end")
        for expected in ("List: Work", "Account: iCloud", "Priority: Low",
                         "Subtask of: Send report"):
            self.assertIn(expected, text)

    def test_search(self):
        self.open_reminders()
        tab = self.show()
        tab.search_var.set("groceries")
        tab.refresh()
        self.assertEqual(sorted(self.column("title")),
                         ["", "Buy milk", "Call plumber", "Thrown away"])
        tab.search_var.set("oat")
        tab.refresh()
        self.assertEqual(self.column("title"), ["Buy milk"])

    def test_the_lists(self):
        self.open_reminders()
        tab = self.show()
        tab.dataset_var.set("Lists")
        tab.choose_dataset()
        self.assertEqual(sorted(self.column("list")),
                         ["Groceries <home>", "Local list", "Orphan list",
                          "Work"])

    def test_export_as_a_to_do_file(self):
        self.open_reminders()
        tab = self.show()
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(rv, "ask_export",
                               return_value=("ics", "all", out)):
            tab.export()
            self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        with open(os.path.join(out, "reminders.ics"), encoding="utf-8") as f:
            self.assertIn("BEGIN:VTODO", f.read())

    def test_original_files(self):
        self.open_reminders()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        wanted = {self.ids[("HomeDomain", p)] for p in (
            fr.STORE_A, fr.STORE_B, fr.STORE_LOCAL,
            fr.STORE_A + "-wal")}
        self.assertEqual(set(ids), wanted)

    def test_an_encrypted_backup(self):
        self.open_reminders(encrypted=True)
        self.show()
        self.assertEqual(len(self.column("title")), 8)

    def test_stores_with_nothing_in_them(self):
        self.open_files([("HomeDomain", fr.STORE_LOCAL,
                          dict((p, d) for _x, p, d in
                               fr.backup_files())[fr.STORE_LOCAL])])
        tab = self.show_tab("Reminders")
        self.wait_for(lambda: "Nothing" in tab.state_var.get(), "the note")


if __name__ == "__main__":
    unittest.main()
