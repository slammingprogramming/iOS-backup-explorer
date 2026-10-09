# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Unencrypted backups: detection, browsing and extraction (no password)."""

import os
import plistlib
import shutil
import tempfile
import unittest
from unittest import mock

import ios_backup_explorer as app
from tests import fixture_backup as fb


def read(path):
    with open(app.fs_path(path), "rb") as handle:
        return handle.read()


def snapshot(root):
    """Every file under *root* with its size and modification time."""
    state = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            info = os.stat(path)
            state[os.path.relpath(path, root)] = (info.st_size,
                                                  info.st_mtime_ns)
    return state


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-plain-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_dir(self, **files):
        folder = tempfile.mkdtemp(dir=self.tmp)
        for name, content in files.items():
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(content)
        return folder


class DetectBackupTests(TempDirCase):
    def test_encrypted_and_unencrypted(self):
        enc, _ = fb.build_backup(self.make_dir())
        plain, _ = fb.build_backup(self.make_dir(), encrypted=False)
        self.assertEqual(app.detect_backup(enc), app.ENCRYPTED)
        self.assertEqual(app.detect_backup(plain), app.UNENCRYPTED)

    def test_missing_is_unencrypted_flag_means_unencrypted(self):
        folder = self.make_dir(**{
            "Manifest.plist": plistlib.dumps({"Version": "10.0"}),
            "Manifest.db": b"x"})
        self.assertEqual(app.detect_backup(folder), app.UNENCRYPTED)

    def assertRejected(self, folder, *fragments):
        with self.assertRaises(app.BackupFormatError) as ctx:
            app.detect_backup(folder)
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    def test_folder_that_is_not_a_backup(self):
        self.assertRejected(self.make_dir(), "Manifest.plist")
        self.assertRejected(os.path.join(self.tmp, "nope"), "does not exist")

    def test_legacy_mbdb_backups_are_explained(self):
        self.assertRejected(self.make_dir(**{"Manifest.mbdb": b"mbdb"}),
                            "Manifest.mbdb")
        self.assertRejected(
            self.make_dir(**{"Manifest.plist": plistlib.dumps({}),
                             "Manifest.mbdb": b"mbdb"}),
            "Manifest.mbdb")

    def test_missing_manifest_db(self):
        self.assertRejected(
            self.make_dir(**{"Manifest.plist":
                             plistlib.dumps({"IsEncrypted": False})}),
            "no Manifest.db")

    def test_unreadable_manifest_plist(self):
        self.assertRejected(self.make_dir(**{"Manifest.plist": b"\x00junk"}),
                            "could not be read")
        self.assertRejected(
            self.make_dir(**{"Manifest.plist": plistlib.dumps([1, 2])}),
            "expected format")


class PlainSessionCase(TempDirCase):
    def setUp(self):
        super().setUp()
        self.backup_dir, self.ids = fb.build_backup(
            self.make_dir(), encrypted=False)
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.session = app.BackupSession()
        self.addCleanup(self._close_session)

    def _close_session(self):
        self.session.close()
        self.session._executor.shutdown(wait=True)

    def open(self, passphrase=None):
        return self.session.open(self.backup_dir, passphrase).result(60)

    def extract(self, *keys):
        ids = [self.ids[k] for k in keys]
        return self.session.extract(ids, self.out).result(60)

    def out_path(self, domain, rel_path):
        return app.build_output_path(self.out, domain, rel_path)


class OpenUnencryptedTests(PlainSessionCase):
    def test_opens_without_a_password(self):
        result = self.open()
        self.assertFalse(result.encrypted)
        self.assertIn(fb.NOTES_DOMAIN, result.domains)
        self.assertEqual(result.total, len(fb.DEFAULT_FILES))

    def test_a_password_is_ignored(self):
        self.assertFalse(self.open("not needed").encrypted)

    def test_scan_reads_the_index(self):
        self.open()
        rows = self.session.scan().result(60)
        by_path = {(r[1], r[2]): r for r in rows if r[3] == 1}
        self.assertEqual(len(by_path), len(fb.DEFAULT_FILES))
        _id, _d, _p, _flags, size, mtime, birth = by_path[
            ("HomeDomain", "Library/Preferences/plain.txt")]
        self.assertEqual((size, mtime, birth), (20, 1_700_000_000,
                                                1_700_000_000))

    def test_encrypted_backup_still_needs_its_password(self):
        enc_dir, _ = fb.build_backup(self.make_dir())
        for given in (None, ""):
            error = self.session.open(enc_dir, given).exception(60)
            self.assertIsInstance(error, app.PassphraseRequiredError)
        self.assertTrue(app.is_wrong_passphrase(
            self.session.open(enc_dir, "wrong").exception(60)))
        self.assertTrue(self.session.open(enc_dir, fb.PASSPHRASE)
                        .result(60).encrypted)

    def test_switching_between_encrypted_and_unencrypted(self):
        enc_dir, _ = fb.build_backup(self.make_dir())
        self.assertTrue(self.session.open(enc_dir, fb.PASSPHRASE)
                        .result(60).encrypted)
        self.assertFalse(self.open().encrypted)
        self.assertTrue(self.session.scan().result(60))

    def test_corrupt_manifest_db_is_a_clear_error(self):
        with open(os.path.join(self.backup_dir, "Manifest.db"), "wb") as f:
            f.write(b"this is not a database" * 100)
        error = self.session.open(self.backup_dir).exception(60)
        self.assertIsInstance(error, app.BackupFormatError)

    def test_encrypted_manifest_db_under_an_unencrypted_flag(self):
        # An encrypted Manifest.db is unreadable noise to SQLite.
        enc_dir, _ = fb.build_backup(self.make_dir())
        with open(os.path.join(enc_dir, "Manifest.plist"), "wb") as handle:
            plistlib.dump({"IsEncrypted": False}, handle)
        error = self.session.open(enc_dir).exception(60)
        self.assertIsInstance(error, app.BackupFormatError)


class ExtractUnencryptedTests(PlainSessionCase):
    def setUp(self):
        super().setUp()
        self.open()

    def test_every_file_is_extracted_byte_for_byte(self):
        keys = [(d, r) for d, r, c in fb.DEFAULT_FILES if c]
        report = self.extract(*keys)
        self.assertEqual((report.extracted, report.errors, report.skipped),
                         (len(keys), [], []))
        for key in keys:
            self.assertEqual(read(self.out_path(*key)),
                             fb.content_of(*key), key)

    def test_modification_time_is_restored(self):
        key = ("HomeDomain", "Library/Preferences/plain.txt")
        self.extract(key)
        self.assertEqual(int(os.path.getmtime(self.out_path(*key))),
                         1_700_000_000)

    def test_domains_differing_only_at_a_like_wildcard(self):
        a = ("AppDomain-com.a_c", "Documents/data.txt")
        b = ("AppDomain-com.a-c", "Documents/data.txt")
        self.extract(a, b)
        self.assertEqual(read(self.out_path(*a)), b"data of a_c")
        self.assertEqual(read(self.out_path(*b)), b"data of a-c")

    def test_empty_file(self):
        key = ("HomeDomain", "Library/empty.txt")
        report = self.extract(key)
        self.assertEqual((report.extracted, report.errors), (1, []))
        self.assertEqual(read(self.out_path(*key)), b"")

    def test_missing_data_is_an_error_and_leaves_no_debris(self):
        key = ("HomeDomain", "Library/missing.bin")
        report = self.extract(key)
        self.assertEqual((report.extracted, len(report.errors)), (0, 1))
        self.assertFalse(os.path.exists(self.out_path(*key)))
        self.assertEqual(os.listdir(os.path.dirname(self.out_path(*key))), [])

    def test_a_hostile_file_id_in_the_manifest_is_refused(self):
        import sqlite3
        conn = sqlite3.connect(os.path.join(self.backup_dir, "Manifest.db"))
        conn.execute("INSERT INTO Files VALUES (?, 'HomeDomain', "
                     "'Library/evil.txt', 1, NULL)", ("../../escape",))
        conn.commit()
        conn.close()
        self.open()  # reopen to see the new row
        report = self.session.extract(["../../escape"], self.out).result(60)
        self.assertEqual((report.extracted, len(report.errors)), (0, 1))
        self.assertIn("invalid file ID", report.errors[0][1])


class NoSideEffectsTests(PlainSessionCase):
    def test_the_backup_folder_is_never_modified(self):
        before = snapshot(self.backup_dir)
        self.open()
        self.session.scan().result(60)
        self.extract(("HomeDomain", "Library/Preferences/plain.txt"),
                     (fb.NOTES_DOMAIN, fb.NOTES_MOV))
        self.session.close()
        self.session._executor.shutdown(wait=True)
        self.assertEqual(snapshot(self.backup_dir), before)

    def test_no_temporary_manifest_copy_is_made(self):
        with mock.patch("tempfile.mkdtemp") as mkdtemp:
            self.open()
            self.extract(("HomeDomain", "Library/Preferences/plain.txt"))
        mkdtemp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
