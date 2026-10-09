# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Files view as a widget: navigation, sorting, search, paging and
extraction hand-off (skipped without a display)."""

import gc
import queue
import time
import tkinter as tk
import unittest
from unittest import mock

import browser_panel as bp
import file_index as fi
from tests.test_file_index import SAMPLE, fid, row


class PanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display available")
        cls.root.withdraw()
        from tkinter import ttk
        ttk.Style().configure("Subtitle.TLabel")   # the app defines this

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.posted = queue.Queue()
        self.status, self.extracted = [], []
        self.page_size = 10_000
        self.panel = bp.FileBrowserPanel(
            self.root,
            post=lambda func, *args: self.posted.put((func, args)),
            on_extract=self.extracted.append,
            on_status=self.status.append,
            page_size=lambda: self.page_size)
        self.addCleanup(self._release)
        self.addCleanup(self.panel.destroy)
        self.addCleanup(self.panel.close)
        self.index = fi.FileIndex(SAMPLE)
        self.panel.set_index(self.index)

    def _release(self):
        # runs last: collect the panel's garbage on the Tk thread
        self.panel = None
        gc.collect()

    # -- helpers ----------------------------------------------

    def pump(self):
        while not self.posted.empty():
            func, args = self.posted.get()
            func(*args)
        self.root.update()

    def wait_for(self, condition, what, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}")

    def settle(self):
        """Wait for the listing requested so far to be on screen."""
        request = self.panel._request
        self.wait_for(lambda: self.panel._listing_request == request,
                      "listing") if hasattr(self.panel,
                                            "_listing_request") else None
        self.wait_for(lambda: self.posted.empty() and self._idle(), "idle")

    def _idle(self):
        time.sleep(0.05)
        self.pump()
        return self.posted.empty()

    def shown(self):
        tree = self.panel.file_tree
        return [tree.item(i, "text") for i in tree.get_children()]

    def cell(self, name, column):
        tree = self.panel.file_tree
        for item in tree.get_children():
            if tree.item(item, "text") == name:
                return tree.set(item, column)
        self.fail(f"{name!r} is not listed")

    def go(self, path, recursive=False):
        node = self.index.get(path) if path else self.index.root
        self.panel.navigate(node, recursive)
        self.settle()

    def item_for(self, path):
        return self.panel._node_item[id(self.index.get(path))]


class TreeTests(PanelCase):
    def test_top_level_entries(self):
        tree = self.panel.domain_tree
        top = [tree.item(i, "text") for i in tree.get_children()]
        self.assertEqual(top, ["All Files (7)", "Apps (1)",
                               "Home / Settings (1)",
                               "Media (Music, Videos) (1)"])

    def test_folders_load_when_opened(self):
        tree = self.panel.domain_tree
        home = self.item_for("HomeDomain")
        self.assertEqual(tree.get_children(home), (home + "/…",))
        tree.focus(home)
        self.panel._on_tree_open(None)
        library = self.item_for("HomeDomain/Library")
        self.assertIn(library, tree.get_children(home))
        # only folders appear in the tree, and empty ones have no arrow
        tree.focus(library)
        self.panel._on_tree_open(None)
        self.assertEqual(
            sorted(tree.item(i, "text") for i in tree.get_children(library)),
            ["Empty", "Notes", "SMS"])
        empty = self.item_for("HomeDomain/Library/Empty")
        self.assertEqual(tree.get_children(empty), ())

    def test_choosing_all_files_lists_every_file(self):
        self.panel.domain_tree.selection_set("__ALL__")
        self.wait_for(lambda: len(self.shown()) == 7, "all files")
        self.assertTrue(self.panel.recursive_var.get())

    def test_choosing_a_domain_lists_its_top_folder(self):
        self.panel.domain_tree.selection_set(self.item_for("HomeDomain"))
        self.wait_for(lambda: self.shown() == ["Library"], "domain contents")
        self.assertFalse(self.panel.recursive_var.get())

    def test_choosing_a_category_lists_its_domains_as_folders(self):
        self.panel.domain_tree.selection_set("__CAT__Apps")
        self.wait_for(lambda: self.shown() == ["AppDomain-com.example.app"],
                      "category")

    def test_nothing_is_shown_without_an_index(self):
        self.panel.set_index(None)
        self.assertEqual(self.panel.domain_tree.get_children(), ())
        self.assertEqual(self.shown(), [])
        self.assertEqual(self.panel.count_var.get(), "")


class ListingTests(PanelCase):
    def test_folder_contents_with_columns(self):
        self.go("HomeDomain/Library")
        self.assertEqual(self.shown(),
                         ["Empty", "Notes", "SMS", "readme"])   # folders first
        self.assertEqual(self.cell("SMS", "kind"), "Folder")
        self.assertEqual(self.cell("SMS", "size"), "2.4 KB")    # a total
        self.assertEqual(self.cell("Empty", "size"), "")        # nothing in it
        self.assertEqual(self.cell("readme", "kind"), "File")
        self.assertEqual(self.cell("readme", "size"), "5 B")
        self.assertEqual(self.cell("readme", "modified"), "")   # unknown
        # SMS has no manifest row of its own, so it has no date; Library does
        self.assertEqual(self.cell("SMS", "modified"), "")
        self.go("HomeDomain")
        self.assertNotEqual(self.cell("Library", "modified"), "")
        self.assertNotEqual(self.cell("Library", "created"), "")
        self.go("HomeDomain/Library")
        self.assertEqual(self.panel.count_var.get(), "4 items")
        self.assertEqual(self.panel.location_var.get(), "HomeDomain/Library")

    def test_every_item_has_an_icon(self):
        self.go("HomeDomain/Library")
        tree = self.panel.file_tree
        for item in tree.get_children():
            self.assertTrue(tree.item(item, "image"))

    def test_icons_follow_the_kind_of_file(self):
        icons = self.panel._icons
        pick = lambda path: self.panel._icon_for(self.index.get(path))  # noqa
        self.assertIs(pick("HomeDomain/Library"), icons["folder"])
        self.assertIs(pick("MediaDomain/Media/DCIM/IMG_2.HEIC"),
                      icons["picture"])
        self.assertIs(pick("HomeDomain/Library/SMS/sms.db"),
                      icons["database"])
        self.assertIs(pick("HomeDomain/Library/readme"), icons["file"])
        movie = fi.FileIndex([row(fid(1), "D", "a.mov")]).get("D/a.mov")
        self.assertIs(self.panel._icon_for(movie), icons["media"])

    def test_include_subfolders_lists_files_and_shows_the_location(self):
        self.go("HomeDomain/Library")
        self.assertNotIn("location", self.panel.file_tree["displaycolumns"])
        self.panel.recursive_var.set(True)
        self.panel._options_changed()
        self.wait_for(lambda: sorted(self.shown()) ==
                      ["a.jpg", "note.txt", "readme", "sms.db"],
                      "flat listing")
        self.assertIn("location", self.panel.file_tree["displaycolumns"])
        self.assertEqual(self.cell("a.jpg", "location"),
                         "HomeDomain/Library/SMS/Attachments")

    def test_properties_text(self):
        self.go("HomeDomain/Library/SMS")
        text = self.panel.properties_text(
            self.index.get("HomeDomain/Library/SMS/sms.db"))
        for part in ("sms.db", "Database", "HomeDomain/Library/SMS",
                     "500 B", f"File ID:   {fid(1)}"):
            self.assertIn(part, text)
        folder = self.panel.properties_text(self.index.get("HomeDomain"))
        self.assertIn("Contains:  4 files", folder)
        self.assertNotIn("File ID", folder)
        dateless = self.panel.properties_text(
            self.index.get("HomeDomain/Library/readme"))
        self.assertIn("Modified:  unknown", dateless)
        self.assertIn("Created:   unknown", dateless)

    def test_properties_dialog_and_clipboard(self):
        node = self.index.get("HomeDomain/Library/readme")
        with mock.patch.object(bp.messagebox, "showinfo") as showinfo:
            self.panel.show_properties(node)
        self.assertEqual(showinfo.call_args[0][0], "Properties")
        self.panel.copy_text("HomeDomain/Library/readme")
        self.assertEqual(self.panel.clipboard_get(),
                         "HomeDomain/Library/readme")


class SortingTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.go("HomeDomain/Library", recursive=True)    # 4 files, flat

    def order(self):
        self.settle()
        return self.shown()

    def heading(self, column):
        return self.panel.file_tree.heading(column, "text")

    def test_starts_sorted_by_name(self):
        self.assertEqual(self.order(),
                         ["a.jpg", "note.txt", "readme", "sms.db"])
        self.assertTrue(self.heading("#0").endswith("▲"))
        self.assertFalse(self.heading("size").endswith(("▲", "▼")))

    def test_each_column_sorts_and_toggles(self):
        cases = {
            "size": (["readme", "note.txt", "sms.db", "a.jpg"], "#0"),
            "modified": (["a.jpg", "sms.db", "note.txt", "readme"], "modified"),
            "created": (["a.jpg", "sms.db", "note.txt", "readme"], "created"),
            "kind": None,
        }
        self.panel.sort_by("size")
        self.assertEqual(self.order(), cases["size"][0])
        self.assertTrue(self.heading("size").endswith("▲"))
        self.assertFalse(self.heading("#0").endswith(("▲", "▼")))
        self.panel.sort_by("size")                       # again: reversed
        self.assertEqual(self.order(),
                         ["a.jpg", "sms.db", "note.txt", "readme"])
        self.assertTrue(self.heading("size").endswith("▼"))

        self.panel.sort_by("modified")
        self.assertEqual(self.order(), cases["modified"][0])  # readme: unknown
        self.panel.sort_by("modified")
        self.assertEqual(self.order(),
                         ["note.txt", "sms.db", "a.jpg", "readme"])  # last still

        self.panel.sort_by("created")
        self.assertEqual(self.order(), cases["created"][0])
        self.panel.sort_by("created")
        self.assertEqual(self.order()[-2:], ["note.txt", "readme"])

    def test_name_descending_and_a_new_column_starts_ascending(self):
        self.panel.sort_by("name")
        self.assertEqual(self.order(),
                         ["sms.db", "readme", "note.txt", "a.jpg"])
        self.panel.sort_by("size")
        self.assertFalse(self.heading("size").endswith("▼"))

    def test_clicking_a_heading_sorts(self):
        command = self.panel.file_tree.heading("size", "command")
        self.panel.tk.call(command)
        self.assertEqual(self.order(),
                         ["readme", "note.txt", "sms.db", "a.jpg"])

    def test_every_heading_is_wired_to_a_sort_key(self):
        for column in ("#0", "kind", "size", "modified", "created",
                       "location"):
            self.assertTrue(self.panel.file_tree.heading(column, "command"))

    def test_folders_first_toggle(self):
        self.go("HomeDomain/Library")
        self.assertEqual(self.shown()[:3], ["Empty", "Notes", "SMS"])
        self.panel.folders_first_var.set(False)
        self.panel._options_changed()
        self.settle()
        self.assertEqual(self.shown(), ["Empty", "Notes", "readme", "SMS"])

    def test_the_latest_request_wins(self):
        self.panel.sort_by("size")
        self.panel.sort_by("size")          # descending
        self.panel.sort_by("name")          # ascending: the last word
        self.assertEqual(self.order(),
                         ["a.jpg", "note.txt", "readme", "sms.db"])


class NavigationTests(PanelCase):
    def test_back_forward_and_up(self):
        panel = self.panel
        self.assertEqual(str(panel.back_btn.cget("state")), "disabled")
        self.assertEqual(str(panel.up_btn.cget("state")), "disabled")
        self.go("HomeDomain")
        self.go("HomeDomain/Library")
        self.go("HomeDomain/Library/SMS")
        self.assertEqual(panel.location_var.get(), "HomeDomain/Library/SMS")
        self.assertEqual(str(panel.back_btn.cget("state")), "normal")
        self.assertEqual(str(panel.forward_btn.cget("state")), "disabled")

        panel.go_back()
        self.settle()
        self.assertEqual(panel.location_var.get(), "HomeDomain/Library")
        panel.go_back()
        self.settle()
        self.assertEqual(panel.location_var.get(), "HomeDomain")
        self.assertEqual(str(panel.forward_btn.cget("state")), "normal")
        panel.go_forward()
        self.settle()
        self.assertEqual(panel.location_var.get(), "HomeDomain/Library")

        panel.go_up()
        self.settle()
        self.assertEqual(panel.location_var.get(), "HomeDomain")

    def test_going_somewhere_new_drops_the_forward_history(self):
        self.go("HomeDomain")
        self.go("HomeDomain/Library")
        self.panel.go_back()
        self.settle()
        self.go("MediaDomain")
        self.assertEqual(str(self.panel.forward_btn.cget("state")),
                         "disabled")

    def test_up_from_a_domain_goes_to_its_category_then_to_the_top(self):
        self.go("HomeDomain")
        self.panel.go_up()
        self.settle()
        self.assertEqual(self.panel.location_var.get(), "Home / Settings")
        self.assertEqual(self.shown(), ["HomeDomain"])
        self.panel.go_up()
        self.settle()
        self.assertEqual(self.panel.location_var.get(), "All Files")
        self.assertEqual(len(self.shown()), 3)           # the domains
        self.assertEqual(str(self.panel.up_btn.cget("state")), "disabled")

    def test_backspace_goes_up(self):
        self.go("HomeDomain/Library")
        # Key events are not delivered to a withdrawn window, so check that
        # the key is bound and that what it calls does the job.
        self.assertTrue(self.panel.file_tree.bind("<BackSpace>"))
        self.panel.go_up()
        self.settle()
        self.assertEqual(self.panel.location_var.get(), "HomeDomain")

    def test_opening_a_folder_selected_in_the_list(self):
        self.go("HomeDomain/Library")
        tree = self.panel.file_tree
        sms = next(i for i in tree.get_children()
                   if tree.item(i, "text") == "SMS")
        tree.selection_set(sms)
        self.panel._open_selected()
        self.settle()
        self.assertEqual(self.panel.location_var.get(),
                         "HomeDomain/Library/SMS")
        self.assertEqual(self.shown(), ["Attachments", "sms.db"])
        # the folder tree follows along
        self.assertEqual(self.panel.domain_tree.selection(),
                         (self.item_for("HomeDomain/Library/SMS"),))

    def test_double_click_opens_folders_only(self):
        self.go("HomeDomain/Library")
        tree = self.panel.file_tree
        with mock.patch.object(tree, "identify_row",
                               return_value="dir:HomeDomain/Library/Notes"):
            self.panel._on_double_click(mock.Mock(y=5))
        self.settle()
        self.assertEqual(self.panel.location_var.get(),
                         "HomeDomain/Library/Notes")
        with mock.patch.object(tree, "identify_row", return_value=fid(3)):
            self.panel._on_double_click(mock.Mock(y=5))
        self.settle()
        self.assertEqual(self.panel.location_var.get(),
                         "HomeDomain/Library/Notes")     # a file: nothing

    def test_typing_a_path(self):
        panel = self.panel
        panel.location_var.set("HomeDomain\\Library\\SMS")
        panel._go_to_typed()
        self.settle()
        self.assertEqual(panel.location_var.get(), "HomeDomain/Library/SMS")
        panel.location_var.set("Nowhere/At/All")
        panel._go_to_typed()
        self.assertIn("No such folder", self.status[-1])
        panel.location_var.set("HomeDomain/Library/readme")   # a file
        panel._go_to_typed()
        self.assertIn("No such folder", self.status[-1])
        panel.location_var.set("All Files")
        panel._go_to_typed()
        self.settle()
        self.assertEqual(panel.location_var.get(), "All Files")


class SearchTests(PanelCase):
    def search(self, text):
        self.panel.search_var.set(text)
        self.wait_for(lambda: self.panel._search_job is None
                      and self.posted.empty(), "search")
        self.settle()

    def test_search_covers_the_folder_and_everything_below(self):
        self.go("HomeDomain/Library")
        self.search("txt")
        self.assertEqual(self.shown(), ["note.txt"])
        self.assertEqual(self.panel.count_var.get(), "1 items")
        self.assertIn("matches", self.status[-1])
        self.assertIn("location", self.panel.file_tree["displaycolumns"])

    def test_search_before_choosing_anything_searches_the_whole_backup(self):
        self.search("heic")
        self.assertEqual(sorted(self.shown()), ["IMG_10.HEIC", "IMG_2.HEIC"])

    def test_search_respects_the_sort_order(self):
        self.go("")
        self.search("heic")
        self.panel.sort_by("size")
        self.panel.sort_by("size")
        self.settle()
        self.assertEqual(self.shown(), ["IMG_10.HEIC", "IMG_2.HEIC"])

    def test_clearing_the_search_restores_the_folder(self):
        self.go("HomeDomain/Library")
        self.search("txt")
        self.search("")
        self.assertEqual(self.shown(),
                         ["Empty", "Notes", "SMS", "readme"])

    def test_navigating_clears_the_search(self):
        self.go("HomeDomain/Library")
        self.search("txt")
        self.go("HomeDomain")
        self.assertEqual(self.panel.search_var.get(), "")
        self.assertEqual(self.shown(), ["Library"])

    def test_typing_is_debounced(self):
        self.go("HomeDomain/Library")
        with mock.patch.object(self.panel, "refresh") as refresh:
            for text in ("t", "tx", "txt"):
                self.panel.search_var.set(text)
            self.assertEqual(refresh.call_count, 0)
            self.wait_for(lambda: refresh.call_count == 1, "one refresh")

    def test_control_f_is_bound_to_the_search_box(self):
        self.assertEqual(self.panel._focus_search(), "break")
        for widget in (self.panel.file_tree, self.panel.domain_tree,
                       self.panel.search_entry, self.panel.location_entry):
            self.assertTrue(widget.bind("<Control-f>"))


class PagingTests(PanelCase):
    def setUp(self):
        super().setUp()
        rows = [row(fid(i), "D", f"f{i:03d}.txt", i, i)
                for i in range(1, 26)]
        self.index = fi.FileIndex(rows)
        self.panel.set_index(self.index)
        self.page_size = 10

    def test_pages(self):
        self.go("D")
        self.assertEqual(len(self.shown()), 10)
        self.assertEqual(self.shown()[0], "f001.txt")
        self.assertEqual(self.panel.page_var.get(), "Page 1 of 3")
        self.assertEqual(self.panel.count_var.get(), "25 items")
        self.assertIn("Showing 10 of 25 items (page 1 of 3)", self.status[-1])
        self.assertEqual(str(self.panel.prev_btn.cget("state")), "disabled")
        self.assertEqual(str(self.panel.next_btn.cget("state")), "normal")

        self.panel.next_btn.invoke()
        self.assertEqual(self.shown()[0], "f011.txt")
        self.assertEqual(self.panel.page_var.get(), "Page 2 of 3")
        self.panel.next_btn.invoke()
        self.assertEqual(len(self.shown()), 5)
        self.assertEqual(str(self.panel.next_btn.cget("state")), "disabled")
        self.panel.prev_btn.invoke()
        self.assertEqual(self.shown()[0], "f011.txt")

    def test_sorting_applies_to_the_whole_listing_not_just_a_page(self):
        self.go("D")
        self.panel.sort_by("size")
        self.panel.sort_by("size")           # biggest first
        self.settle()
        self.assertEqual(self.shown()[0], "f025.txt")
        self.assertEqual(self.panel.page_var.get(), "Page 1 of 3")

    def test_a_short_listing_has_no_pager(self):
        self.page_size = 100
        self.go("D")
        self.assertEqual(self.panel.page_var.get(), "")
        self.assertEqual(str(self.panel.next_btn.cget("state")), "disabled")
        self.assertIn("25 items in D", self.status[-1])

    def test_extract_all_in_view_covers_every_page(self):
        self.go("D")
        with mock.patch.object(bp.messagebox, "askyesno", return_value=True):
            self.panel.extract_all_in_view()
        self.assertEqual(len(self.extracted[0]), 25)


class ExtractionHandOffTests(PanelCase):
    def test_nothing_selected(self):
        self.go("HomeDomain/Library")
        with mock.patch.object(bp.messagebox, "showinfo") as showinfo:
            self.panel.extract_selected()
        self.assertEqual(self.extracted, [])
        self.assertIn("Select files", showinfo.call_args[0][1])

    def test_a_selected_folder_stands_for_everything_in_it(self):
        self.go("HomeDomain/Library")
        tree = self.panel.file_tree
        picks = [i for i in tree.get_children()
                 if tree.item(i, "text") in ("SMS", "readme")]
        tree.selection_set(picks)
        self.panel.extract_selected()
        self.assertEqual(sorted(self.extracted[0]),
                         sorted([fid(1), fid(2), fid(4)]))

    def test_files_are_not_repeated(self):
        self.go("HomeDomain", recursive=True)
        self.panel._select_all()
        self.panel.extract_selected()
        self.assertEqual(len(self.extracted[0]), len(set(self.extracted[0])))
        self.assertEqual(len(self.extracted[0]), 4)

    def test_a_selection_of_empty_folders_says_so(self):
        self.go("HomeDomain/Library")
        tree = self.panel.file_tree
        empty = next(i for i in tree.get_children()
                     if tree.item(i, "text") == "Empty")
        tree.selection_set(empty)
        with mock.patch.object(bp.messagebox, "showinfo") as showinfo:
            self.panel.extract_selected()
        self.assertEqual(self.extracted, [])
        self.assertIn("no files", showinfo.call_args[0][1])

    def test_extract_all_in_view_asks_only_for_big_batches(self):
        self.go("HomeDomain", recursive=True)
        with mock.patch.object(bp.messagebox, "askyesno") as ask:
            self.panel.extract_all_in_view()
        ask.assert_not_called()
        self.assertEqual(len(self.extracted[0]), 4)

        rows = [row(fid(i), "D", f"f{i}.txt") for i in range(1, 151)]
        self.panel.set_index(fi.FileIndex(rows))
        self.index = self.panel.index
        self.go("D")
        with mock.patch.object(bp.messagebox, "askyesno",
                               return_value=False) as ask:
            self.panel.extract_all_in_view()
        ask.assert_called_once()
        self.assertEqual(len(self.extracted), 1)         # declined

    def test_nothing_to_extract(self):
        with mock.patch.object(bp.messagebox, "showinfo") as showinfo:
            self.panel.extract_all_in_view()
        self.assertIn("No files", showinfo.call_args[0][1])

    def test_select_all(self):
        self.go("HomeDomain/Library")
        self.panel._select_all()
        self.assertEqual(len(self.panel.file_tree.selection()), 4)


if __name__ == "__main__":
    unittest.main()
