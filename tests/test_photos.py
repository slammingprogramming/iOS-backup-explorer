# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reading the camera roll and the voice recordings."""

import os
import shutil
import sqlite3
import tempfile
import unittest

from file_index import FileIndex
from ios_apps import photos as ph
from ios_apps import voice_memos as vm
from tests import fixture_media as fm
from tests.fixture_apps import T0, database_bytes

LIB = f"{fm.CAMERA}/{fm.DCIM}"


def index_of(files):
    rows = [(f"{n:040x}", entry[0], entry[1], 1, len(entry[2] or b""),
             entry[3] if len(entry) > 3 else 0,
             entry[3] if len(entry) > 3 else 0)
            for n, entry in enumerate(files, 1)]
    return FileIndex(rows)


def connect(testcase, builder):
    folder = tempfile.mkdtemp(prefix="ibe-photos-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, "db.sqlite")
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


class PhotosCase(unittest.TestCase):
    def setUp(self):
        self.files = fm.camera_files()
        self.index = index_of(self.files)
        self.items = ph.scan(self.index)
        self.by = {(i.directory.split("/")[-1], i.name): i for i in self.items}

    def enriched(self):
        ph.enrich(self.items, connect(self, fm.build_library))
        return self.by


class ScanTests(PhotosCase):
    def test_pictures_and_videos_in_the_camera_roll_only(self):
        self.assertEqual([(i.directory, i.name) for i in self.items], [
            ("DCIM/100APPLE", "IMG_0001.PNG"),
            ("DCIM/100APPLE", "IMG_0002.JPG"),
            ("DCIM/100APPLE", "IMG_0003.HEIC"),
            ("DCIM/100APPLE", "IMG_0004.MOV"),
            ("DCIM/100APPLE", "IMG_E0002.JPG"),
            ("DCIM/101APPLE", "IMG_0001.PNG")])

    def test_what_the_files_alone_tell(self):
        item = self.by[("100APPLE", "IMG_0001.PNG")]
        self.assertEqual(item.path, f"{LIB}/100APPLE/IMG_0001.PNG")
        self.assertEqual(item.kind, "photo")
        self.assertEqual(item.taken, fm.FILE_DATE)
        self.assertEqual(item.taken_from, "file")
        self.assertEqual(item.size, len(fm.picture_bytes("PNG")))
        self.assertTrue(item.file_id)
        self.assertEqual(self.by[("100APPLE", "IMG_0004.MOV")].kind, "video")
        self.assertEqual(item.type_label, "Photo (PNG)")
        self.assertEqual(self.by[("100APPLE", "IMG_0004.MOV")].type_label,
                         "Video (MOV)")

    def test_no_camera_roll_means_no_items(self):
        self.assertEqual(ph.scan(index_of([("HomeDomain", "a.txt", b"x")])),
                         [])

    def test_a_missing_date_is_none(self):
        index = index_of([(fm.CAMERA, f"{fm.DCIM}/100APPLE/a.jpg", b"x", 0)])
        (item,) = ph.scan(index)
        self.assertIsNone(item.taken)

    def test_kinds_by_extension(self):
        for name, kind in (("a.JPG", "photo"), ("a.heic", "photo"),
                           ("a.MOV", "video"), ("a.m4v", "video"),
                           ("a.AAE", None), ("a.plist", None), ("a", None)):
            with self.subTest(name=name):
                self.assertEqual(ph.kind_of(name), kind)


class LibraryTests(PhotosCase):
    def test_dates_taken_come_from_the_library(self):
        by = self.enriched()
        item = by[("100APPLE", "IMG_0001.PNG")]
        self.assertEqual(item.taken, T0 + fm.APPLE_EPOCH)
        self.assertEqual(item.taken_from, "library")
        orphan = by[("100APPLE", "IMG_E0002.JPG")]
        self.assertEqual((orphan.taken, orphan.taken_from),
                         (fm.FILE_DATE + 4, "file"))

    def test_flags_sizes_and_places(self):
        by = self.enriched()
        first = by[("100APPLE", "IMG_0001.PNG")]
        self.assertTrue(first.favorite)
        self.assertFalse(first.hidden or first.trashed)
        self.assertEqual(first.location, "47.60620, -122.33210")
        self.assertTrue(by[("100APPLE", "IMG_0002.JPG")].hidden)
        heic = by[("100APPLE", "IMG_0003.HEIC")]
        self.assertEqual(heic.dimensions, "4032 × 3024")
        self.assertEqual(heic.location, "-34.92850, 138.60070")
        video = by[("100APPLE", "IMG_0004.MOV")]
        self.assertEqual((video.kind, video.duration), ("video", 12.5))
        self.assertEqual(video.location, "")        # iOS stores -180 for none
        self.assertEqual(by[("100APPLE", "IMG_E0002.JPG")].dimensions, "")

    def test_two_pictures_with_one_name_are_told_apart_by_folder(self):
        by = self.enriched()
        self.assertTrue(by[("101APPLE", "IMG_0001.PNG")].trashed)
        self.assertFalse(by[("100APPLE", "IMG_0001.PNG")].trashed)

    def test_albums(self):
        by = self.enriched()
        self.assertEqual(by[("100APPLE", "IMG_0001.PNG")].albums,
                         ["Holiday", "Favourites of 2026"])
        self.assertEqual(by[("100APPLE", "IMG_0003.HEIC")].albums,
                         ["Holiday"])
        self.assertEqual(by[("100APPLE", "IMG_0004.MOV")].albums,
                         ["Favourites of 2026"])
        self.assertEqual(by[("100APPLE", "IMG_E0002.JPG")].albums, [])

    def test_a_library_without_the_asset_table_changes_nothing(self):
        def build(conn):
            conn.execute("CREATE TABLE other (x)")
            conn.commit()

        before = [(i.taken, i.favorite) for i in self.items]
        ph.enrich(self.items, connect(self, build))
        self.assertEqual([(i.taken, i.favorite) for i in self.items], before)

    def test_a_file_that_is_not_a_database_raises(self):
        folder = tempfile.mkdtemp(prefix="ibe-photos-")
        self.addCleanup(shutil.rmtree, folder, True)
        junk = os.path.join(folder, "junk.sqlite")
        with open(junk, "wb") as handle:
            handle.write(b"not a database")
        conn = sqlite3.connect(junk)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.DatabaseError):
            ph.enrich(self.items, conn)

    def test_a_library_with_only_some_columns(self):
        def build(conn):
            conn.executescript(
                "CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, "
                "ZDIRECTORY VARCHAR, ZFILENAME VARCHAR);"
                "INSERT INTO ZASSET VALUES (1, 'DCIM/100APPLE', "
                "'IMG_0001.PNG');")
            conn.commit()

        ph.enrich(self.items, connect(self, build))
        item = self.by[("100APPLE", "IMG_0001.PNG")]
        self.assertEqual((item.taken_from, item.favorite), ("file", False))

    def test_places_that_make_no_sense_are_dropped(self):
        for lat, lon, shown in ((0, 0, False), (91, 10, False),
                                (10, 181, False), (10, -180, False),
                                (10, 180, True), (-90, 0.5, True)):
            with self.subTest(lat=lat, lon=lon):
                def build(conn, lat=lat, lon=lon):
                    conn.executescript(
                        "CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, "
                        "ZDIRECTORY VARCHAR, ZFILENAME VARCHAR, "
                        "ZLATITUDE FLOAT, ZLONGITUDE FLOAT);")
                    conn.execute("INSERT INTO ZASSET VALUES (1, "
                                 "'DCIM/100APPLE', 'IMG_0001.PNG', ?, ?)",
                                 (lat, lon))
                    conn.commit()

                items = ph.scan(index_of(self.files))
                ph.enrich(items, connect(self, build))
                self.assertEqual(bool(items[0].location), shown)


class AlbumTests(PhotosCase):
    def names(self, album):
        self.enriched()
        return sorted(f"{i.directory.rsplit('/', 1)[-1]}/{i.name}"
                      for i in self.items if ph.in_album(i, album))

    def test_smart_albums(self):
        self.assertEqual(self.names(ph.ALL), [
            "100APPLE/IMG_0001.PNG", "100APPLE/IMG_0003.HEIC",
            "100APPLE/IMG_0004.MOV", "100APPLE/IMG_E0002.JPG"])
        self.assertEqual(self.names(ph.PHOTOS), [
            "100APPLE/IMG_0001.PNG", "100APPLE/IMG_0003.HEIC",
            "100APPLE/IMG_E0002.JPG"])
        self.assertEqual(self.names(ph.VIDEOS), ["100APPLE/IMG_0004.MOV"])
        self.assertEqual(self.names(ph.FAVORITES),
                         ["100APPLE/IMG_0001.PNG"])
        self.assertEqual(self.names(ph.HIDDEN), ["100APPLE/IMG_0002.JPG"])
        self.assertEqual(self.names(ph.DELETED), ["101APPLE/IMG_0001.PNG"])

    def test_user_albums_and_folders(self):
        self.assertEqual(self.names(("album", "Holiday")), [
            "100APPLE/IMG_0001.PNG", "100APPLE/IMG_0003.HEIC"])
        self.assertEqual(self.names(("folder", "DCIM/100APPLE")), [
            "100APPLE/IMG_0001.PNG", "100APPLE/IMG_0002.JPG",
            "100APPLE/IMG_0003.HEIC", "100APPLE/IMG_0004.MOV",
            "100APPLE/IMG_E0002.JPG"])
        self.assertEqual(self.names(("folder", "DCIM/101APPLE")), [])
        self.assertEqual(self.names(("album", "Nope")), [])

    def test_the_list_of_albums_and_folders(self):
        self.enriched()
        albums, folders = ph.albums_of(self.items)
        self.assertEqual(albums, [(("album", "Favourites of 2026"), 2),
                                  (("album", "Holiday"), 2)])
        self.assertEqual(folders, [(("folder", "DCIM/100APPLE"), 5)])


class ListTests(PhotosCase):
    def test_sorting(self):
        self.enriched()
        names = lambda how: [i.name for i in ph.sort_items(self.items, how)]
        newest = ph.sort_items(self.items, "Date taken, newest first")
        stamps = [i.taken for i in newest]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        oldest = [i.taken for i in ph.sort_items(self.items,
                                                  "Date taken, oldest first")]
        self.assertEqual(oldest, sorted(oldest))
        self.assertEqual(names("Name")[:3],
                         ["IMG_0001.PNG", "IMG_0001.PNG", "IMG_0002.JPG"])
        sizes = [i.size for i in ph.sort_items(self.items,
                                                "Size, largest first")]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        kinds = [i.kind for i in ph.sort_items(self.items, "Type")]
        self.assertEqual(kinds, sorted(kinds))
        for how in ph.SORTS:
            self.assertEqual(len(names(how)), 6)

    def test_search(self):
        self.enriched()
        found = lambda text: sorted(i.name for i in
                                    ph.search_items(self.items, text))
        self.assertEqual(found("heic"), ["IMG_0003.HEIC"])
        self.assertEqual(found("holiday"), ["IMG_0001.PNG", "IMG_0003.HEIC"])
        self.assertEqual(found("101apple img_0001"), ["IMG_0001.PNG"])
        self.assertEqual(found("-34.9285"), ["IMG_0003.HEIC"])
        self.assertEqual(found("nothing like it"), [])
        self.assertEqual(len(found("")), 6)

    def test_unique_names(self):
        names = ph.unique_names(self.items)
        self.assertEqual(len(set(n.casefold() for n in names.values())), 6)
        first = names[f"{LIB}/100APPLE/IMG_0001.PNG"]
        second = names[f"{LIB}/101APPLE/IMG_0001.PNG"]
        self.assertEqual(first, "IMG_0001.PNG")
        self.assertEqual(second, "DCIM_101APPLE_IMG_0001.PNG")

    def test_unique_names_even_when_the_second_try_collides(self):
        a = ph.MediaItem("D/a/x.jpg", "x.jpg", "a")
        b = ph.MediaItem("D/b/x.jpg", "x.jpg", "b")
        c = ph.MediaItem("D/b2/X.JPG", "X.JPG", "b")
        d = ph.MediaItem("D/b3/b_x.jpg", "b_x.jpg", "b3")
        names = ph.unique_names([a, d, b, c])
        self.assertEqual(len({v.casefold() for v in names.values()}), 4)
        self.assertEqual(names[a.path], "x.jpg")


class VoiceMemoTests(unittest.TestCase):
    def setUp(self):
        self.files = fm.memo_files()
        self.index = index_of(self.files)
        self.memos = vm.scan(self.index)

    def test_recordings_newest_first_and_nothing_else(self):
        self.assertEqual([m.name for m in self.memos], [
            "20260901 130000-DDD.m4a", "20260901 120000-CCC.m4a",
            "20260901 110000-BBB.m4a", "20260901 100000-AAA.m4a"])
        self.assertTrue(vm.has_recordings(self.index))
        self.assertFalse(vm.has_recordings(index_of([("HomeDomain", "a", b"")])))

    def test_the_database_is_found(self):
        self.assertEqual(vm.find_database(self.index), vm.DATABASES[0])
        self.assertIsNone(vm.find_database(
            index_of(fm.memo_files(with_database=False))))

    def test_a_database_alone_counts(self):
        index = index_of([e for e in self.files if e[1].endswith(".db")])
        self.assertTrue(vm.has_recordings(index))

    def test_titles_dates_and_lengths_come_from_the_database(self):
        vm.enrich(self.memos, connect(self, fm.build_memos_db))
        by = {m.name: m for m in self.memos}
        interview = by["20260901 100000-AAA.m4a"]
        self.assertEqual((interview.title, interview.duration),
                         ("Interview with Sam", 125.4))
        self.assertEqual((interview.when, interview.when_from),
                         (T0 + fm.APPLE_EPOCH, "library"))
        untitled = by["20260901 110000-BBB.m4a"]
        self.assertEqual(untitled.display_title, "20260901 110000-BBB")
        unknown = by["20260901 130000-DDD.m4a"]
        self.assertEqual((unknown.duration, unknown.when_from),
                         (None, "file"))
        self.assertEqual(unknown.when, fm.FILE_DATE + 180)

    def test_the_older_layout(self):
        def build(conn):
            conn.executescript(
                "CREATE TABLE ZRECORDING (Z_PK INTEGER PRIMARY KEY, "
                "ZCUSTOMLABEL VARCHAR, ZDATE TIMESTAMP, ZDURATION FLOAT, "
                "ZPATH VARCHAR);"
                "INSERT INTO ZRECORDING VALUES (1, 'Old one', 1000, 7.5, "
                "'/var/mobile/Media/Recordings/20150101 010101.m4a');")
            conn.commit()

        files = [("MediaDomain", "Media/Recordings/20150101 010101.m4a",
                  fm.AUDIO, fm.FILE_DATE),
                 ("MediaDomain", "Media/Recordings/Recordings.db", b"x",
                  fm.FILE_DATE)]
        index = index_of(files)
        self.assertEqual(vm.find_database(index), vm.DATABASES[1])
        memos = vm.scan(index)
        vm.enrich(memos, connect(self, build))
        self.assertEqual((memos[0].title, memos[0].duration),
                         ("Old one", 7.5))

    def test_a_database_with_no_recordings_table_changes_nothing(self):
        def build(conn):
            conn.execute("CREATE TABLE other (x)")
            conn.commit()

        vm.enrich(self.memos, connect(self, build))
        self.assertTrue(all(m.title == "" for m in self.memos))

    def test_a_file_that_is_not_a_database_raises(self):
        folder = tempfile.mkdtemp(prefix="ibe-photos-")
        self.addCleanup(shutil.rmtree, folder, True)
        junk = os.path.join(folder, "junk.db")
        with open(junk, "wb") as handle:
            handle.write(b"not a database")
        conn = sqlite3.connect(junk)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.DatabaseError):
            vm.enrich(self.memos, conn)

    def test_sorting_and_search(self):
        vm.enrich(self.memos, connect(self, fm.build_memos_db))
        titles = lambda how: [m.display_title
                              for m in vm.sort_memos(self.memos, how)]
        self.assertEqual(titles("Title")[0], "20260901 110000-BBB")
        self.assertEqual(titles("Length, longest first")[0],
                         "Interview with Sam")
        sizes = [m.size for m in vm.sort_memos(self.memos,
                                                "Size, largest first")]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(len(titles("Date, oldest first")), 4)
        found = lambda text: [m.display_title
                              for m in vm.search_memos(self.memos, text)]
        self.assertEqual(found("interview sam"), ["Interview with Sam"])
        self.assertEqual(found("ccc"), ["Song idea"])
        self.assertEqual(len(found("")), 4)


if __name__ == "__main__":
    unittest.main()
