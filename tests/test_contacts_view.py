# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Contacts tab in the real window (skipped without a display)."""

import os
import unittest
from unittest import mock

from ios_apps import contacts_view as cv
from tests import fixture_contacts as fcn
from tests.gui_apps import AppGuiCase

DB = ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb")


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


class ContactsGuiCase(AppGuiCase):
    def open_contacts(self, encrypted=False):
        self.open_files(fcn.backup_files(), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Contacts")

    def show(self):
        tab = self.show_tab("Contacts")
        self.wait_for(lambda: tab.contacts, "the contacts")
        return tab

    def names(self):
        tree = self.tab.tree
        return [tree.item(i, "text") for i in tree.get_children()]

    def choose(self, name):
        tab = self.tab
        row = next(r for r, c in tab._rows.items()
                   if c.display_name == name)
        tab.tree.selection_set(row)
        self.wait_for(lambda: tab.current is tab._rows[row], f"{name!r}")
        return tab._rows[row]

    def card(self):
        return self.tab.card.get("1.0", "end")


class TabTests(ContactsGuiCase):
    def test_the_tab_appears_only_when_the_backup_has_an_address_book(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        self.open_contacts()
        self.assertEqual(self.tab_titles(), ["Files", "Contacts"])

    def test_it_loads_when_first_shown(self):
        self.open_contacts()
        tab = self.tab
        self.assertFalse(tab._loaded)
        self.show()
        self.assertEqual(tab.state_var.get(), "8 contacts")

    def test_it_works_for_an_encrypted_backup(self):
        self.open_contacts(encrypted=True)
        self.show()
        self.assertEqual(len(self.names()), 8)


class ListTests(ContactsGuiCase):
    def setUp(self):
        super().setUp()
        self.open_contacts()
        self.show()

    def test_ordered_by_last_name(self):
        self.assertEqual(self.names(), [
            "Alice Example", "Mum", "Orphan", "Pizza Place", "Bob Sample",
            "Sam Smith, Jr.", "Zed Q Zebra", "555-010-6666"])

    def test_the_second_column_shows_the_company_or_a_number(self):
        tree = self.tab.tree
        by_name = {tree.item(i, "text"): tree.set(i, "detail")
                   for i in tree.get_children()}
        self.assertEqual(by_name["Alice Example"], "Example Corp")
        self.assertEqual(by_name["Bob Sample"], "+1 555 010 5678")
        self.assertEqual(by_name["Pizza Place"], "555-010-7777")
        self.assertEqual(by_name["Orphan"], "")

    def test_ordering_by_first_name(self):
        self.tab.sort_var.set("First name")
        self.tab.refresh()
        self.assertEqual(self.names(), [
            "Alice Example", "Bob Sample", "Mum", "Orphan", "Pizza Place",
            "Sam Smith, Jr.", "Zed Q Zebra", "555-010-6666"])

    def test_search(self):
        tab = self.tab
        tab.search_var.set("alice")
        tab.refresh()
        self.assertEqual(self.names(), ["Alice Example", "Zed Q Zebra"])
        self.assertEqual(tab.state_var.get(), "2 of 8 contacts")
        tab.search_var.set("")
        tab.refresh()
        self.assertEqual(len(self.names()), 8)
        self.assertEqual(tab.state_var.get(), "8 contacts")

    def test_search_by_number_and_place(self):
        tab = self.tab
        for text, expected in (("5550101234", ["Alice Example"]),
                               ("naples", ["Pizza Place"]),
                               ("nobody-like-this", [])):
            with self.subTest(text=text):
                tab.search_var.set(text)
                tab.refresh()
                self.assertEqual(self.names(), expected)

    def test_typing_waits_a_moment_before_searching(self):
        tab = self.tab
        tab.search_var.set("mum")
        self.assertIn("search", tab._timers)
        self.assertEqual(len(self.names()), 8)
        self.wait_for(lambda: self.names() == ["Mum"], "the filtered list")

    def test_the_chosen_contact_stays_chosen_when_the_list_changes(self):
        self.choose("Bob Sample")
        self.tab.search_var.set("sample")
        self.tab.refresh()
        self.assertEqual(self.tab.tree.selection(),
                         (f"p{self.tab.current.pk}",))


class CardTests(ContactsGuiCase):
    def setUp(self):
        super().setUp()
        self.open_contacts()
        self.show()

    def test_a_full_card(self):
        self.choose("Alice Example")
        card = self.card()
        for expected in ("Alice Example", "Example Corp", "Engineer",
                         "Mobile\n(555) 010-1234", "Work\n+1 555 010 0000",
                         "alice@example.com", "Home\n1 Main St\nSpringfield "
                         "IL 62701\nUnited States", "HomePage\nhttps://"
                         "example.com/alice", "birthday\n1990-05-17",
                         "note\nMet at the conference.\nLikes tea."):
            with self.subTest(expected=expected):
                self.assertIn(expected, card)
        self.assertRegex(card, r"created \d{4}-\d\d-\d\d")

    def test_the_name_is_big_and_the_labels_are_quiet(self):
        self.choose("Alice Example")
        body = self.tab.card
        name = body.search("Alice Example", "1.0")
        label = body.search("Mobile", "1.0")
        sizes = lambda index: int(self.fontsize(index))
        self.assertGreater(sizes(name), sizes(label))
        self.assertEqual(body.tag_cget("label", "foreground"), cv._MUTED)

    def fontsize(self, index):
        import tkinter.font as tkfont
        body = self.tab.card
        for tag in body.tag_names(index):
            font = body.tag_cget(tag, "font")
            if font:
                return tkfont.Font(font=font).actual("size")
        return 0

    def test_name_parts_nickname_and_other_kinds_of_entries(self):
        self.choose("Zed Q Zebra")
        card = self.card()
        self.assertIn("Dr. Zed Q Zebra Jr.", card)
        self.assertIn("Zookeeper", card)
        self.assertIn("Spouse\nAlice Example", card)
        self.assertIn("Anniversary\n2015-08-09", card)
        self.assertIn("Skype\nzed.zebra", card)
        self.choose("Bob Sample")
        self.assertIn("“Bobby”", self.card())

    def test_a_company_and_a_contact_with_only_a_number(self):
        self.choose("Pizza Place")
        self.assertIn("Main\n555-010-7777", self.card())
        self.assertIn("Work\n9 Oven Rd\nNaples", self.card())
        self.choose("555-010-6666")
        self.assertIn("phone\n555-010-6666", self.card())

    def test_choosing_another_contact_replaces_the_card(self):
        self.choose("Alice Example")
        self.choose("Mum")
        self.assertNotIn("Alice", self.card())
        self.assertIn("Mother's mobile", self.card())


class ExportTests(ContactsGuiCase):
    def setUp(self):
        super().setUp()
        self.open_contacts()
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
        for fmt in cv.cx.FORMATS:
            with self.subTest(fmt=fmt):
                self.out = os.path.join(self.tmp, f"out-{fmt}")
                self.run_export("all", fmt)
                self.assertTrue(os.path.isfile(
                    os.path.join(self.out, f"contacts.{fmt}")))

    def test_a_vcard_file_with_everybody(self):
        self.run_export("all", "vcf")
        raw = read(os.path.join(self.out, "contacts.vcf"), "rb")
        self.assertEqual(raw.count(b"BEGIN:VCARD"), 8)
        self.assertIn(b"FN:Alice Example", raw)

    def test_the_scopes_follow_what_is_chosen_and_shown(self):
        ask = self.run_export("all", "vcf")
        self.assertEqual(list(ask.call_args.args[3]), ["all"])
        self.tab.search_var.set("alice")
        self.tab.refresh()
        ask = self.run_export("view", "vcf")
        self.assertEqual(list(ask.call_args.args[3]), ["view", "all"])
        self.assertEqual(read(os.path.join(self.out, "contacts.vcf"),
                              "rb").count(b"BEGIN:VCARD"), 2)
        self.choose("Alice Example")
        ask = self.run_export("one", "vcf")
        self.assertEqual(list(ask.call_args.args[3]), ["one", "view", "all"])
        self.assertEqual(ask.call_args.args[4], "one")
        self.assertEqual(read(os.path.join(self.out, "contacts.vcf"),
                              "rb").count(b"BEGIN:VCARD"), 1)

    def test_cancelling_exports_nothing(self):
        with mock.patch.object(cv, "ask_export", return_value=None):
            self.tab.export()
        self.root.update()
        self.assertFalse(os.path.exists(self.out))

    def test_original_files(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        self.tab.extract_originals()
        (ids,) = extracted
        self.assertEqual(ids, [self.ids[DB]])


class RobustnessTests(ContactsGuiCase):
    def test_a_damaged_address_book_is_reported(self):
        self.open_files([DB + (b"not a database",)])
        tab = self.show_tab("Contacts")
        self.wait_for(lambda: "Could not" in tab.state_var.get(),
                      "the error message")

    def test_an_address_book_with_nobody_in_it(self):
        def empty(conn):
            conn.executescript(fcn.SCHEMA)
            conn.commit()

        from tests.fixture_apps import database_bytes
        self.open_files([DB + (database_bytes(empty),)])
        tab = self.show_tab("Contacts")
        self.wait_for(lambda: tab.state_var.get() == "0 contacts", "the count")
        self.assertEqual(tab.tree.get_children(), ())
        tab.export()
        self.assertEqual(self.dialogs[-1][0], "showinfo")


if __name__ == "__main__":
    unittest.main()
