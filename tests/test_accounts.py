# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Accounts and facts about the device, and the tab in the window."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from file_index import FileIndex
from ios_apps import accounts as ac
from ios_apps.common import APPLE_EPOCH
from tests import fixture_accounts as fa
from tests.fixture_apps import T0
from tests.gui_apps import AppGuiCase


def make_index(files):
    rows = [(f"id{n}", d, p, 1, len(data), 0, 0)
            for n, (d, p, data) in enumerate(files)]
    return FileIndex(rows)


def write(folder, name, data):
    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(data)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-acc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work")
        self.backup = os.path.join(self.tmp, "backup")
        os.makedirs(self.work)
        os.makedirs(self.backup)
        for _d, path, data in fa.backup_files():
            write(self.work, os.path.basename(path), data)
        self.conn = sqlite3.connect(os.path.join(self.work,
                                                 "Accounts3.sqlite"))
        self.addCleanup(self.conn.close)


class AccountTests(Case):
    def setUp(self):
        super().setUp()
        self.rows = ac.account_rows(self.conn)
        self.by = {(r["type"], r["description"]): r for r in self.rows}

    def test_every_account(self):
        self.assertEqual(len(self.rows), 5)
        self.assertEqual(sorted(r["type"] for r in self.rows), sorted([
            "iCloud", "CalDAV", "Game Center", "(unknown type)",
            "(unknown type)"]))

    def test_names_users_and_dates(self):
        icloud = self.by[("iCloud", "iCloud")]
        self.assertEqual((icloud["user"], icloud["owner"], icloud["parent"]),
                         ("person@example.com", "com.example.setup", ""))
        self.assertEqual(icloud["added"], T0 + APPLE_EPOCH)
        games = self.by[("Game Center", "Games")]            # trimmed
        self.assertEqual((games["user"], games["active"]), ("player1", "off"))

    def test_sub_accounts_name_their_parent(self):
        calendar = self.by[("CalDAV", "")]
        self.assertEqual(calendar["parent"], "iCloud")
        self.assertEqual(calendar["hidden"], "hidden")

    def test_services_are_read_from_blobs_and_text(self):
        self.assertEqual(self.by[("iCloud", "iCloud")]["services"],
                         "Calendars, Contacts, Mail")
        self.assertEqual(self.by[("CalDAV", "")]["services"], "Calendars")
        self.assertEqual(self.by[("Game Center", "Games")]["services"], "")

    def test_an_account_with_nothing_set(self):
        bare = next(r for r in self.rows if r["added"] is None)
        self.assertEqual((bare["user"], bare["description"], bare["hidden"]),
                         ("", "", ""))

    def test_no_accounts_table(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(ac.account_rows(conn), [])
        self.assertEqual(ac.datasets(conn, self.tmp), [])

    def test_the_details(self):
        text = ac._details(self.by[("iCloud", "iCloud")])
        for expected in ("Description: iCloud",
                         "Account name: person@example.com",
                         "Switched on for: Calendars, Contacts, Mail",
                         "Set up by: com.example.setup"):
            self.assertIn(expected, text)
        self.assertIn("Not active", ac._details(self.by[("Game Center",
                                                         "Games")]))
        self.assertIn("Part of: iCloud", ac._details(self.by[("CalDAV", "")]))


class DeviceTests(Case):
    def test_the_names_in_the_preferences(self):
        self.assertEqual(ac.preferences_info(self.work), [
            ("Name of the device", "Sam's Phone"),
            ("Host name", "Sams-Phone"),
            ("Local host name", "Sams-Phone-local")])

    def test_preferences_without_a_name(self):
        write(self.work, "preferences.plist", fa.preferences_plist(False))
        self.assertEqual(ac.preferences_info(self.work),
                         [("Local host name", "Sams-Phone-local")])

    def test_a_damaged_or_missing_plist(self):
        write(self.work, "preferences.plist", b"junk")
        self.assertEqual(ac.preferences_info(self.work), [])
        self.assertEqual(ac.preferences_info(os.path.join(self.tmp, "no")), [])

    def test_the_backup_folders_own_plists(self):
        write(self.backup, "Info.plist", fa.info_plist())
        write(self.backup, "Manifest.plist", fa.manifest_plist())
        write(self.backup, "Status.plist", fa.status_plist())
        info = dict(ac.backup_info(self.backup))
        self.assertEqual(info["Device name"], "Sam's Phone")  # Info.plist wins
        self.assertEqual(info["Model"], "iPhone 13")
        self.assertEqual(info["iOS version"], "18.2")
        self.assertEqual(info["Serial number"], "SERIAL12345")
        self.assertEqual(info["IMEI"], "123456789012345")
        self.assertEqual(info["Encrypted"], "no")
        self.assertEqual(info["Passcode was set"], "yes")
        self.assertEqual(info["Full backup"], "yes")
        self.assertNotIn("GUID", " ".join(info))
        local = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(info["Last backup"],
                         datetime.fromtimestamp(local.timestamp()
                                                ).strftime("%Y-%m-%d %H:%M"))

    def test_only_a_manifest(self):
        write(self.backup, "Manifest.plist", fa.manifest_plist())
        info = dict(ac.backup_info(self.backup))
        self.assertEqual(info["Device name"], "Different Name")
        self.assertEqual(info["Serial number"], "SERIAL12345")

    def test_an_extracted_backup_has_no_plists(self):
        self.assertEqual(ac.backup_info(self.backup), [])
        self.assertEqual(ac.backup_info(None), [])

    def test_the_device_table_does_not_repeat_itself(self):
        write(self.backup, "Info.plist", fa.info_plist())
        data = {d.key: d for d in ac.datasets(self.conn, self.work,
                                              self.backup)}
        items = [r["item"] for r in data["device"].rows]
        self.assertEqual(len(items), len(set(items)))
        self.assertIn("Name of the device", items)       # from the phone
        self.assertEqual(list(data), ["device", "accounts"])

    def test_nothing_known_about_the_device(self):
        os.remove(os.path.join(self.work, "preferences.plist"))
        data = {d.key for d in ac.datasets(self.conn, self.work)}
        self.assertEqual(data, {"accounts"})


class FilesTests(unittest.TestCase):
    def test_what_a_tab_copies(self):
        index = make_index(fa.backup_files())
        self.assertEqual(ac.discover(index), [ac.ACCOUNTS, ac.PREFERENCES])
        self.assertEqual(ac.discover(make_index(
            fa.backup_files(accounts=False))), [ac.PREFERENCES])
        self.assertEqual(ac.discover(make_index([])), [])
        self.assertEqual(ac.discover(None), [])


class AccountsGuiCase(AppGuiCase):
    def open_accounts(self, encrypted=False, **kw):
        self.open_files(fa.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Accounts")

    def show(self):
        tab = self.show_tab("Accounts")
        self.wait_for(lambda: tab.datasets, "the accounts")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]


class WindowTests(AccountsGuiCase):
    def test_the_tab_appears_only_with_the_files(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertNotIn("Accounts", self.tab_titles())
        self.open_accounts()
        self.assertIn("Accounts", self.tab_titles())

    def test_the_device_and_the_accounts(self):
        self.open_accounts()
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["device", "accounts"])
        self.assertIn("Name of the device", self.column("item"))
        self.assertIn("Sam's Phone", self.column("value"))
        tab.dataset_var.set("Accounts")
        tab.choose_dataset()
        self.assertEqual(len(self.column("type")), 5)
        self.assertEqual(self.column("type")[0], "(unknown type)")
        self.assertIn("player1", self.column("user"))

    def test_the_backup_folders_information_is_included(self):
        backup = self.open_files(fa.backup_files())
        write(backup, "Info.plist", fa.info_plist())
        # (a tab made after the file was added reads it)
        self.explorer.apps.backup_dir = backup
        self.explorer._clear_app_tabs()
        self.explorer._add_app_tabs(self.explorer.apps.index)
        tab = self.show()
        self.assertIn("Serial number", self.column("item"))
        self.assertIn("SERIAL12345", self.column("value"))
        self.assertIn("Encrypted", self.column("item"))

    def test_search_and_details(self):
        self.open_accounts()
        tab = self.show()
        tab.dataset_var.set("Accounts")
        tab.choose_dataset()
        tab.search_var.set("calendars")
        tab.refresh()
        self.assertEqual(len(self.column("type")), 2)
        row = next(iter(tab._items))
        tab.tree.selection_set(row)
        self.root.update()
        self.assertIn("Switched on for:", tab.detail.get("1.0", "end"))

    def test_original_files(self):
        self.open_accounts()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        wanted = {self.ids[(d, p)] for d, p, _ in fa.backup_files()}
        self.assertEqual(set(ids), wanted)

    def test_only_the_preferences(self):
        self.open_accounts(accounts=False)
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["device"])

    def test_an_encrypted_backup(self):
        self.open_accounts(encrypted=True)
        tab = self.show()
        self.assertIn("accounts", tab.datasets)
        self.assertIn("Encrypted", [r["item"] for r in
                                    tab.datasets["device"].rows])


if __name__ == "__main__":
    unittest.main()
