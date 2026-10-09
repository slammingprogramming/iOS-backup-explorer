# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The folder tree, search and sorting behind the Files view (no GUI)."""

import shutil
import tempfile
import time
import unittest

import file_index as fi
import ios_backup_explorer as app
from tests import fixture_backup as fb


def row(file_id, domain, rel_path, size=10, mtime=None, birth=None, flags=1):
    return (file_id, domain, rel_path, flags, size, mtime, birth)


def fid(n):
    return f"{n:040x}"


SAMPLE = [
    row(fid(1), "HomeDomain", "Library/SMS/sms.db", 500, 300, 100),
    row(fid(2), "HomeDomain", "Library/SMS/Attachments/a.jpg", 2000, 200, 50),
    row(fid(3), "HomeDomain", "Library/Notes/note.txt", 20, 400, None),
    row(fid(4), "HomeDomain", "Library/readme", 5, None, None),
    row(fid(5), "MediaDomain", "Media/DCIM/IMG_2.HEIC", 3000, 100, 100),
    row(fid(6), "MediaDomain", "Media/DCIM/IMG_10.HEIC", 4000, 500, 400),
    row(fid(7), "AppDomain-com.example.app", "Documents/x.txt", 1, 1, 1),
    # folders carry their own dates
    row(fid(90), "HomeDomain", "Library", 0, 999, 888, flags=2),
    row(fid(91), "HomeDomain", "Library/Empty", 0, 5, 5, flags=2),
]


def names(nodes):
    return [n.name for n in nodes]


class ReadFileDetailsTests(unittest.TestCase):
    def test_reads_size_and_both_dates(self):
        blob = fb._file_record(1234, 1_700_000_000, 3)
        self.assertEqual(fi.read_file_details(blob),
                         (1234, 1_700_000_000, 1_700_000_000))

    def test_birth_is_separate_from_mtime(self):
        import plistlib
        blob = plistlib.dumps(
            {"$archiver": "NSKeyedArchiver",
             "$objects": ["$null", {"Size": 1, "LastModified": 20,
                                    "Birth": 10}],
             "$top": {"root": plistlib.UID(1)}}, fmt=plistlib.FMT_BINARY)
        self.assertEqual(fi.read_file_details(blob), (1, 20, 10))

    def test_missing_or_bad_data(self):
        self.assertEqual(fi.read_file_details(None), (None, None, None))
        self.assertEqual(fi.read_file_details(b"junk"), (None, None, None))

    def test_wrong_types_are_ignored(self):
        import plistlib
        blob = plistlib.dumps(
            {"$objects": ["$null", {"Size": "big", "LastModified": True,
                                    "Birth": None}],
             "$top": {"root": plistlib.UID(1)}}, fmt=plistlib.FMT_BINARY)
        self.assertEqual(fi.read_file_details(blob), (None, None, None))


class DisplayHelperTests(unittest.TestCase):
    def test_format_size(self):
        self.assertEqual(fi.format_size(0), "0 B")
        self.assertEqual(fi.format_size(1536), "1.5 KB")
        self.assertEqual(fi.format_size(5 * 1024 ** 3), "5.00 GB")

    def test_format_time(self):
        self.assertRegex(fi.format_time(1_700_000_000),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(fi.format_time(None), "")
        self.assertEqual(fi.format_time(0), "")
        self.assertEqual(fi.format_time(10 ** 20), "")   # out of range

    def test_categories(self):
        self.assertEqual(fi.category_for("AppDomain-com.x"), "Apps")
        self.assertEqual(fi.category_for("AppDomainGroup-group.x"), "Apps")
        self.assertEqual(fi.category_for("CameraRollDomain"),
                         "Camera Roll / Photos")
        self.assertEqual(fi.category_for("SysContainerDomain-x"),
                         "System Containers")
        self.assertEqual(fi.category_for("SysSharedContainerDomain-x"),
                         "System Containers")
        self.assertEqual(fi.category_for("WhateverDomain"), "Other")

    def test_kinds(self):
        index = fi.FileIndex(SAMPLE)
        sms = index.get("HomeDomain/Library/SMS/sms.db")
        self.assertEqual(fi.kind_of(sms), "Database")
        self.assertEqual(fi.kind_of(index.get("HomeDomain/Library")), "Folder")
        self.assertEqual(fi.kind_of(index.get("HomeDomain/Library/readme")),
                         "File")
        self.assertEqual(
            fi.kind_of(index.get("MediaDomain/Media/DCIM/IMG_2.HEIC")),
            "HEIC image")
        wal = fi.FileIndex([row(fid(1), "D", "sms.db-wal")]).get("D/sms.db-wal")
        self.assertEqual(fi.kind_of(wal), "Database journal")
        odd = fi.FileIndex([row(fid(1), "D", "a/b.weird")]).get("D/a/b.weird")
        self.assertEqual(fi.kind_of(odd), "WEIRD file")


class FileIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = fi.FileIndex(SAMPLE)

    def test_structure_and_totals(self):
        index = self.index
        self.assertEqual(index.file_count, 7)
        self.assertEqual(index.total_size, 500 + 2000 + 20 + 5 + 3000
                         + 4000 + 1)
        self.assertEqual(names(index.domains),
                         ["AppDomain-com.example.app", "HomeDomain",
                          "MediaDomain"])
        home = index.get("HomeDomain")
        self.assertEqual((home.count, home.total), (4, 2525))
        library = index.get("HomeDomain/Library")
        self.assertEqual((library.count, library.total), (4, 2525))
        sms = index.get("HomeDomain/Library/SMS")
        self.assertEqual((sms.count, sms.total), (2, 2500))

    def test_folder_rows_supply_dates_and_empty_folders(self):
        library = self.index.get("HomeDomain/Library")
        self.assertEqual((library.mtime, library.birth), (999, 888))
        empty = self.index.get("HomeDomain/Library/Empty")
        self.assertTrue(empty.is_dir)
        self.assertEqual((empty.count, empty.total), (0, 0))

    def test_lookups(self):
        index = self.index
        sms = index.get("HomeDomain/Library/SMS/sms.db")
        self.assertEqual(sms.file_id, fid(1))
        self.assertEqual(index.path_of(sms), "HomeDomain/Library/SMS/sms.db")
        self.assertEqual(index.domain_of(sms), "HomeDomain")
        self.assertEqual(index.domain_of(index.get("MediaDomain")),
                         "MediaDomain")
        self.assertIs(index.get(""), index.root)
        self.assertIs(index.get("/HomeDomain//Library/"),
                      index.get("HomeDomain/Library"))
        self.assertIsNone(index.get("HomeDomain/nope"))
        self.assertIsNone(index.get("HomeDomain/Library/readme/inside"))
        self.assertEqual(index.path_of(index.root), "")

    def test_walk_files_covers_everything_below(self):
        files = list(self.index.walk_files(self.index.get("HomeDomain")))
        self.assertEqual(sorted(n.file_id for n in files),
                         [fid(1), fid(2), fid(3), fid(4)])
        self.assertEqual(len(list(self.index.walk_files(self.index.root))), 7)
        single = self.index.get("HomeDomain/Library/readme")
        self.assertEqual(list(self.index.walk_files(single)), [single])

    def test_listing_modes(self):
        index = self.index
        library = index.get("HomeDomain/Library")
        self.assertEqual(sorted(names(index.listing(library))),
                         ["Empty", "Notes", "SMS", "readme"])
        self.assertEqual(len(index.listing(library, recursive=True)), 4)
        self.assertEqual(sorted(names(index.listing(index.root))),
                         ["AppDomain-com.example.app", "HomeDomain",
                          "MediaDomain"])
        self.assertEqual(len(index.listing(index.root, True)), 7)

    def test_search(self):
        index = self.index
        self.assertEqual(names(index.search(index.root, "sms.db")),
                         ["sms.db"])
        # every word must match, in any order, in the full path
        self.assertEqual(sorted(names(index.search(index.root,
                                                   "attachments JPG"))),
                         ["a.jpg"])
        self.assertEqual(index.search(index.root, "IMG_2")[0].name,
                         "IMG_2.HEIC")                  # ignores case
        self.assertEqual(index.search(index.root, "nothing like this"), [])

    def test_search_matches_the_domain_name(self):
        found = self.index.search(self.index.root, "mediadomain")
        self.assertEqual(sorted(names(found)), ["IMG_10.HEIC", "IMG_2.HEIC"])

    def test_search_is_limited_to_the_scope(self):
        index = self.index
        found = index.search(index.get("HomeDomain/Library/SMS"), "a")
        self.assertEqual(sorted(names(found)), ["a.jpg", "sms.db"])
        # and still sees the path above the scope
        found = index.search(index.get("HomeDomain/Library/SMS"),
                             "homedomain")
        self.assertEqual(len(found), 2)

    def test_search_treats_wildcards_literally(self):
        index = fi.FileIndex([row(fid(1), "D", "a_c.txt"),
                              row(fid(2), "D", "abc.txt"),
                              row(fid(3), "D", "100%.txt")])
        self.assertEqual(names(index.search(index.root, "a_c")), ["a_c.txt"])
        self.assertEqual(names(index.search(index.root, "%")), ["100%.txt"])

    def test_search_inside_a_category(self):
        scope = self.index.category_scope("Apps")
        self.assertEqual(names(self.index.search(scope, "x.txt")), ["x.txt"])
        self.assertEqual(self.index.search(scope, "sms"), [])

    def test_categories(self):
        groups = self.index.categories()
        self.assertEqual(list(groups), ["Apps", "Home / Settings",
                                        "Media (Music, Videos)"])
        scope = self.index.category_scope("Home / Settings")
        self.assertEqual(names(self.index.listing(scope)), ["HomeDomain"])
        self.assertEqual(len(self.index.listing(scope, True)), 4)

    def test_name_clashes_do_not_lose_anything(self):
        index = fi.FileIndex([
            row(fid(1), "D", "thing", 1),
            row(fid(2), "D", "thing/inner.txt", 2),     # folder over a file
            row(fid(3), "D", "twice.txt", 3),
            row(fid(4), "D", "twice.txt", 4),           # same path again
        ])
        self.assertEqual(index.file_count, 4)
        self.assertEqual(len(list(index.walk_files(index.root))), 4)
        self.assertEqual(len(index.get("D").children), 4)

    def test_rows_with_no_domain_or_of_other_kinds_are_ignored(self):
        index = fi.FileIndex([
            row(fid(1), "", "a.txt"),
            row(fid(2), None, "a.txt"),
            row(fid(3), "D", "link", flags=4),
            row(fid(4), "D", "", flags=1),               # nothing to name
            row(fid(5), "D", "ok.txt"),
        ])
        self.assertEqual(index.file_count, 1)

    def test_unknown_sizes_count_as_zero(self):
        index = fi.FileIndex([row(fid(1), "D", "a.txt", size=None)])
        self.assertEqual((index.file_count, index.total_size), (1, 0))

    def test_progress_is_reported(self):
        calls = []
        rows = [row(fid(i), "D", f"f{i}.txt") for i in range(12000)]
        fi.FileIndex(rows, progress=calls.append)
        self.assertEqual(calls, [5000, 10000])

    def test_a_large_backup_indexes_and_searches_quickly(self):
        rows = [row(fid(i), f"AppDomain-{i % 50}",
                    f"Library/Caches/{i % 40}/file{i}.dat", i)
                for i in range(100_000)]
        started = time.perf_counter()
        index = fi.FileIndex(rows)
        built = time.perf_counter() - started
        started = time.perf_counter()
        found = index.search(index.root, "file99999")
        searched = time.perf_counter() - started
        self.assertEqual(len(found), 1)
        self.assertLess(built, 10)
        self.assertLess(searched, 5)


class NaturalKeyTests(unittest.TestCase):
    def test_numbers_sort_as_numbers_and_case_is_ignored(self):
        words = ["IMG_10", "img_2", "IMG_1", "b", "A", "a10", "a9"]
        self.assertEqual(sorted(words, key=fi.natural_key),
                         ["A", "a9", "a10", "b", "IMG_1", "img_2", "IMG_10"])

    def test_mixed_digits_and_text_never_raise(self):
        sorted(["1", "a", "1a", "a1", "", "9" * 30, "é"],
               key=fi.natural_key)


class SortTests(unittest.TestCase):
    def setUp(self):
        self.index = fi.FileIndex(SAMPLE)
        self.library = self.index.get("HomeDomain/Library")
        self.nodes = list(self.library.children.values())     # 2 files, 3 dirs

    def order(self, key, descending=False, folders_first=True, nodes=None):
        return names(fi.sort_nodes(nodes or self.nodes, key, descending,
                                   folders_first))

    def test_by_name(self):
        self.assertEqual(self.order("name"),
                         ["Empty", "Notes", "SMS", "readme"])
        self.assertEqual(self.order("name", True),
                         ["SMS", "Notes", "Empty", "readme"])

    def test_names_sort_naturally(self):
        files = [n for n in self.index.get("MediaDomain/Media/DCIM")
                 .children.values()]
        self.assertEqual(self.order("name", nodes=files),
                         ["IMG_2.HEIC", "IMG_10.HEIC"])

    def test_folders_first_can_be_turned_off(self):
        self.assertEqual(self.order("name", folders_first=False),
                         ["Empty", "Notes", "readme", "SMS"])
        self.assertEqual(self.order("name", True, folders_first=False),
                         ["SMS", "readme", "Notes", "Empty"])

    def test_by_size_uses_a_folders_total(self):
        self.assertEqual(self.order("size"),
                         ["Empty", "Notes", "SMS", "readme"])   # 0, 20, 2500
        self.assertEqual(self.order("size", True),
                         ["SMS", "Notes", "Empty", "readme"])
        self.assertEqual(self.order("size", folders_first=False),
                         ["Empty", "readme", "Notes", "SMS"])

    def test_by_date_with_unknown_dates_always_last(self):
        everything = [n for n in self.index.walk_files(self.index.root)]
        modified = fi.sort_nodes(everything, "modified")
        self.assertEqual([n.mtime for n in modified],
                         [1, 100, 200, 300, 400, 500, None])
        modified = fi.sort_nodes(everything, "modified", descending=True)
        self.assertEqual([n.mtime for n in modified],
                         [500, 400, 300, 200, 100, 1, None])
        created = fi.sort_nodes(everything, "created")
        self.assertEqual([n.birth for n in created][-2:], [None, None])
        created = fi.sort_nodes(everything, "created", descending=True)
        self.assertEqual([n.birth for n in created][-2:], [None, None])

    def test_folder_dates_come_from_their_own_rows(self):
        dated = fi.sort_nodes([self.library, self.index.get("HomeDomain/"
                                                            "Library/Empty")],
                              "modified")
        self.assertEqual(names(dated), ["Empty", "Library"])   # 5 < 999

    def test_by_kind_groups_like_things(self):
        files = list(self.index.walk_files(self.index.get("HomeDomain")))
        kinds = [fi.kind_of(n) for n in fi.sort_nodes(files, "kind",
                                                      folders_first=False)]
        self.assertEqual(kinds, sorted(kinds, key=str.casefold))
        kinds = [fi.kind_of(n) for n in fi.sort_nodes(
            files, "kind", descending=True, folders_first=False)]
        self.assertEqual(kinds, sorted(kinds, key=str.casefold, reverse=True))

    def test_by_location(self):
        files = list(self.index.walk_files(self.index.get("HomeDomain")))
        ordered = fi.sort_nodes(files, "location", folders_first=False)
        where = [self.index.path_of(n.parent) for n in ordered]
        self.assertEqual(where, sorted(where, key=fi.natural_key))

    def test_ties_fall_back_to_the_name(self):
        same = fi.FileIndex([row(fid(1), "D", "b.txt", 5),
                             row(fid(2), "D", "a.txt", 5),
                             row(fid(3), "D", "c.txt", 5)])
        nodes = list(same.get("D").children.values())
        self.assertEqual(names(fi.sort_nodes(nodes, "size")),
                         ["a.txt", "b.txt", "c.txt"])
        self.assertEqual(names(fi.sort_nodes(nodes, "size", True)),
                         ["a.txt", "b.txt", "c.txt"])

    def test_an_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError):
            fi.sort_nodes(self.nodes, "colour")

    def test_sorting_does_not_change_its_input(self):
        before = list(self.nodes)
        fi.sort_nodes(self.nodes, "size", True)
        self.assertEqual(self.nodes, before)


class FromARealBackupTests(unittest.TestCase):
    def check(self, encrypted):
        tmp = tempfile.mkdtemp(prefix="ibe-index-")
        self.addCleanup(shutil.rmtree, tmp, True)
        backup_dir, ids = fb.build_backup(tmp, encrypted=encrypted)
        session = app.BackupSession()
        self.addCleanup(lambda: (session.close(),
                                 session._executor.shutdown(wait=True)))
        session.open(backup_dir, fb.PASSPHRASE if encrypted else None) \
            .result(60)
        index = fi.FileIndex(session.scan().result(60))

        self.assertEqual(index.file_count, len(fb.DEFAULT_FILES))
        movie = index.get(f"{fb.NOTES_DOMAIN}/{fb.NOTES_MOV}")
        self.assertEqual(movie.file_id, ids[(fb.NOTES_DOMAIN, fb.NOTES_MOV)])
        self.assertEqual(movie.size, len(fb.content_of(fb.NOTES_DOMAIN,
                                                       fb.NOTES_MOV)))
        self.assertEqual((movie.mtime, movie.birth),
                         (1_700_000_000, 1_700_000_000))
        self.assertTrue(index.get("HomeDomain/Library").is_dir)
        self.assertEqual(
            names(index.search(index.root, "voice_memo_01")),
            ["voice_memo_01-audio.MOV"])

    def test_encrypted(self):
        self.check(True)

    def test_unencrypted(self):
        self.check(False)


if __name__ == "__main__":
    unittest.main()
