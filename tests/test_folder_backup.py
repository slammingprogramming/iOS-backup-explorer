# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Backups that were already decrypted and extracted into domain folders."""

import hashlib
import os
import plistlib
import shutil
import tempfile
import unittest

import folder_backup as fbk
import ios_backup_explorer as app

MTIME = 1_700_000_000
FILES = {
    ("HomeDomain", "Library/SMS/sms.db"): b"pretend database",
    ("HomeDomain", "Library/Notes/a b.txt"): b"hello",
    ("HomeDomain", "Library/Empty.bin"): b"",
    ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0001.JPG"): b"jpeg" * 100,
    ("AppDomain-com.example.app", "Documents/x.txt"): b"app",
    ("AppDomainGroup-group.com.example", "y.txt"): b"group",
}


def build_extracted(parent, files=FILES, extra=()):
    root = os.path.join(parent, "extracted")
    for (domain, rel), data in files.items():
        path = os.path.join(root, domain, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        os.utime(path, (MTIME, MTIME))
    os.makedirs(os.path.join(root, "HomeDomain", "Library", "EmptyFolder"))
    for name in extra:
        with open(os.path.join(root, name), "wb") as handle:
            handle.write(b"x")
    return root


def snapshot(root):
    state = {}
    for folder, dirs, names in os.walk(root):
        for name in dirs + names:
            path = os.path.join(folder, name)
            info = os.stat(path)
            state[os.path.relpath(path, root)] = (info.st_size,
                                                  info.st_mtime_ns)
    return state


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-extracted-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = build_extracted(self.tmp)
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)


class NameTests(unittest.TestCase):
    def test_domain_names(self):
        for name in ("HomeDomain", "CameraRollDomain", "WirelessDomain",
                     "AppDomain-com.apple.mobilesafari",
                     "AppDomainGroup-group.com.example",
                     "AppDomainPlugin-com.example.plug",
                     "SysSharedContainerDomain-systemgroup.com.apple.x"):
            self.assertTrue(fbk.looks_like_domain(name), name)
        for name in ("Photos", "Domain.txt", "notes", "Manifest.db",
                     "My-HomeDomain", ""):
            self.assertFalse(fbk.looks_like_domain(name), name)

    def test_the_ids_are_those_of_a_real_backup(self):
        self.assertEqual(
            fbk.file_id_for("HomeDomain", "Library/SMS/sms.db"),
            hashlib.sha1(b"HomeDomain-Library/SMS/sms.db").hexdigest())
        self.assertEqual(len({fbk.file_id_for("A", "b"),
                              fbk.file_id_for("Ab", "")}), 2)


class DetectTests(Case):
    def test_an_extracted_folder(self):
        self.assertTrue(fbk.looks_extracted(self.root))
        self.assertEqual(app.detect_backup(self.root), app.EXTRACTED)

    def test_stray_files_beside_the_domains_are_fine(self):
        root = build_extracted(tempfile.mkdtemp(dir=self.tmp),
                               extra=("notes.txt", ".DS_Store"))
        self.assertEqual(app.detect_backup(root), app.EXTRACTED)

    def test_not_an_extracted_folder(self):
        empty = tempfile.mkdtemp(dir=self.tmp)
        self.assertFalse(fbk.looks_extracted(empty))
        self.assertFalse(fbk.looks_extracted(os.path.join(self.tmp, "nope")))
        os.makedirs(os.path.join(empty, "Pictures"))
        self.assertFalse(fbk.looks_extracted(empty))
        with self.assertRaises(app.BackupFormatError) as ctx:
            app.detect_backup(empty)
        self.assertIn("extracted domain folders", str(ctx.exception))

    def test_a_domain_name_that_is_a_file_does_not_count(self):
        folder = tempfile.mkdtemp(dir=self.tmp)
        with open(os.path.join(folder, "HomeDomain"), "wb") as handle:
            handle.write(b"x")
        self.assertFalse(fbk.looks_extracted(folder))

    def test_a_real_backups_manifest_wins(self):
        for name in ("Manifest.db", "Manifest.plist", "Manifest.mbdb"):
            folder = build_extracted(tempfile.mkdtemp(dir=self.tmp))
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(b"x")
            self.assertFalse(fbk.looks_extracted(folder), name)
            if name != "Manifest.plist":
                with self.assertRaises(app.BackupFormatError):
                    app.detect_backup(folder)

    def test_the_other_kinds_are_unchanged(self):
        from tests import fixture_backup as fb
        enc, _ = fb.build_backup(tempfile.mkdtemp(dir=self.tmp))
        plain, _ = fb.build_backup(tempfile.mkdtemp(dir=self.tmp),
                                   encrypted=False)
        self.assertEqual(app.detect_backup(enc), app.ENCRYPTED)
        self.assertEqual(app.detect_backup(plain), app.UNENCRYPTED)


class SessionCase(Case):
    def setUp(self):
        super().setUp()
        self.session = app.BackupSession()
        self.addCleanup(self._close)

    def _close(self):
        self.session.close()
        self.session._executor.shutdown(wait=True)

    def open(self, passphrase=None):
        return self.session.open(self.root, passphrase).result(60)

    def rows(self):
        self.open()
        return {(r[1], r[2]): r for r in self.session.scan().result(60)}


class OpenTests(SessionCase):
    def test_it_opens_without_a_password(self):
        result = self.open()
        self.assertFalse(result.encrypted)
        self.assertEqual(sorted(result.domains), sorted(
            {d for d, _ in FILES}))
        self.assertEqual(result.total, len(FILES))

    def test_a_password_is_ignored(self):
        self.assertFalse(self.open("not needed").encrypted)

    def test_the_index_has_files_and_folders(self):
        rows = self.rows()
        sms = rows[("HomeDomain", "Library/SMS/sms.db")]
        self.assertEqual(sms[0], fbk.file_id_for("HomeDomain",
                                                 "Library/SMS/sms.db"))
        self.assertEqual((sms[3], sms[4], sms[5]), (1, 16, MTIME))
        self.assertEqual(rows[("HomeDomain", "Library/SMS")][3], 2)
        self.assertEqual(rows[("HomeDomain", "Library/EmptyFolder")][3], 2)
        self.assertIn(("HomeDomain", "Library/Notes/a b.txt"), rows)
        self.assertEqual(rows[("HomeDomain", "Library/Empty.bin")][4], 0)
        self.assertIn(("AppDomain-com.example.app", "Documents/x.txt"), rows)

    def test_things_that_are_not_domains_are_left_out(self):
        root = build_extracted(tempfile.mkdtemp(dir=self.tmp),
                               extra=("readme.txt",))
        os.makedirs(os.path.join(root, "Pictures"))
        with open(os.path.join(root, "Pictures", "a.jpg"), "wb") as handle:
            handle.write(b"x")
        self.root = root
        self.assertNotIn("Pictures", {d for d, _ in self.rows()})

    @unittest.skipUnless(hasattr(os, "symlink"), "no symbolic links")
    def test_a_link_pointing_out_of_the_folder_is_not_followed(self):
        secret = os.path.join(self.tmp, "secret.txt")
        with open(secret, "wb") as handle:
            handle.write(b"top secret")
        try:
            os.symlink(secret, os.path.join(self.root, "HomeDomain",
                                            "link.txt"))
            os.symlink(self.tmp, os.path.join(self.root, "HomeDomain",
                                              "linkdir"))
        except (OSError, NotImplementedError):
            self.skipTest("cannot make symbolic links here")
        rows = self.rows()
        self.assertNotIn(("HomeDomain", "link.txt"), rows)
        self.assertFalse([k for k in rows if k[1].startswith("linkdir")])

    def test_an_empty_domain_folder_is_not_an_error(self):
        os.makedirs(os.path.join(self.root, "WirelessDomain"))
        self.assertEqual(self.open().total, len(FILES))


class ExtractTests(SessionCase):
    def extract(self, *keys):
        self.open()
        ids = [fbk.file_id_for(*k) for k in keys]
        return self.session.extract(ids, self.out).result(60)

    def test_files_come_out_byte_for_byte_with_their_times(self):
        self.extract(*FILES)
        for (domain, rel), data in FILES.items():
            path = app.build_output_path(self.out, domain, rel)
            with open(app.fs_path(path), "rb") as handle:
                self.assertEqual(handle.read(), data, (domain, rel))
            self.assertEqual(int(os.stat(path).st_mtime), MTIME)

    def test_the_folder_is_never_modified(self):
        before = snapshot(self.root)
        self.extract(*FILES)
        self.rows()
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(os.listdir(self.root).count("Manifest.db"), 0)

    def test_a_file_that_vanished_is_an_error_without_debris(self):
        self.open()
        os.remove(os.path.join(self.root, "HomeDomain", "Library", "SMS",
                               "sms.db"))
        report = self.session.extract(
            [fbk.file_id_for("HomeDomain", "Library/SMS/sms.db")],
            self.out).result(60)
        self.assertEqual((report.extracted, len(report.errors)), (0, 1))
        left = [n for _d, _s, names in os.walk(self.out) for n in names]
        self.assertEqual(left, [])


class BackendTests(Case):
    def setUp(self):
        super().setUp()
        self.backend = fbk.FolderBackend(self.root)
        self.addCleanup(self.backend.close)

    def test_the_index_is_the_files_table(self):
        with self.backend.manifest_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM Files WHERE flags = 1")
            self.assertEqual(cur.fetchone()[0], len(FILES))

    def test_files_are_used_where_they_are(self):
        path = self.backend.materialize(
            None, "id", "HomeDomain", "Library/SMS/sms.db", 16, MTIME,
            os.path.join(self.tmp, "cache"))
        self.assertEqual(path, os.path.join(self.root, "HomeDomain",
                                            "Library", "SMS", "sms.db"))

    def test_an_empty_file_is_given_an_empty_stand_in(self):
        cache = os.path.join(self.tmp, "cache")
        path = self.backend.materialize(None, "abc", "HomeDomain",
                                        "Library/Empty.bin", 0, MTIME, cache)
        self.assertEqual(os.path.getsize(path), 0)
        self.assertTrue(path.startswith(cache))

    def test_a_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            self.backend.materialize(None, "id", "HomeDomain", "gone.db", 5,
                                     MTIME, self.tmp)

    def test_paths_that_leave_the_folder_are_refused(self):
        for rel in ("../outside.txt", "a/../../x", "/etc/passwd", "a//b",
                    "a\\..\\..\\x", "./x", ""):
            with self.subTest(rel=rel):
                with self.assertRaises(ValueError):
                    self.backend._source("HomeDomain", rel)
        for domain in ("..", "", "Home/Domain", "a\\b"):
            with self.subTest(domain=domain):
                with self.assertRaises(ValueError):
                    self.backend._source(domain, "x.txt")

    def test_the_record_holds_what_the_app_reads(self):
        blob = fbk.file_record(1234, MTIME, MTIME - 5)
        plist = plistlib.loads(blob)
        record = plist["$objects"][1]
        self.assertEqual((record["Size"], record["LastModified"],
                          record["Birth"]), (1234, MTIME, MTIME - 5))
        self.assertNotIn("Birth", plistlib.loads(
            fbk.file_record(1, 0))["$objects"][1])


if __name__ == "__main__":
    unittest.main()
