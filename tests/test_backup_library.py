# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The backups on the computer and the care of them: finding, describing,
copying, moving, deleting and checking. Everything runs on invented backups
in a temporary folder."""

import datetime
import os
import plistlib
import shutil
import sqlite3
import tempfile
import unittest
import unittest.mock

import app_settings
import backup_library as lib
from tests import fixture_backup as fb

UDID = "00008030-001A2B3C4D5E6F78"


def write_plist(path, data):
    with open(path, "wb") as handle:
        plistlib.dump(data, handle)


def make_backup(parent, name=UDID, *, device="Taylor's iPhone",
                encrypted=False, finished=True, when=None, files=None):
    """A small unencrypted backup with its three property lists."""
    folder = os.path.join(parent, name)
    os.makedirs(folder)
    when = when or datetime.datetime(2026, 10, 9, 18, 30)
    write_plist(os.path.join(folder, "Info.plist"), {
        "Device Name": device, "Product Type": "iPhone15,4",
        "Product Version": "18.5", "Build Version": "22F76",
        "Serial Number": "DEMO", "Unique Identifier": name,
        "Last Backup Date": when})
    write_plist(os.path.join(folder, "Manifest.plist"), {
        "IsEncrypted": encrypted, "Date": when, "Version": "10.0"})
    write_plist(os.path.join(folder, "Status.plist"), {
        "IsFullBackup": True, "SnapshotState":
        "finished" if finished else "new", "Date": when})
    files = files if files is not None else {"HomeDomain": {
        "Library/a.txt": b"hello", "Library/b.txt": b"world!!"}}
    conn = sqlite3.connect(os.path.join(folder, "Manifest.db"))
    conn.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT,"
                 " relativePath TEXT, flags INTEGER, file BLOB)")
    for domain, entries in files.items():
        for relative, content in entries.items():
            file_id = fb.file_id_for(domain, relative)
            os.makedirs(os.path.join(folder, file_id[:2]), exist_ok=True)
            with open(os.path.join(folder, file_id[:2], file_id), "wb") as f:
                f.write(content)
            conn.execute("INSERT INTO Files VALUES (?,?,?,?,?)",
                         (file_id, domain, relative, 1, None))
    conn.commit()
    conn.close()
    return folder


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-library-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def folder(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path, exist_ok=True)
        return path


class WhereBackupsAreTests(unittest.TestCase):
    def test_windows_has_both_apple_places_and_its_own(self):
        found = lib.default_locations("Windows", {
            "APPDATA": r"C:\Users\x\AppData\Roaming",
            "USERPROFILE": r"C:\Users\x",
            "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}, r"C:\Users\x")
        paths = [p for p, _who in found]
        self.assertTrue(paths[0].endswith(os.path.join(
            "Apple Computer", "MobileSync", "Backup")))
        self.assertTrue(paths[1].endswith(os.path.join(
            "Apple", "MobileSync", "Backup")))
        self.assertIn("iOS Backup Explorer", paths[2])

    def test_macos_has_finders_and_its_own(self):
        found = lib.default_locations("Darwin", {}, "/Users/x")
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0][0].replace("\\", "/").endswith(
            "Library/Application Support/MobileSync/Backup"))

    def test_linux_has_a_folder_of_its_own_following_xdg(self):
        found = lib.default_locations("Linux", {"XDG_DATA_HOME": "/d"}, "/h")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0].replace("\\", "/"),
                         "/d/ios-backup-explorer/Backups")
        found = lib.default_locations("Linux", {}, "/h")
        self.assertEqual(found[0][0].replace("\\", "/"),
                         "/h/.local/share/ios-backup-explorer/Backups")


class DescribingTests(TempCase):
    def test_a_backup_says_what_it_is(self):
        path = make_backup(self.tmp)
        entry = lib.inspect_backup(path)
        self.assertEqual(entry.device_name, "Taylor's iPhone")
        self.assertEqual(entry.udid, UDID)
        self.assertEqual(entry.version, "18.5")
        self.assertEqual(entry.model, "iPhone15,4")
        self.assertIs(entry.encrypted, False)
        self.assertIs(entry.complete, True)
        self.assertIs(entry.full, True)
        self.assertEqual(entry.made, datetime.datetime(2026, 10, 9, 18, 30))

    def test_encrypted_and_interrupted_backups_are_marked(self):
        path = make_backup(self.tmp, encrypted=True, finished=False)
        entry = lib.inspect_backup(path)
        self.assertIs(entry.encrypted, True)
        self.assertIs(entry.complete, False)

    def test_a_folder_that_is_not_a_backup_is_not_one(self):
        self.assertIsNone(lib.inspect_backup(self.folder("photos")))
        open(os.path.join(self.tmp, "file"), "w").close()
        self.assertIsNone(lib.inspect_backup(os.path.join(self.tmp, "file")))

    def test_damaged_property_lists_do_not_stop_the_listing(self):
        path = make_backup(self.tmp)
        with open(os.path.join(path, "Info.plist"), "wb") as f:
            f.write(b"not a plist")
        entry = lib.inspect_backup(path)
        self.assertEqual(entry.device_name, "")
        self.assertEqual(entry.title, UDID)       # (the folder's name)
        self.assertIs(entry.encrypted, False)

    def test_a_backup_with_no_status_is_not_called_unfinished(self):
        path = make_backup(self.tmp)
        os.remove(os.path.join(path, "Status.plist"))
        self.assertIsNone(lib.inspect_backup(path).complete)


class FindingTests(TempCase):
    def test_backups_in_every_location_newest_first(self):
        a, b = self.folder("a"), self.folder("b")
        make_backup(a, "OLD", when=datetime.datetime(2025, 1, 1))
        make_backup(b, "NEW", when=datetime.datetime(2026, 5, 5))
        make_backup(b, "MID", when=datetime.datetime(2026, 1, 1))
        self.folder(os.path.join("b", "not-a-backup"))
        found = lib.find_backups([(a, "one"), (b, "two"),
                                  os.path.join(self.tmp, "missing")])
        self.assertEqual([e.folder_name for e in found],
                         ["NEW", "MID", "OLD"])
        self.assertEqual(found[0].location, "two")

    def test_a_location_that_is_itself_a_backup_counts(self):
        path = make_backup(self.tmp, "SOLO")
        self.assertEqual([e.folder_name for e in lib.find_backups([path])],
                         ["SOLO"])

    def test_the_same_backup_is_listed_once(self):
        make_backup(self.tmp, "X")
        found = lib.find_backups([self.tmp, self.tmp])
        self.assertEqual(len(found), 1)

    def test_the_size_is_every_file(self):
        path = make_backup(self.tmp)
        size = lib.folder_size(path)
        self.assertGreater(size, len(b"hello") + len(b"world!!"))
        self.assertEqual(lib.folder_size(self.folder("empty")), 0)

    def test_sizing_can_be_cancelled(self):
        make_backup(self.tmp)
        with self.assertRaises(lib.Cancelled):
            lib.folder_size(self.tmp, cancel=lambda: True)


class CopyAndMoveTests(TempCase):
    def setUp(self):
        super().setUp()
        self.src_parent = self.folder("src")
        self.dest = self.folder("dest")
        self.path = make_backup(self.src_parent)

    def test_a_copy_is_complete_and_the_original_stays(self):
        seen = []
        target = lib.copy_backup(self.path, self.dest,
                                 progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(target, os.path.join(self.dest, UDID))
        self.assertEqual(lib.folder_size(target), lib.folder_size(self.path))
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertTrue(lib.inspect_backup(target))
        self.assertFalse([n for n in os.listdir(self.dest)
                          if n.endswith(".copying")])

    def test_it_never_overwrites_a_backup_that_is_there(self):
        lib.copy_backup(self.path, self.dest)
        with self.assertRaises(FileExistsError):
            lib.copy_backup(self.path, self.dest)

    def test_a_backup_cannot_be_copied_into_itself(self):
        with self.assertRaises(lib.NotABackup):
            lib.copy_backup(self.path, os.path.join(self.path, "ab"))

    def test_a_cancelled_copy_leaves_nothing_behind(self):
        with self.assertRaises(lib.Cancelled):
            lib.copy_backup(self.path, self.dest, cancel=lambda: True)
        self.assertEqual(os.listdir(self.dest), [])

    def test_a_copy_that_came_out_short_is_never_put_in_place(self):
        # (a failing drive can write less than it was given and say nothing)
        real = shutil.copyfile

        def short(src, dst, *a, **k):
            real(src, dst, *a, **k)
            with open(dst, "r+b") as handle:
                handle.truncate(max(0, os.path.getsize(dst) - 1))

        with unittest.mock.patch.object(lib.shutil, "copyfile", short):
            with self.assertRaises(OSError):
                lib.copy_backup(self.path, self.dest)
        self.assertEqual(os.listdir(self.dest), [])
        self.assertTrue(lib.inspect_backup(self.path))

    def test_a_folder_that_is_not_a_backup_is_refused(self):
        with self.assertRaises(lib.NotABackup):
            lib.copy_backup(self.folder("photos"), self.dest)

    def test_a_move_copies_then_removes_the_original(self):
        target = lib.move_backup(self.path, self.dest, [self.src_parent])
        self.assertTrue(lib.inspect_backup(target))
        self.assertFalse(os.path.exists(self.path))

    def test_a_failed_copy_never_removes_the_original(self):
        lib.copy_backup(self.path, self.dest)       # now the name is taken
        with self.assertRaises(FileExistsError):
            lib.move_backup(self.path, self.dest, [self.src_parent])
        self.assertTrue(os.path.isdir(self.path))


class DeleteTests(TempCase):
    def test_a_backup_in_a_known_location_is_deleted(self):
        parent = self.folder("loc")
        path = make_backup(parent)
        lib.delete_backup(path, [(parent, "x")])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isdir(parent))

    def test_read_only_files_do_not_stop_it(self):
        parent = self.folder("loc")
        path = make_backup(parent)
        for root, _dirs, files in os.walk(path):
            for name in files:
                os.chmod(os.path.join(root, name), 0o444)
        lib.delete_backup(path, [parent])
        self.assertFalse(os.path.exists(path))

    def test_anything_that_is_not_a_backup_is_refused(self):
        parent = self.folder("loc")
        other = self.folder(os.path.join("loc", "documents"))
        open(os.path.join(other, "thesis.txt"), "w").close()
        with self.assertRaises(lib.NotABackup):
            lib.delete_backup(other, [parent])
        self.assertTrue(os.path.exists(os.path.join(other, "thesis.txt")))

    def test_a_backup_outside_the_known_places_is_refused(self):
        elsewhere = self.folder("elsewhere")
        path = make_backup(elsewhere)
        with self.assertRaises(lib.NotABackup):
            lib.delete_backup(path, [self.folder("loc")])
        self.assertTrue(os.path.isdir(path))

    def test_the_location_itself_is_never_deleted(self):
        parent = make_backup(self.tmp, "ROOT")      # a backup used as a place
        with self.assertRaises(lib.NotABackup):
            lib.delete_backup(parent, [parent])
        self.assertTrue(os.path.isdir(parent))

    def test_a_link_is_refused(self):
        parent = self.folder("loc")
        real = make_backup(self.folder("real"))
        link = os.path.join(parent, "link")
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("links are not allowed here")
        with self.assertRaises(lib.NotABackup):
            lib.delete_backup(link, [parent])
        self.assertTrue(os.path.isdir(real))


class CheckTests(TempCase):
    def test_a_whole_backup_passes(self):
        report = lib.check_backup(make_backup(self.tmp))
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(report.complete_check)
        self.assertEqual(report.files, 2)

    def test_a_missing_file_is_found(self):
        path = make_backup(self.tmp)
        file_id = fb.file_id_for("HomeDomain", "Library/a.txt")
        os.remove(os.path.join(path, file_id[:2], file_id))
        report = lib.check_backup(path)
        self.assertFalse(report.ok)
        self.assertEqual(report.missing, 1)
        self.assertIn(file_id, report.problems[0])

    def test_a_missing_index_is_a_problem(self):
        path = make_backup(self.tmp)
        os.remove(os.path.join(path, "Manifest.db"))
        report = lib.check_backup(path)
        self.assertFalse(report.ok)
        self.assertFalse(report.complete_check)

    def test_an_interrupted_backup_says_so(self):
        report = lib.check_backup(make_backup(self.tmp, finished=False))
        self.assertFalse(report.ok)
        self.assertIn("interrupted", report.problems[0])

    def test_an_encrypted_backup_is_checked_as_far_as_it_can_be(self):
        report = lib.check_backup(make_backup(self.tmp, encrypted=True))
        self.assertTrue(report.ok)
        self.assertFalse(report.complete_check)
        self.assertIn("password", report.note)

    def test_a_size_that_differs_is_not_a_fault(self):
        # (phones list the size a database had before compacting it)
        path = make_backup(self.tmp)
        conn = sqlite3.connect(os.path.join(path, "Manifest.db"))
        blob = plistlib.dumps({
            "$archiver": "NSKeyedArchiver", "$version": 100000,
            "$top": {"root": plistlib.UID(1)},
            "$objects": ["$null", {"Size": 9999, "LastModified": 1,
                                   "$class": plistlib.UID(2)},
                         {"$classname": "MBFile"}]},
            fmt=plistlib.FMT_BINARY)
        conn.execute("UPDATE Files SET file=?", (blob,))
        conn.commit()
        conn.close()
        report = lib.check_backup(path)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.wrong_size, 2)     # (the sizes were read)
        self.assertIn("normal", report.note)

    def test_a_damaged_index_is_reported_not_raised(self):
        path = make_backup(self.tmp)
        with open(os.path.join(path, "Manifest.db"), "wb") as f:
            f.write(b"this is not a database at all" * 10)
        report = lib.check_backup(path)
        self.assertFalse(report.ok)

    def test_the_check_can_be_cancelled(self):
        with self.assertRaises(lib.Cancelled):
            lib.check_backup(make_backup(self.tmp), cancel=lambda: True)


class SettingsTests(TempCase):
    def test_choices_survive_a_restart(self):
        s = app_settings.Settings(self.tmp)
        s.add_folder(os.path.join(self.tmp, "drive"))
        s.backup_destination = "/mnt/backups"
        s.tools_folder = "/opt/idevice"
        self.assertTrue(s.save())
        again = app_settings.Settings.load(self.tmp)
        self.assertEqual(again.backup_folders,
                         [os.path.abspath(os.path.join(self.tmp, "drive"))])
        self.assertEqual(again.backup_destination, "/mnt/backups")
        self.assertEqual(again.tools_folder, "/opt/idevice")

    def test_a_folder_is_remembered_once_and_can_be_forgotten(self):
        s = app_settings.Settings(self.tmp)
        s.add_folder("/x")
        s.add_folder("/x")
        self.assertEqual(len(s.backup_folders), 1)
        s.remove_folder(s.backup_folders[0])
        self.assertEqual(s.backup_folders, [])

    def test_a_missing_or_damaged_file_is_empty_settings(self):
        self.assertEqual(app_settings.Settings.load(self.tmp).backup_folders,
                         [])
        with open(os.path.join(self.tmp, "settings.json"), "w") as f:
            f.write("{ nonsense")
        self.assertEqual(app_settings.Settings.load(self.tmp).tools_folder,
                         "")
        with open(os.path.join(self.tmp, "settings.json"), "w") as f:
            f.write('{"backup_folders": "oops", "tools_folder": 7}')
        loaded = app_settings.Settings.load(self.tmp)
        self.assertEqual(loaded.backup_folders, [])
        self.assertEqual(loaded.tools_folder, "")

    def test_a_save_that_cannot_happen_is_not_an_error(self):
        blocker = os.path.join(self.tmp, "file")
        open(blocker, "w").close()
        self.assertFalse(app_settings.Settings(
            os.path.join(blocker, "sub")).save())
        self.assertFalse(app_settings.Settings(None).save())

    def test_the_folder_follows_each_systems_convention(self):
        self.assertTrue(app_settings.settings_folder(
            "Windows", {"APPDATA": r"C:\A"}, "h").startswith("C:\\A"))
        self.assertEqual(app_settings.settings_folder(
            "Linux", {"XDG_CONFIG_HOME": "/c"}, "/h").replace("\\", "/"),
            "/c/ios-backup-explorer")
        self.assertIn("Application Support", app_settings.settings_folder(
            "Darwin", {}, "/Users/x"))


if __name__ == "__main__":
    unittest.main()
