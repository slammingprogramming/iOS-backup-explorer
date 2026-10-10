# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Privacy, Apps, Recent contacts and iCloud Drive tabs."""

import plistlib
import sqlite3
import unittest

from ios_apps import appnames, icloud_drive, installed_apps, privacy, recents
from tests import fixture_small_tabs as fx
from tests.fixture_apps import database_bytes
from tests.gui_apps import AppGuiCase


def empty_connection(testcase):
    conn = sqlite3.connect(":memory:")
    testcase.addCleanup(conn.close)
    return conn


def connect(testcase, builder):
    import os
    import shutil
    import tempfile
    folder = tempfile.mkdtemp(prefix="ibe-small-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, "x.db")
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.rows = privacy.rows(connect(self, fx.build_privacy))

    def test_every_permission(self):
        self.assertEqual(len(self.rows), 6)
        first = self.rows[0]
        self.assertEqual((first["app"], first["permission"], first["access"],
                          first["how"], first["changed"]),
                         ("com.example.app", "Photos", "Allowed",
                          "answered the prompt", fx.UNIX0))

    def test_what_the_numbers_mean(self):
        by = {r["permission"]: r for r in self.rows}
        self.assertEqual(by["Local network"]["access"], "Refused")
        self.assertEqual(by["Local network"]["how"], "set by the system")
        self.assertEqual(by["Contacts"]["access"], "Limited")
        self.assertEqual(by["Contacts"]["how"], "set in Settings")

    def test_a_service_without_a_name_is_made_readable(self):
        row = next(r for r in self.rows if r["path"])
        self.assertEqual(row["permission"], "Something new here")
        self.assertEqual((row["access"], row["how"], row["changed"]),
                         ("Not decided", "", None))
        self.assertEqual(privacy.service_label("kTCCServiceUbiquity"),
                         "iCloud")
        self.assertEqual(privacy.service_label(None), "")

    def test_unknown_values_and_no_date(self):
        row = next(r for r in self.rows if r["permission"] == "Microphone")
        self.assertEqual((row["access"], row["how"], row["changed"]),
                         ("Value 7", "", None))

    def test_the_details(self):
        (data,) = privacy.datasets(connect(self, fx.build_privacy))
        text = data.details(self.rows[0])
        for expected in ("com.example.app", "Photos: Allowed",
                         "Set: answered the prompt", "kTCCServicePhotos"):
            self.assertIn(expected, text)

    def test_no_table(self):
        self.assertEqual(privacy.datasets(empty_connection(self)), [])


class LocationTests(unittest.TestCase):
    def setUp(self):
        import os
        import shutil
        import tempfile
        self.folder = tempfile.mkdtemp(prefix="ibe-loc-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.write(fx.location_plist())

    def write(self, data):
        import os
        with open(os.path.join(self.folder, "clients.plist"), "wb") as f:
            f.write(data)

    def rows(self):
        return {r["app"]: r for r in privacy.location_rows(self.folder)}

    def test_the_apps_and_the_system_parts(self):
        rows = self.rows()
        self.assertEqual(sorted(rows), sorted([
            "com.example.app", "com.apple.Maps", "com.example.never",
            "com.example.undecided", "com.example.mask", "com.example.weird",
            "somed", "Thing.bundle"]))
        self.assertEqual(rows["somed"]["kind"], "System")
        self.assertEqual(rows["Thing.bundle"]["kind"], "System")
        self.assertEqual(rows["com.example.app"]["kind"], "App")

    def test_access(self):
        rows = self.rows()
        self.assertEqual(rows["com.example.app"]["access"],
                         "While using the app")
        self.assertEqual(rows["com.apple.Maps"]["access"], "Always")
        self.assertEqual(rows["com.example.never"]["access"], "Never")
        self.assertEqual(rows["com.example.undecided"]["access"],
                         "Not decided")
        self.assertEqual(rows["com.example.mask"]["access"], "Not set")
        self.assertEqual(rows["com.example.weird"]["access"], "Value 9")

    def test_when_the_location_was_last_given(self):
        rows = self.rows()
        self.assertEqual(rows["com.example.app"]["last"],
                         700_000_000.5 + 978_307_200)
        self.assertIsNone(rows["com.example.weird"]["last"])
        self.assertIsNone(rows["com.apple.Maps"]["last"])

    def test_a_damaged_or_missing_list(self):
        self.write(b"not a property list")
        self.assertEqual(privacy.location_rows(self.folder), [])
        self.write(plistlib.dumps([1, 2]))
        self.assertEqual(privacy.location_rows(self.folder), [])
        self.assertEqual(privacy.location_datasets(self.folder + "-none"), [])

    def test_what_a_tab_copies(self):
        from file_index import FileIndex
        rows = [(f"id{n}", d, p, 1, len(b), 0, 0)
                for n, (d, p, b) in enumerate(fx.files())]
        self.assertEqual(privacy.discover(FileIndex(rows)),
                         [privacy.DATABASE, privacy.LOCATION])
        self.assertEqual(privacy.discover(None), [])


class AppsTests(unittest.TestCase):
    def setUp(self):
        self.rows = installed_apps.rows(connect(self, fx.build_apps))
        self.by = {r["identifier"]: r for r in self.rows}

    def test_the_apps(self):
        self.assertEqual(len(self.rows), 3)             # (blank ones: not)
        safari = self.by["com.apple.mobilesafari"]
        self.assertEqual((safari["app"], safari["maker"], safari["badge"]),
                         ("Safari", "Apple", "3"))

    def test_other_apps_are_named_by_their_identifier(self):
        tool = self.by["com.example.tool"]
        self.assertEqual((tool["app"], tool["maker"], tool["badge"]),
                         ("com.example.tool", "", "!"))
        self.assertEqual(self.by["com.apple.unknownthing"]["app"],
                         "com.apple.unknownthing")

    def test_a_badge_that_is_data_is_not_shown(self):
        self.assertEqual(self.by["com.apple.unknownthing"]["badge"], "")

    def test_names(self):
        self.assertEqual(appnames.app_name("com.apple.MobileSMS"),
                         "Messages")
        self.assertEqual(appnames.app_name("x"), "x")

    def test_no_table(self):
        self.assertEqual(installed_apps.datasets(empty_connection(self)), [])


class RecentsTests(unittest.TestCase):
    def setUp(self):
        self.rows = recents.rows(connect(self, fx.build_recents))

    def test_a_person_with_two_addresses(self):
        alex = self.rows[0]
        self.assertEqual((alex["name"], alex["address"], alex["also"],
                          alex["kind"], alex["via"], alex["count"]),
                         ("Alex Example", "+15550100001", 1, "phone",
                          "Messages", 5))
        self.assertEqual(alex["last"], fx.UNIX0)        # (from thousandths)

    def test_an_address_with_no_name(self):
        row = self.rows[1]
        self.assertEqual((row["name"], row["address"], row["via"]),
                         ("", "someone@example.org", "Mail"))
        self.assertEqual(row["last"], fx.UNIX0 + 60)

    def test_what_is_missing(self):
        row = self.rows[2]
        self.assertEqual((row["address"], row["via"], row["count"],
                          row["last"]),
                         ("x@example.com", "com.example.unknown", None, None))

    def test_the_channel_can_come_from_the_source(self):
        self.assertEqual(self.rows[3]["via"], "Wallet")

    def test_the_details(self):
        (data,) = recents.datasets(connect(self, fx.build_recents))
        text = data.details(self.rows[0])
        for expected in ("Alex Example", "Address: +15550100001",
                         "Through: Messages", "1 more address(es)"):
            self.assertIn(expected, text)

    def test_no_table(self):
        self.assertEqual(recents.datasets(empty_connection(self)), [])


class ICloudTests(unittest.TestCase):
    def setUp(self):
        self.rows = icloud_drive.rows(connect(self, fx.build_icloud))
        self.by = {r["path"]: r for r in self.rows}

    def test_only_real_paths(self):
        self.assertEqual(len(self.rows), 4)

    def test_names_folders_and_types(self):
        row = self.by["Projects/Plan 2025/notes.TXT"]
        self.assertEqual((row["name"], row["folder"], row["kind"]),
                         ("notes.TXT", "Projects/Plan 2025", "txt"))
        self.assertEqual(self.by["readme"]["folder"], "")
        self.assertEqual(self.by["readme"]["kind"], "")
        self.assertEqual(self.by["Deep/er/still/file.tar.gz"]["kind"], "gz")
        self.assertEqual(self.by["Folder/.hidden.pdf.icloud"]["name"],
                         ".hidden.pdf.icloud")


class SmallTabsGuiCase(AppGuiCase):
    def column(self, tab, key):
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]

    def shown(self, title):
        tab = self.show_tab(title)
        self.wait_for(lambda: tab.datasets, f"the {title} table")
        return tab


class WindowTests(SmallTabsGuiCase):
    TITLES = ("Privacy", "Apps", "Recents", "iCloud Drive")

    def test_the_tabs_appear_only_with_their_data(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        for title in self.TITLES:
            self.assertNotIn(title, self.tab_titles())
        self.open_files(fx.files())
        for title in self.TITLES:
            self.assertIn(title, self.tab_titles())
        self.open_files(fx.files(privacy=False, location=False, apps=False))
        self.assertEqual([t for t in self.TITLES if t in self.tab_titles()],
                         ["Recents", "iCloud Drive"])
        self.open_files(fx.files(privacy=False, apps=False, recents=False,
                                 icloud=False))      # (the location alone)
        self.assertEqual([t for t in self.TITLES if t in self.tab_titles()],
                         ["Privacy"])

    def test_privacy(self):
        self.open_files(fx.files())
        tab = self.shown("Privacy")
        self.assertEqual(len(self.column(tab, "app")), 6)
        tab.search_var.set("local network")
        tab.refresh()
        self.assertEqual(self.column(tab, "access"), ["Refused"])
        tab.search_var.set("")
        tab.dataset_var.set("Location services")
        tab.choose_dataset()
        self.assertEqual(len(self.column(tab, "app")), 8)
        self.assertIn("Always", self.column(tab, "access"))

    def test_the_location_alone(self):
        self.open_files(fx.files(privacy=False, apps=False, recents=False,
                                 icloud=False))
        tab = self.shown("Privacy")
        self.assertEqual(list(tab.datasets), ["location"])

    def test_apps_recents_and_icloud(self):
        self.open_files(fx.files())
        tab = self.shown("Apps")
        self.assertEqual(sorted(self.column(tab, "app")),
                         ["Safari", "com.apple.unknownthing",
                          "com.example.tool"])
        tab = self.shown("Recents")
        self.assertEqual(self.column(tab, "name")[0], "")      # newest: mail
        self.assertEqual(len(self.column(tab, "address")), 4)
        tab = self.shown("iCloud Drive")
        self.assertEqual(self.column(tab, "name")[0], ".hidden.pdf.icloud")
        self.assertEqual(tab.state_var.get(), "4 rows")

    def test_original_files(self):
        self.open_files(fx.files())
        for title, wanted in (("Privacy", [fx.PRIVACY, fx.LOCATION]),
                              ("Apps", [fx.APPS]), ("Recents", [fx.RECENTS]),
                              ("iCloud Drive", [fx.ICLOUD])):
            tab = self.shown(title)
            extracted = []
            self.explorer.apps.extract = extracted.append
            tab.extract_originals()
            (ids,) = extracted
            self.assertEqual(set(ids), {self.ids[key] for key in wanted},
                             title)

    def test_an_encrypted_backup(self):
        self.open_files(fx.files(), encrypted=True)
        tab = self.shown("Privacy")
        self.assertEqual(len(tab.datasets["permissions"].rows), 6)


if __name__ == "__main__":
    unittest.main()
