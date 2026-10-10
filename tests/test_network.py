# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Network: Wi-Fi networks, Bluetooth devices and data usage, and the tab
in the window."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from file_index import FileIndex
from ios_apps import network as nw
from ios_apps.common import APPLE_EPOCH
from tests import fixture_network as fn
from tests.gui_apps import AppGuiCase


def make_index(files):
    rows = [(f"id{n}", d, p, 1, len(data), 0, 0)
            for n, (d, p, data) in enumerate(files)]
    return FileIndex(rows)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc).timestamp()


class ReaderCase(unittest.TestCase):
    def setUp(self, **kw):
        self.tmp = tempfile.mkdtemp(prefix="ibe-net-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        files = fn.backup_files(**kw)
        self.index = make_index(files)
        for _domain, path, data in files:
            with open(os.path.join(self.tmp, os.path.basename(path)),
                      "wb") as handle:
                handle.write(data)
        found = nw.discover(self.index)
        main = next((p for p in found if p.endswith((".sqlite", ".db"))),
                    found[0] if found else "x")
        self.conn = sqlite3.connect(os.path.join(
            self.tmp, os.path.basename(main)))
        self.addCleanup(self.conn.close)
        self.data = {d.key: d for d in nw.datasets(self.conn, self.index)}


class WifiTests(ReaderCase):
    def rows(self):
        return {r["network"]: r for r in self.data["wifi"].rows}

    def test_the_networks(self):
        self.assertEqual(sorted(self.rows()), sorted([
            "Home Net", "Café ☕", "NoSsidField",
            "��-net"]))

    def test_what_is_known_of_one(self):
        home = self.rows()["Home Net"]
        self.assertEqual((home["security"], home["router"], home["channel"],
                          home["access_points"], home["hidden"]),
                         ("WPA2 Personal", "aa:bb:cc:00:11:22", 36, 3, ""))
        self.assertEqual(home["joined"], utc(2025, 6, 1, 12, 30))
        self.assertEqual(home["added"], utc(2025, 5, 1, 8))
        self.assertEqual(home["seen"], utc(2025, 6, 2, 9, 15))

    def test_the_most_recent_place_is_used(self):
        self.assertEqual(self.rows()["Home Net"]["place"],
                         "12.60000, -45.50000 (within 20 m)")
        self.assertEqual(self.rows()["Café ☕"]["place"], "")

    def test_hidden_carplay_and_the_fallback_for_joining(self):
        cafe = self.rows()["Café ☕"]
        self.assertEqual((cafe["hidden"], cafe["carplay"]), ("hidden", True))
        self.assertEqual(cafe["joined"], utc(2025, 6, 1, 12, 30))  # prevJoined

    def test_the_details(self):
        text = self.data["wifi"].details(self.rows()["Home Net"])
        for expected in ("Security: WPA2 Personal", "Channel: 36",
                         "Access points known: 3",
                         "Last known place: 12.60000, -45.50000"):
            self.assertIn(expected, text)
        cafe = self.data["wifi"].details(self.rows()["Café ☕"])
        self.assertIn("A hidden network", cafe)
        self.assertIn("Also used by CarPlay", cafe)

    def test_the_older_list(self):
        ReaderCase.setUp(self, old=True)
        rows = {r["network"]: r for r in self.data["wifi"].rows}
        self.assertEqual(len(rows), 5)
        old = rows["Old Net"]
        self.assertEqual((old["security"], old["hidden"], old["router"]),
                         ("WPA2", "hidden", "11:22"))
        self.assertEqual(old["joined"], utc(2025, 6, 1, 12, 30))

    def test_a_damaged_list_is_just_missing(self):
        with open(os.path.join(self.tmp, os.path.basename(fn.WIFI_KNOWN)),
                  "wb") as handle:
            handle.write(b"not a property list")
        self.assertEqual(nw.wifi_rows(self.tmp), [])
        self.assertIsNone(nw.read_plist(os.path.join(self.tmp, "nothing")))


class BluetoothTests(ReaderCase):
    def test_every_kind_of_device(self):
        rows = {(r["name"], r["kind"]): r
                for r in self.data["bluetooth"].rows}
        self.assertEqual(len(rows), 7)
        self.assertEqual(
            rows[("Sam's Headphones", "Paired (classic)")]["seen"],
            1_728_501_402)
        self.assertIsNone(rows[("Speaker", "Paired (classic)")]["seen"])
        self.assertIn(("(no name)", "Paired (classic)"), rows)
        self.assertEqual(rows[("Smart Watch", "Paired (low energy)")]
                         ["address"], "11:11:11:11:11:11")
        self.assertEqual(rows[("Beacon 1", "Seen nearby (low energy)")]
                         ["address"], "33:33")

    def test_an_unnamed_device_with_only_a_resolved_address(self):
        row = next(r for r in self.data["bluetooth"].rows
                   if r["address"] == "44:44")
        self.assertEqual((row["name"], row["kind"]),
                         ("(no name)", "Seen nearby (low energy)"))

    def test_no_bluetooth_files(self):
        ReaderCase.setUp(self, bluetooth=False)
        self.assertNotIn("bluetooth", self.data)


class UsageTests(ReaderCase):
    def rows(self):
        return {r["app"]: r for r in self.data["usage"].rows}

    def test_what_each_app_used(self):
        video = self.rows()["com.example.video"]
        self.assertEqual((video["wifi_in"], video["wifi_out"],
                          video["cell_in"], video["cell_out"],
                          video["total"]), (3000, 300, 5000, 50, 8350))
        self.assertEqual(video["process"], "Video")

    def test_a_process_without_a_bundle_is_named_by_the_process(self):
        self.assertEqual(self.rows()["mediaserverd"]["total"], 20)

    def test_apps_with_no_usage_and_unknown_ones(self):
        self.assertEqual(self.rows()["com.example.quiet"]["total"], 0)
        self.assertEqual(self.rows()["(unknown)"]["total"], 0)
        self.assertEqual(len(self.rows()), 4)        # not the stray usage

    def test_the_dates(self):
        video = self.rows()["com.example.video"]
        self.assertEqual(video["last"], fn.T0 + 1000 + APPLE_EPOCH)
        self.assertIsNone(self.rows()["com.example.quiet"]["last"])

    def test_the_note_adds_it_all_up(self):
        note = self.data["usage"].note
        self.assertEqual(
            note, "All together: 3.2 KB over Wi-Fi and 4.9 KB over the "
            "mobile network, as counted by the phone since it last cleared "
            "its statistics.")

    def test_order_is_most_data_first(self):
        data = self.data["usage"]
        order = [r["app"] for r in data.sorted_rows(data.rows)]
        self.assertEqual(order[:2], ["com.example.video", "mediaserverd"])

    def test_no_usage_database(self):
        ReaderCase.setUp(self, usage=False)
        self.assertNotIn("usage", self.data)
        self.assertIn("wifi", self.data)


class FilesTests(unittest.TestCase):
    def test_what_a_tab_copies(self):
        index = make_index(fn.backup_files(old=True))
        found = nw.discover(index)
        self.assertEqual(found[0], nw.DATA_USAGE)       # a database first
        self.assertEqual(len(found), 6)
        self.assertEqual(nw.discover(make_index([])), [])
        self.assertEqual(nw.discover(None), [])

    def test_only_wifi(self):
        index = make_index(fn.backup_files(bluetooth=False, usage=False))
        self.assertEqual(nw.discover(index), [nw.WIFI_KNOWN])


class NetworkGuiCase(AppGuiCase):
    def open_network(self, encrypted=False, **kw):
        self.open_files(fn.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Network")

    def show(self):
        tab = self.show_tab("Network")
        self.wait_for(lambda: tab.datasets, "the network tables")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]

    def choose(self, title):
        self.tab.dataset_var.set(title)
        self.tab.choose_dataset()


class WindowTests(NetworkGuiCase):
    def test_the_tab_appears_only_with_network_files(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertNotIn("Network", self.tab_titles())
        self.open_network()
        self.assertIn("Network", self.tab_titles())

    def test_it_works_with_only_wifi(self):
        self.open_network(bluetooth=False, usage=False)
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["wifi"])
        self.assertEqual(len(self.column("network")), 4)

    def test_the_tables(self):
        self.open_network()
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["wifi", "bluetooth", "usage"])
        self.assertEqual(self.column("network")[0], "Café ☕")
        self.choose("Bluetooth devices")
        self.assertEqual(len(self.column("name")), 7)
        self.choose("Data used by apps")
        self.assertEqual(self.column("app")[0], "com.example.video")
        self.assertEqual(self.column("wifi_in")[0], "2.9 KB")
        self.assertIn("over Wi-Fi", tab.note_var.get())

    def test_search(self):
        self.open_network()
        tab = self.show()
        tab.search_var.set("wpa2")
        tab.refresh()
        self.assertEqual(self.column("network"), ["Home Net"])

    def test_the_details_of_a_network(self):
        self.open_network()
        tab = self.show()
        row = next(r for r, v in tab._items.items()
                   if v["network"] == "Home Net")
        tab.tree.selection_set(row)
        self.root.update()
        self.assertIn("Channel: 36", tab.detail.get("1.0", "end"))

    def test_original_files(self):
        self.open_network()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        wanted = {self.ids[(d, p)] for d, p, _ in fn.backup_files()}
        self.assertEqual(set(ids), wanted)

    def test_an_encrypted_backup(self):
        self.open_network(encrypted=True)
        self.show()
        self.assertEqual(len(self.column("network")), 4)


if __name__ == "__main__":
    unittest.main()
