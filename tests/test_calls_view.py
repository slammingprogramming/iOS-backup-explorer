# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Calls tab in the real window (skipped without a display)."""

import csv
import io
import os
import unittest
from unittest import mock

from ios_apps import calls as cl
from ios_apps import calls_view as cv
from tests import fixture_calls as fc
from tests.gui_apps import AppGuiCase


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


class CallsGuiCase(AppGuiCase):
    def open_calls(self, encrypted=False, contacts=True):
        files = fc.backup_files()
        if not contacts:
            files = files[:1]
        self.open_files(files, encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Calls")

    def show(self):
        tab = self.show_tab("Calls")
        self.wait_for(lambda: tab.calls, "the calls")
        return tab

    def column(self, name):
        tree = self.tab.tree
        if name == "when":
            return [tree.item(i, "text") for i in tree.get_children()]
        return [tree.set(i, name) for i in tree.get_children()]


class TabTests(CallsGuiCase):
    def test_the_tab_appears_only_when_the_backup_has_a_call_history(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        self.open_calls()
        # (the backup has an address book too, so that tab appears as well)
        self.assertEqual(self.tab_titles(), ["Files", "Calls", "Contacts"])

    def test_it_loads_when_first_shown(self):
        self.open_calls()
        tab = self.tab
        self.assertFalse(tab._loaded)
        self.show()
        self.assertTrue(tab._loaded)
        self.assertEqual(tab.state_var.get(), "9 calls")

    def test_it_works_for_an_encrypted_backup(self):
        self.open_calls(encrypted=True)
        tab = self.show()
        self.assertEqual(len(tab.tree.get_children()), 9)
        self.assertIn("Alice Example", self.column("who"))


class TableTests(CallsGuiCase):
    def setUp(self):
        super().setUp()
        self.open_calls()
        self.show()

    def test_rows_newest_first_with_names_from_the_address_book(self):
        self.assertEqual(self.column("who"), [
            "+15550106666", "Pizza Place", "Unknown caller", "Alice Example",
            "Bob Sample", "Spam Likely", "Bob Sample", "Alice Example",
            "Alice Example"])
        self.assertEqual(self.column("direction")[:3],
                         ["Incoming", "Outgoing", "Missed"])

    def test_the_columns(self):
        tree = self.tab.tree
        row = next(r for r, c in self.tab._rows.items() if c.rowid == 1)
        self.assertEqual(tree.set(row, "number"), "+15550101234")
        self.assertEqual(tree.set(row, "kind"), "Phone")
        self.assertEqual(tree.set(row, "duration"), "2:05")
        self.assertEqual(tree.set(row, "place"), "Seattle, WA")
        self.assertRegex(tree.item(row, "text"),
                         r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        unanswered = next(r for r, c in self.tab._rows.items()
                          if c.rowid == 7)
        self.assertEqual(tree.set(unanswered, "duration"), "")

    def test_missed_calls_are_marked(self):
        marked = [r for r in self.tab.tree.get_children()
                  if "missed" in self.tab.tree.item(r, "tags")]
        self.assertEqual(sorted(self.tab._rows[r].rowid for r in marked),
                         [3, 6])

    def test_clicking_a_heading_sorts_and_clicking_again_reverses(self):
        tab = self.tab
        tab.sort_by("who")
        names = self.column("who")
        self.assertEqual(names, sorted(names, key=str.casefold))
        self.assertIn("▲", tab.tree.heading("who", "text"))
        tab.sort_by("who")
        self.assertEqual(self.column("who"), names[::-1])
        self.assertIn("▼", tab.tree.heading("who", "text"))
        self.assertNotIn("▼", tab.tree.heading("#0", "text"))

    def test_sorting_by_duration_and_date(self):
        tab = self.tab
        tab.sort_by("duration")
        durations = [c.duration for c in
                     (tab._rows[r] for r in tab.tree.get_children())]
        self.assertEqual(durations, sorted(durations))
        tab.sort_by("when")                       # new column: newest first
        whens = [tab._rows[r].when for r in tab.tree.get_children()]
        self.assertEqual(whens, sorted(whens, reverse=True))
        tab.sort_by("when")
        whens = [tab._rows[r].when for r in tab.tree.get_children()]
        self.assertEqual(whens, sorted(whens))

    def test_every_heading_can_be_sorted_on(self):
        for key in cv.HEADINGS:
            with self.subTest(key=key):
                self.tab.sort_by(key)
                self.assertEqual(len(self.tab.tree.get_children()), 9)

    def test_the_filter(self):
        tab = self.tab
        for name, expected in (("Missed", [3, 6]), ("Incoming", [2, 5, 8, 9]),
                               ("Outgoing", [1, 4, 7]),
                               ("FaceTime", [4, 5]),
                               ("Phone calls", [1, 2, 3, 6, 7, 8, 9]),
                               ("All calls", list(range(1, 10)))):
            with self.subTest(filter=name):
                tab.filter_var.set(name)
                tab.refresh()
                self.assertEqual(sorted(c.rowid for c in tab.view), expected)
                self.assertEqual(len(tab.tree.get_children()), len(expected))

    def test_the_search(self):
        tab = self.tab
        tab.search_var.set("alice")
        tab.refresh()
        self.assertEqual(len(tab.tree.get_children()), 3)
        tab.search_var.set("5550107777")
        tab.refresh()
        self.assertEqual(self.column("who"), ["Pizza Place"])
        tab.search_var.set("zzz")
        tab.refresh()
        self.assertEqual(tab.tree.get_children(), ())
        self.assertIn("0 calls", tab.summary_var.get())

    def test_a_filter_and_a_search_work_together(self):
        tab = self.tab
        tab.filter_var.set("Incoming")
        tab.search_var.set("alice")
        tab.refresh()
        self.assertEqual(sorted(c.rowid for c in tab.view), [5, 9])

    def test_typing_waits_a_moment_before_filtering(self):
        tab = self.tab
        tab.search_var.set("bob")
        self.assertIn("search", tab._timers)
        self.assertEqual(len(tab.tree.get_children()), 9)
        self.wait_for(lambda: len(tab.tree.get_children()) == 2,
                      "the filtered table")

    def test_the_summary_follows_what_is_shown(self):
        tab = self.tab
        self.assertEqual(tab.summary_var.get(),
                         "9 calls · 2 missed · 1:15:46 talk time")
        tab.filter_var.set("Missed")
        tab.refresh()
        self.assertEqual(tab.summary_var.get(),
                         "2 calls · 2 missed · 0:00 talk time")

    def test_long_histories_load_a_page_at_a_time(self):
        with mock.patch.object(cv, "PAGE", 4):
            tab = self.tab
            tab.refresh()
            self.assertEqual(len(tab.tree.get_children()), 4)
            self.assertIn("5 not shown", tab.more_btn.cget("text"))
            self.assertTrue(tab.more_btn.winfo_manager())
            tab.more_btn.invoke()
            self.assertEqual(len(tab.tree.get_children()), 8)
            tab.more_btn.invoke()
            self.assertEqual(len(tab.tree.get_children()), 9)
            self.assertFalse(tab.more_btn.winfo_manager())


class ExportTests(CallsGuiCase):
    def setUp(self):
        super().setUp()
        self.open_calls()
        self.show()
        self.out = os.path.join(self.tmp, "export")

    def run_export(self, scope, fmt):
        before = len(self.dialogs)
        with mock.patch.object(cv, "ask_export",
                               return_value=(fmt, scope, self.out)) as ask:
            self.tab.export()
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        return ask

    def test_every_format(self):
        for fmt in cx_formats():
            with self.subTest(fmt=fmt):
                self.out = os.path.join(self.tmp, f"out-{fmt}")
                self.run_export("all", fmt)
                self.assertTrue(os.path.isfile(
                    os.path.join(self.out, f"calls.{fmt}")))

    def test_the_dialog_offers_the_shown_calls_when_filtered(self):
        tab = self.tab
        ask = self.run_export("all", "csv")
        scopes = ask.call_args.args[3]
        self.assertEqual(list(scopes), ["all"])
        tab.filter_var.set("Missed")
        tab.refresh()
        ask = self.run_export("view", "csv")
        scopes = ask.call_args.args[3]
        self.assertEqual(list(scopes), ["view", "all"])
        self.assertEqual(ask.call_args.args[4], "view")
        rows = list(csv.reader(io.StringIO(
            read(os.path.join(self.out, "calls.csv"), encoding="utf-8-sig"),
            newline="")))
        self.assertEqual(len(rows), 3)                # the header and two

    def test_all_calls_even_when_a_filter_is_on(self):
        self.tab.filter_var.set("Missed")
        self.tab.refresh()
        self.run_export("all", "csv")
        rows = read(os.path.join(self.out, "calls.csv"),
                    encoding="utf-8-sig").splitlines()
        self.assertEqual(len(rows), 10)

    def test_the_exported_order_is_the_order_on_screen(self):
        self.tab.sort_by("who")
        self.tab.filter_var.set("Incoming")
        self.tab.refresh()
        self.run_export("view", "txt")
        lines = read(os.path.join(self.out, "calls.txt"),
                     encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("+15550106666", lines[0])          # digits sort first
        self.assertIn("Alice Example", lines[1])

    def test_cancelling_exports_nothing(self):
        with mock.patch.object(cv, "ask_export", return_value=None):
            self.tab.export()
        self.root.update()
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.dialogs, [])

    def test_an_export_that_fails_is_reported(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "calls.csv"), "w") as handle:
            handle.write("x")
        with mock.patch.object(cv.cx, "export",
                               side_effect=OSError("disk full")):
            before = len(self.dialogs)
            with mock.patch.object(cv, "ask_export",
                                   return_value=("csv", "all", self.out)):
                self.tab.export()
            self.wait_for(lambda: len(self.dialogs) > before, "the report")
        self.assertEqual(self.dialogs[-1][0], "showerror")
        self.assertIn("disk full", self.dialogs[-1][1][1])

    def test_original_files(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        self.tab.extract_originals()
        (ids,) = extracted
        self.assertEqual(ids, [self.ids[(
            "HomeDomain", "Library/CallHistoryDB/CallHistory.storedata")]])


def cx_formats():
    return list(cv.cx.FORMATS)


class WithoutContactsTests(CallsGuiCase):
    def test_numbers_are_shown_when_there_is_no_address_book(self):
        self.open_calls(contacts=False)
        tab = self.show()
        self.assertIn("+15550101234", self.column("who"))
        self.assertNotIn("Alice Example", self.column("who"))
        self.assertEqual(len(tab.tree.get_children()), 9)


class RobustnessTests(CallsGuiCase):
    def test_a_damaged_database_is_reported(self):
        self.open_files([("HomeDomain",
                          "Library/CallHistoryDB/CallHistory.storedata",
                          b"not a database")])
        tab = self.show_tab("Calls")
        self.wait_for(lambda: "Could not" in tab.state_var.get(),
                      "the error message")


if __name__ == "__main__":
    unittest.main()
