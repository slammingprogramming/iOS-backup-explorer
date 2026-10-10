# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Maps, Podcasts and Books: reading generated databases, exporting, and
the tabs in the window."""

import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from file_index import FileIndex
from ios_apps import books as bk
from ios_apps import maps as mp
from ios_apps import podcasts as pc
from ios_apps import records_export as rx
from ios_apps import records_view as rv
from ios_apps.common import APPLE_EPOCH
from tests import fixture_maps_podcasts_books as fx
from tests.fixture_apps import T0
from tests.gui_apps import AppGuiCase

DAY = fx.DAY


def make_index(files):
    rows = [(f"id{n}", d, p, 1, len(data), 0, 0)
            for n, (d, p, data) in enumerate(files)]
    return FileIndex(rows)


class WorkCase(unittest.TestCase):
    def work(self, files):
        folder = tempfile.mkdtemp(prefix="ibe-media-")
        self.addCleanup(shutil.rmtree, folder, True)
        for _d, path, data in files:
            with open(os.path.join(folder, os.path.basename(path)),
                      "wb") as handle:
                handle.write(data)
        return folder

    def connect(self, folder, name):
        conn = sqlite3.connect(os.path.join(folder, name))
        self.addCleanup(conn.close)
        return conn


# ── Maps ─────────────────────────────────────────────────────

class MapsTests(WorkCase):
    def setUp(self):
        folder = self.work(fx.maps_files())
        self.conn = self.connect(folder, "MapsSync_0.0.1")
        self.data = {d.key: d for d in mp.datasets(self.conn)}

    def test_the_tables(self):
        self.assertEqual(list(self.data), [
            "favorites", "places", "collections", "history"])

    def test_favorites(self):
        rows = self.data["favorites"].rows
        self.assertEqual(len(rows), 5)
        home = rows[0]
        self.assertEqual((home["name"], home["address"], home["place"],
                          home["hidden"]),
                         ("Home <sweet>", "1 Main St",
                          "12.50000, -45.25000", ""))
        self.assertEqual(home["added"], T0 + APPLE_EPOCH)
        self.assertEqual(rows[1]["hidden"], "hidden")

    def test_what_is_not_a_place_has_no_coordinates(self):
        rows = self.data["favorites"].rows
        self.assertEqual([r["lat"] for r in rows[2:]], [None] * 3)
        self.assertEqual(rows[2]["place"], "")        # no coordinates
        self.assertEqual(rows[3]["place"], "")        # 0, 0
        self.assertEqual(rows[4]["place"], "")        # off the map

    def test_guides_and_their_places(self):
        guides = {r["collection"]: r["places"]
                  for r in self.data["collections"].rows}
        self.assertEqual(guides, {"Trip": 2, "(no title)": 1, "Empty": 0})
        places = {(r["collection"], r["name"]): r
                  for r in self.data["places"].rows}
        self.assertEqual(len(places), 3)               # (the gone one: not)
        self.assertEqual(places[("Trip", "Museum")]["place"],
                         "40.00000, -74.00000")
        self.assertEqual(places[("(no title)", "Somewhere")]["place"], "")

    def test_history_newest_first(self):
        data = self.data["history"]
        rows = data.sorted_rows(data.rows)
        self.assertEqual([r["search"] for r in rows],
                         ["coffee near me", "", "pizza"])
        self.assertEqual(rows[2]["name"], "Pizza Place")
        self.assertEqual(rows[2]["place"], "50.00000, 8.00000")

    def test_the_details(self):
        text = self.data["favorites"].details(self.data["favorites"].rows[0])
        for expected in ("Home <sweet>", "Address: 1 Main St",
                         "Place: 12.50000, -45.25000"):
            self.assertIn(expected, text)

    def test_the_place_file(self):
        out = tempfile.mkdtemp(prefix="ibe-gpx-")
        self.addCleanup(shutil.rmtree, out, True)
        (path,) = rx.export(self.data["favorites"],
                            self.data["favorites"].rows, "gpx", out)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text.count("<wpt "), 2)
        self.assertIn('<wpt lat="12.5000000" lon="-45.2500000">'
                      "<name>Home &lt;sweet&gt;</name></wpt>", text)
        self.assertNotIn("Null island", text)
        self.assertTrue(text.rstrip().endswith("</gpx>"))

    def test_history_without_a_name_is_named_by_its_search(self):
        (path,) = mp.write_gpx(os.path.join(tempfile.mkdtemp(), "h"),
                               [{"lat": 1.0, "lon": 2.0, "search": "pizza",
                                 "name": "", "place": "1, 2"}])
        with open(path, encoding="utf-8") as handle:
            self.assertIn("<name>pizza</name>", handle.read())

    def test_an_empty_database(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(mp.datasets(conn), [])

    def test_what_a_tab_copies(self):
        self.assertEqual(mp.discover(make_index(fx.maps_files())),
                         [mp.DATABASE])
        self.assertEqual(mp.discover(make_index([])), [])
        self.assertEqual(mp.discover(None), [])


# ── Podcasts ─────────────────────────────────────────────────

class PodcastTests(WorkCase):
    def setUp(self):
        folder = self.work(fx.podcasts_files())
        self.conn = self.connect(folder, "MTLibrary.sqlite")
        self.data = {d.key: d for d in pc.datasets(self.conn)}

    def test_shows(self):
        rows = {r["title"]: r for r in self.data["shows"].rows}
        show = rows["The Show <1>"]
        self.assertEqual((show["author"], show["episodes"], show["played"],
                          show["following"]), ("Host A", 2, 1, "yes"))
        self.assertEqual(show["last"], T0 + 100 + APPLE_EPOCH)
        other = rows["Other Show"]
        self.assertEqual((other["episodes"], other["played"],
                          other["following"], other["last"]),
                         (1, 0, "", None))

    def test_episodes(self):
        rows = {r["title"]: r for r in self.data["episodes"].rows}
        one = rows["Episode one"]
        self.assertEqual((one["show"], one["length"], one["plays"],
                          one["position"], one["downloaded"], one["address"]),
                         ("The Show <1>", 1800.0, 2, 600.0, "yes",
                          "https://example.com/1.mp3"))
        self.assertEqual(one["published"], T0 - 10 * DAY + APPLE_EPOCH)

    def test_the_first_known_column_is_used(self):
        two = {r["title"]: r for r in self.data["episodes"].rows}[
            "Episode two"]
        self.assertEqual(two["published"], T0 - 5 * DAY + APPLE_EPOCH)
        self.assertEqual(two["position"], 30.0)         # (the bookmark)
        self.assertEqual(two["downloaded"], "yes")      # (has an asset)

    def test_empty_and_orphan_episodes(self):
        rows = {r["title"]: r for r in self.data["episodes"].rows}
        self.assertIsNone(rows["Lonely"]["length"])      # 0 = unknown
        self.assertEqual(rows["Lonely"]["downloaded"], "")
        self.assertEqual(rows["Orphan"]["show"], "")

    def test_newest_first(self):
        data = self.data["episodes"]
        order = [r["title"] for r in data.sorted_rows(data.rows)]
        self.assertEqual(order[:2], ["Lonely", "Episode two"])

    def test_the_details(self):
        row = next(r for r in self.data["episodes"].rows
                   if r["title"] == "Episode one")
        text = self.data["episodes"].details(row)
        for expected in ("Episode one", "The Show <1>", "Stopped at: 10:00",
                         "Audio: https://example.com/1.mp3"):
            self.assertIn(expected, text)

    def test_a_database_with_other_columns(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE ZMTPODCAST (Z_PK INTEGER, ZTITLE TEXT)")
        conn.execute("INSERT INTO ZMTPODCAST VALUES (1, 'Only a title')")
        data = {d.key: d for d in pc.datasets(conn)}
        self.assertEqual(data["shows"].rows[0]["title"], "Only a title")
        self.assertEqual(data["shows"].rows[0]["episodes"], 0)
        self.assertNotIn("episodes", data)

    def test_where_the_library_is(self):
        older = fx.podcasts_files("Library/Documents/MTLibrary.sqlite",
                                  "AppDomain-com.apple.podcasts")
        self.assertEqual(pc.discover(make_index(older)),
                         ["AppDomain-com.apple.podcasts/Library/Documents/"
                          "MTLibrary.sqlite"])
        self.assertEqual(pc.discover(make_index([])), [])
        self.assertEqual(pc.discover(None), [])


# ── Books ────────────────────────────────────────────────────

class BookTests(WorkCase):
    def setUp(self, **kw):
        files = fx.books_files(**kw)
        self.index = make_index(files)
        folder = self.work(files)
        paths = bk.discover(self.index)
        self.conn = self.connect(folder, os.path.basename(paths[0]))
        self.data = {d.key: d for d in bk.datasets(self.conn, folder, paths)}

    def test_what_a_tab_copies(self):
        self.assertEqual(
            [p.rsplit("/", 1)[1] for p in bk.discover(self.index)],
            ["BKLibrary-1-091020131601.sqlite",
             "AEAnnotation_v10312011_1727_local.sqlite",
             "BKJaliscoServerSource-v09182016.sqlite", "BCCloudCollections"])
        self.assertEqual(bk.discover(make_index([])), [])
        self.assertEqual(bk.discover(None), [])

    def test_the_library_and_the_purchases_it_lacks(self):
        rows = {r["title"]: r for r in self.data["books"].rows}
        self.assertEqual(sorted(rows), ["A Novel", "A Sample", "Heard Book",
                                        "Only Bought"])      # not twice

    def test_a_book(self):
        novel = {r["title"]: r for r in self.data["books"].rows}["A Novel"]
        self.assertEqual((novel["author"], novel["genre"], novel["progress"],
                          novel["kind"]), ("Writer One", "Fiction", 43,
                                           "Book"))
        self.assertEqual(novel["opened"], T0 + APPLE_EPOCH)
        self.assertEqual(novel["bought"], T0 - DAY + APPLE_EPOCH)

    def test_audiobooks_hidden_and_samples(self):
        rows = {r["title"]: r for r in self.data["books"].rows}
        self.assertEqual((rows["Heard Book"]["kind"],
                          rows["Heard Book"]["hidden"],
                          rows["Heard Book"]["progress"]),
                         ("Audiobook", "hidden", 100))
        self.assertEqual(rows["A Sample"]["sample"], "sample")
        self.assertIsNone(rows["A Sample"]["progress"])   # 7.5: not a share
        only = rows["Only Bought"]
        self.assertEqual((only["kind"], only["hidden"], only["opened"]),
                         ("Audiobook", "hidden", None))

    def test_highlights_and_notes(self):
        rows = sorted(self.data["notes"].rows, key=lambda r: r["text"])
        self.assertEqual([(r["book"], r["text"], r["note"]) for r in rows],
                         [("A Novel", "", "only a note"),
                          ("A Novel", "A line worth keeping", "my note"),
                          ("Z9", "From a book not in the library", "")])
        by = {r["note"]: r for r in rows}
        self.assertEqual(by["my note"]["when"], T0 + 10 + APPLE_EPOCH)
        self.assertEqual(by["only a note"]["when"], T0 + 20 + APPLE_EPOCH)

    def test_collections(self):
        rows = {r["name"]: r for r in self.data["collections"].rows}
        self.assertEqual(sorted(rows), ["(no name)", "Want to Read"])
        self.assertEqual(rows["(no name)"]["hidden"], "hidden")

    def test_the_details(self):
        novel = next(r for r in self.data["books"].rows
                     if r["title"] == "A Novel")
        text = self.data["books"].details(novel)
        for expected in ("Author: Writer One", "Read: 43%"):
            self.assertIn(expected, text)
        note = self.data["notes"].rows[0]
        self.assertIn(note["book"], self.data["notes"].details(note))

    def test_only_the_store_list(self):
        BookTests.setUp(self, library=False, annotations=False,
                        collections=False)
        self.assertEqual(sorted(r["title"] for r in self.data["books"].rows),
                         ["A Novel", "Only Bought"])
        self.assertNotIn("notes", self.data)

    def test_no_books_at_all(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(bk.datasets(conn, "", []), [])


# ── The tabs in the window ───────────────────────────────────

class TabCase(AppGuiCase):
    def column(self, tab, key):
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]

    def shown(self, title):
        tab = self.show_tab(title)
        self.wait_for(lambda: tab.datasets or "Nothing" in tab.state_var.get(),
                      f"the {title} tables")
        return tab


class WindowTests(TabCase):
    def test_the_tabs_appear_only_with_their_data(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        for title in ("Maps", "Podcasts", "Books"):
            self.assertNotIn(title, self.tab_titles())
        self.open_files(fx.maps_files() + fx.podcasts_files()
                        + fx.books_files())
        for title in ("Maps", "Podcasts", "Books"):
            self.assertIn(title, self.tab_titles())

    def test_maps(self):
        self.open_files(fx.maps_files())
        tab = self.shown("Maps")
        self.assertEqual(list(tab.datasets), [
            "favorites", "places", "collections", "history"])
        self.assertIn("Home <sweet>", self.column(tab, "name"))
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(rv, "ask_export",
                               return_value=("gpx", "all", out)):
            tab.export()
            self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        with open(os.path.join(out, "favorites.gpx"), encoding="utf-8") as f:
            self.assertEqual(len(re.findall("<wpt ", f.read())), 2)

    def test_podcasts_and_their_original_files(self):
        self.open_files(fx.podcasts_files())
        tab = self.shown("Podcasts")
        self.assertEqual(list(tab.datasets), ["shows", "episodes"])
        self.assertEqual(len(self.column(tab, "title")), 2)
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        self.assertEqual(set(ids), {self.ids[(fx.PODCASTS_DOMAIN,
                                              fx.PODCASTS_DB)]})

    def test_books(self):
        self.open_files(fx.books_files())
        tab = self.shown("Books")
        self.assertEqual(list(tab.datasets), ["books", "notes",
                                              "collections"])
        self.assertEqual(len(self.column(tab, "title")), 4)
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        self.assertEqual(set(ids), {self.ids[(d, p)]
                                    for d, p, _ in fx.books_files()})

    def test_an_encrypted_backup(self):
        self.open_files(fx.maps_files(), encrypted=True)
        tab = self.shown("Maps")
        self.assertEqual(len(tab.datasets["favorites"].rows), 5)

    def test_a_backup_that_holds_the_files_but_no_data(self):
        def empty(conn):
            conn.execute("CREATE TABLE Z_METADATA (Z_VERSION INTEGER)")
            conn.commit()

        from tests.fixture_apps import database_bytes
        self.open_files([(fx.MAPS_DOMAIN, fx.MAPS_DB,
                          database_bytes(empty))])
        tab = self.shown("Maps")
        self.assertEqual(tab.datasets, {})
        self.assertIn("Nothing was found", tab.state_var.get())


if __name__ == "__main__":
    unittest.main()
