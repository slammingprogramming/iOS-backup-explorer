# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Safari tab (a table of records) in the real window (skipped without
a display)."""

import os
import unittest
from unittest import mock

from ios_apps import safari_view as sv
from tests import fixture_safari as fs
from tests.gui_apps import AppGuiCase


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


class SafariGuiCase(AppGuiCase):
    def open_safari(self, encrypted=False, **kw):
        self.open_files(fs.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Safari")

    def show(self):
        tab = self.show_tab("Safari")
        self.wait_for(lambda: tab.datasets, "the tables")
        return tab

    def column(self, key):
        tab = self.tab
        names = [c.key for c in tab.dataset.columns]
        index = names.index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]

    def choose(self, title):
        self.tab.dataset_var.set(title)
        self.tab.choose_dataset()


class TabTests(SafariGuiCase):
    def test_the_tab_appears_for_any_of_the_databases(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        for kw in ({"bookmarks": False, "tabs": False},
                   {"history": False, "tabs": False},
                   {"history": False, "bookmarks": False}):
            with self.subTest(kw=kw):
                self.open_safari(**kw)
                self.assertEqual(self.tab_titles(), ["Files", "Safari"])

    def test_it_loads_when_first_shown(self):
        self.open_safari()
        tab = self.tab
        self.assertFalse(tab._loaded)
        self.show()
        self.assertEqual(list(tab.datasets), [
            "history", "sites", "bookmarks", "reading", "tabs"])
        self.assertEqual(tab.dataset.title, "History")

    def test_it_works_for_an_encrypted_backup(self):
        self.open_safari(encrypted=True)
        self.show()
        self.assertEqual(len(self.column("title")), 7)

    def test_with_only_one_database_the_others_are_just_missing(self):
        self.open_safari(bookmarks=False, tabs=False)
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["history", "sites"])
        self.open_safari(history=False, tabs=False)
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["bookmarks", "reading"])

    def test_a_damaged_database_is_reported(self):
        self.open_files([("HomeDomain", "Library/Safari/History.db",
                          b"not a database")])
        tab = self.show_tab("Safari")
        self.wait_for(lambda: "Could not" in tab.state_var.get()
                      or "Nothing" in tab.state_var.get(), "the message")


class TableTests(SafariGuiCase):
    def setUp(self):
        super().setUp()
        self.open_safari()
        self.show()

    def test_history_newest_first(self):
        self.assertEqual(self.column("site")[0], "www.example.com")
        whens = self.column("when")
        self.assertEqual(whens, sorted(whens, reverse=True))
        self.assertEqual(self.tab.state_var.get(), "7 rows")

    def test_clicking_a_heading_sorts_and_reverses(self):
        tab = self.tab
        tab.sort_by("title")
        titles = self.column("title")
        self.assertEqual(titles[-2:], ["", ""])   # no title: always last
        self.assertEqual([t for t in titles if t],
                         sorted([t for t in titles if t], key=str.casefold))
        self.assertIn("▲", tab.tree.heading("title", "text"))
        tab.sort_by("title")
        self.assertIn("▼", tab.tree.heading("title", "text"))
        self.assertEqual([t for t in self.column("title") if t][0], "Other")
        self.assertEqual(self.column("title")[-2:], ["", ""])

    def test_search(self):
        tab = self.tab
        tab.search_var.set("example page")
        tab.refresh()
        self.assertEqual(len(self.column("title")), 3)
        self.assertEqual(tab.state_var.get(), "3 of 7")
        tab.search_var.set("zzz")
        tab.refresh()
        self.assertEqual(self.column("title"), [])
        tab.search_var.set("")
        tab.refresh()
        self.assertEqual(len(self.column("title")), 7)

    def test_typing_waits_a_moment(self):
        tab = self.tab
        tab.search_var.set("story")
        self.assertIn("search", tab._timers)
        self.wait_for(lambda: len(self.column("title")) == 1, "the filter")

    def test_the_other_tables(self):
        self.choose("Sites visited")
        self.assertEqual(self.column("site")[0], "www.example.com")
        self.choose("Bookmarks")
        self.assertIn("Favorites/Shopping", self.column("folder"))
        self.assertEqual(self.tab.note_var.get(),
                         "Double-click a row to open its address in your web "
                         "browser.")
        self.choose("Reading list")
        self.assertEqual(self.column("title"), ["Read later"])
        self.choose("Open tabs")
        self.assertEqual(len(self.column("url")), 3)

    def test_each_table_keeps_its_own_columns_and_sort(self):
        self.choose("Sites visited")
        self.tab.sort_by("site")
        self.choose("History")
        self.assertEqual([c for c in self.tab.tree["columns"]],
                         ["when", "title", "url", "site", "failed"])
        self.assertIn("▼", self.tab.tree.heading("when", "text"))

    def test_the_details_of_a_row(self):
        tab = self.tab
        row = next(r for r, v in tab._items.items()
                   if v["title"] == "Example page")
        tab.tree.selection_set(row)
        self.root.update()
        text = tab.detail.get("1.0", "end")
        self.assertIn("Example page", text)
        self.assertIn("https://www.example.com/page?a=1&b=2", text)
        tab.tree.selection_set(tab.tree.get_children()[:2])
        self.root.update()
        self.assertIn("2 selected", tab.detail.get("1.0", "end"))

    def test_a_double_click_opens_only_web_addresses(self):
        tab = self.tab
        opened = []
        with mock.patch.object(sv.webbrowser, "open", opened.append):
            row = next(r for r, v in tab._items.items()
                       if v["title"] == "Cart")
            tab.tree.selection_set(row)
            tab._on_double()
            self.assertEqual(opened, ["https://shop.example.net/<cart>"])
            about = next(r for r, v in tab._items.items()
                         if v["url"] == "about:blank")
            tab.tree.selection_set(about)
            tab._on_double()
            self.assertEqual(len(opened), 1)
        self.assertEqual(self.dialogs[-1][0], "showinfo")

    def test_nothing_is_opened_without_a_chosen_row(self):
        with mock.patch.object(sv.webbrowser, "open") as opened:
            self.tab.run_action("open_page")
            self.tab._on_double()
        opened.assert_not_called()
        self.assertEqual(self.dialogs[-1][0], "showinfo")


class ExportTests(SafariGuiCase):
    def setUp(self):
        super().setUp()
        self.open_safari()
        self.tab_ = self.show()
        self.out = os.path.join(self.tmp, "export")

    def run_export(self, scope, fmt):
        before = len(self.dialogs)
        import ios_apps.records_view as rv
        with mock.patch.object(rv, "ask_export",
                               return_value=(fmt, scope, self.out)) as ask:
            self.tab_.export()
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        return ask

    def test_history_in_every_format(self):
        for fmt in ("csv", "html", "txt", "json"):
            with self.subTest(fmt=fmt):
                self.run_export("all", fmt)
                self.assertTrue(os.path.isfile(
                    os.path.join(self.out, f"history.{fmt}")))

    def test_the_scopes_follow_what_is_shown_and_chosen(self):
        tab = self.tab_
        ask = self.run_export("all", "csv")
        self.assertEqual(list(ask.call_args.args[3]), ["all"])
        tab.search_var.set("story")
        tab.refresh()
        ask = self.run_export("view", "csv")
        self.assertEqual(list(ask.call_args.args[3]), ["view", "all"])
        self.assertEqual(len(read(os.path.join(self.out, "history.csv"),
                                  encoding="utf-8-sig").splitlines()), 2)
        tab.tree.selection_set(tab.tree.get_children()[0])
        ask = self.run_export("selected", "csv")
        self.assertEqual(list(ask.call_args.args[3]),
                         ["selected", "view", "all"])

    def test_bookmarks_can_be_exported_for_a_browser(self):
        self.tab_.dataset_var.set("Bookmarks")
        self.tab_.choose_dataset()
        ask = self.run_export("all", "netscape")
        self.assertIn("netscape", ask.call_args.args[2])
        text = read(os.path.join(self.out, "bookmarks-import.html"),
                    encoding="utf-8")
        self.assertTrue(text.startswith("<!DOCTYPE NETSCAPE-Bookmark-file"))

    def test_original_files(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        self.tab_.extract_originals()
        (ids,) = extracted
        wanted = {self.ids[("HomeDomain", p.split("/", 1)[1])]
                  for p in (fs.HISTORY, fs.BOOKMARKS, fs.TABS)}
        self.assertEqual(set(ids), wanted)

    def test_cancelling_exports_nothing(self):
        import ios_apps.records_view as rv
        with mock.patch.object(rv, "ask_export", return_value=None):
            self.tab_.export()
        self.root.update()
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
