# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Mounting: the tree, the read-only file system, the Mount handle, and the
session calls they rely on. None of this needs FUSE except the one real
Windows mount test at the bottom, which skips itself when WinFsp or mfusepy
is missing."""

import errno
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

import backup_mount as bm
import ios_backup_explorer as app
from tests import fixture_backup as fb

MOV = (fb.NOTES_DOMAIN, fb.NOTES_MOV)


def fs_path(domain, rel_path):
    return "/" + domain + "/" + rel_path


class MountCase(unittest.TestCase):
    encrypted = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-mount-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backup_dir, self.ids = fb.build_backup(
            tempfile.mkdtemp(dir=self.tmp), encrypted=self.encrypted)
        self.cache = os.path.join(self.tmp, "cache")
        self.session = app.BackupSession()
        self.addCleanup(self._close)
        if self.encrypted:
            self.session.open(self.backup_dir, fb.PASSPHRASE).result(60)
        else:
            self.session.open(self.backup_dir).result(60)

    def _close(self):
        self.session.close()
        self.session._executor.shutdown(wait=True)

    def make_fs(self, windows=False, case_insensitive=False):
        rows = self.session.list_all().result(60)
        tree = bm.BackupTree(rows, windows=windows,
                             case_insensitive=case_insensitive)
        return bm.BackupFilesystem(
            tree, lambda fid: self.session.cache_file(fid, self.cache)
            .result(60))

    @staticmethod
    def read_all(fs, path):
        fh = fs.open(path, os.O_RDONLY)
        try:
            size = fs.getattr(path)["st_size"]
            chunks, offset = [], 0
            while offset < size:
                chunk = fs.read(path, 65536, offset, fh)
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
            return b"".join(chunks)
        finally:
            fs.release(path, fh)


# ── session additions ────────────────────────────────────────

class SessionAdditionTests(MountCase):
    def test_list_all(self):
        rows = self.session.list_all().result(60)
        self.assertEqual(len(rows), len(fb.DEFAULT_FILES))
        by_path = {(r[1], r[2]): r for r in rows}
        file_id, _d, _p, size, mtime = by_path[MOV]
        self.assertEqual(file_id, self.ids[MOV])
        self.assertEqual(size, len(fb.content_of(*MOV)))
        self.assertEqual(mtime, 1_700_000_000)

    def test_cache_file_decrypts_once_and_reuses(self):
        path = self.session.cache_file(self.ids[MOV], self.cache).result(60)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), fb.content_of(*MOV))
        stamp = os.stat(path).st_mtime_ns
        again = self.session.cache_file(self.ids[MOV], self.cache).result(60)
        self.assertEqual((again, os.stat(again).st_mtime_ns), (path, stamp))

    def test_cache_file_errors(self):
        self.assertIsInstance(
            self.session.cache_file("0" * 40, self.cache).exception(60),
            FileNotFoundError)
        missing = self.ids[("HomeDomain", "Library/missing.bin")]
        self.assertIsNotNone(
            self.session.cache_file(missing, self.cache).exception(60))

    def test_cache_file_empty_file(self):
        empty = self.ids[("HomeDomain", "Library/empty.txt")]
        path = self.session.cache_file(empty, self.cache).result(60)
        self.assertEqual(os.path.getsize(path), 0)

    def test_extract_all_is_not_limited_by_the_row_cap(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        with mock.patch.object(app, "MAX_ROWS", 2):
            report = self.session.extract_all(out).result(120)
        with_data = [k for k in self.ids if fb.content_of(*k)]
        # missing.bin is listed but has no data: reported, not fatal.
        self.assertEqual(report.extracted, len(with_data) + 1)  # + empty file
        self.assertEqual(len(report.errors), 1)
        self.assertIn("missing.bin", report.errors[0][0])
        for key in with_data:
            path = app.build_output_path(out, *key)
            with open(app.fs_path(path), "rb") as handle:
                self.assertEqual(handle.read(), fb.content_of(*key), key)


class SessionAdditionPlainTests(SessionAdditionTests):
    encrypted = False

    def test_plain_files_are_served_in_place_without_a_copy(self):
        path = self.session.cache_file(self.ids[MOV], self.cache).result(60)
        self.assertEqual(os.path.dirname(os.path.dirname(path)),
                         os.path.abspath(self.backup_dir))
        self.assertFalse(os.path.exists(self.cache))   # nothing was copied

    def test_cache_file_reuses_in_place_data(self):
        pass  # covered by the in-place test above; there is no cache


# ── the tree ─────────────────────────────────────────────────

def rows(*entries):
    return [(fid, dom, rel, size, None) for fid, dom, rel, size in entries]


class BackupTreeTests(unittest.TestCase):
    def test_structure_and_stats(self):
        tree = bm.BackupTree(rows(
            ("a" * 40, "HomeDomain", "Library/SMS/sms.db", 10),
            ("b" * 40, "HomeDomain", "Library/Notes/n.txt", 5),
            ("c" * 40, "MediaDomain", "Media/p.jpg", 7),
        ), windows=False, case_insensitive=False)
        self.assertEqual(sorted(tree.names(tree.root)),
                         ["HomeDomain", "MediaDomain"])
        sms = tree.lookup("/HomeDomain/Library/SMS/sms.db")
        self.assertEqual((sms.file_id, sms.size), ("a" * 40, 10))
        self.assertTrue(tree.is_dir(tree.lookup("/HomeDomain/Library")))
        self.assertIsNone(tree.lookup("/HomeDomain/nope"))
        self.assertIsNone(tree.lookup("/HomeDomain/Library/SMS/sms.db/x"))
        self.assertEqual((tree.file_count, tree.total_size), (3, 22))

    def test_windows_hostile_names_are_sanitised(self):
        tree = bm.BackupTree(rows(
            ("a" * 40, "HomeDomain", "Notes/what?:file*.txt", 1),
            ("b" * 40, "HomeDomain", "CON", 1),
        ), windows=True)
        folder = tree.lookup("/HomeDomain/Notes")
        self.assertEqual(tree.names(folder), ["what__file_.txt"])
        self.assertIn("_CON", tree.names(tree.lookup("/HomeDomain")))

    def test_same_name_in_different_case_is_kept_apart_where_case_folds(self):
        tree = bm.BackupTree(rows(
            ("a" * 40, "D", "Photo.JPG", 1),
            ("b" * 40, "D", "photo.jpg", 2),
        ), windows=False, case_insensitive=True)
        names = tree.names(tree.lookup("/D"))
        self.assertEqual(len(names), 2)
        self.assertEqual(len({n.casefold() for n in names}), 2)

    def test_case_is_not_folded_where_the_host_is_case_sensitive(self):
        tree = bm.BackupTree(rows(
            ("a" * 40, "D", "Photo.JPG", 1),
            ("b" * 40, "D", "photo.jpg", 2),
        ), windows=False, case_insensitive=False)
        self.assertEqual(sorted(tree.names(tree.lookup("/D"))),
                         ["Photo.JPG", "photo.jpg"])

    def test_a_file_and_a_folder_with_the_same_name_both_survive(self):
        tree = bm.BackupTree(rows(
            ("a" * 40, "D", "thing", 1),
            ("b" * 40, "D", "thing/inner.txt", 2),
        ), windows=False, case_insensitive=False)
        names = tree.names(tree.lookup("/D"))
        self.assertEqual(len(names), 2)
        self.assertEqual(tree.file_count, 2)

    def test_dot_dot_and_empty_parts_never_escape(self):
        tree = bm.BackupTree(rows(
            ("a" * 40, "D", "../../evil.txt", 1),
            ("b" * 40, "D", "a//b/./c.txt", 1),
        ), windows=False, case_insensitive=False)
        self.assertEqual(tree.names(tree.lookup("/D")), ["evil.txt", "a"])
        self.assertIsNotNone(tree.lookup("/D/a/b/c.txt"))


# ── the file system ──────────────────────────────────────────

class FilesystemTests(MountCase):
    def test_directories_and_attributes(self):
        fs = self.make_fs()
        root = fs.getattr("/")
        self.assertTrue(stat.S_ISDIR(root["st_mode"]))
        self.assertIn(fb.NOTES_DOMAIN, fs.readdir("/", 0))
        self.assertIn(".", fs.readdir("/", 0))
        info = fs.getattr(fs_path(*MOV))
        self.assertTrue(stat.S_ISREG(info["st_mode"]))
        self.assertEqual(info["st_size"], len(fb.content_of(*MOV)))
        self.assertEqual(info["st_mtime"], 1_700_000_000 * 1_000_000_000)
        self.assertFalse(info["st_mode"] & 0o222)    # nobody can write

    def test_reads_are_byte_exact_in_chunks(self):
        fs = self.make_fs()
        self.assertEqual(self.read_all(fs, fs_path(*MOV)),
                         fb.content_of(*MOV))
        key = ("HomeDomain", "Library/Preferences/plain.txt")
        self.assertEqual(self.read_all(fs, fs_path(*key)),
                         fb.content_of(*key))

    def test_reading_at_an_offset(self):
        fs = self.make_fs()
        path = fs_path("HomeDomain", "Library/Preferences/plain.txt")
        fh = fs.open(path, os.O_RDONLY)
        self.assertEqual(fs.read(path, 4, 6, fh), b"from")
        self.assertEqual(fs.read(path, 100, 1000, fh), b"")
        fs.release(path, fh)

    def test_empty_file(self):
        fs = self.make_fs()
        path = fs_path("HomeDomain", "Library/empty.txt")
        self.assertEqual(fs.getattr(path)["st_size"], 0)
        self.assertEqual(self.read_all(fs, path), b"")

    def test_error_codes(self):
        fs = self.make_fs()

        def code(call, *args):
            with self.assertRaises(OSError) as ctx:
                call(*args)
            return ctx.exception.errno

        self.assertEqual(code(fs.getattr, "/nope"), errno.ENOENT)
        self.assertEqual(code(fs.readdir, "/nope", 0), errno.ENOENT)
        self.assertEqual(code(fs.readdir, fs_path(*MOV), 0), errno.ENOTDIR)
        self.assertEqual(code(fs.open, "/" + fb.NOTES_DOMAIN, os.O_RDONLY),
                         errno.EISDIR)
        self.assertEqual(code(fs.open, "/nope", os.O_RDONLY), errno.ENOENT)
        # listed in the backup, but its data is missing
        missing = fs_path("HomeDomain", "Library/missing.bin")
        self.assertEqual(code(fs.open, missing, os.O_RDONLY), errno.ENOENT)

    def test_it_is_read_only(self):
        fs = self.make_fs()
        path = fs_path(*MOV)
        for flags in (os.O_WRONLY, os.O_RDWR):
            with self.assertRaises(OSError) as ctx:
                fs.open(path, flags)
            self.assertEqual(ctx.exception.errno, errno.EROFS)
        for name, args in (("write", (path, b"x", 0, 0)),
                           ("create", (path, 0o644)),
                           ("unlink", (path,)), ("mkdir", ("/x", 0o755)),
                           ("rmdir", ("/x",)), ("truncate", (path, 0)),
                           ("chmod", (path, 0o777)),
                           ("chown", (path, 0, 0)),
                           ("rename", (path, "/y"))):
            with self.assertRaises(OSError, msg=name) as ctx:
                getattr(fs, name)(*args)
            self.assertEqual(ctx.exception.errno, errno.EROFS, name)

    def test_statfs_describes_the_backup(self):
        stats = self.make_fs().statfs("/")
        self.assertEqual(stats["f_files"], len(fb.DEFAULT_FILES))
        self.assertGreater(stats["f_blocks"], 0)
        self.assertEqual(stats["f_bavail"], 0)

    def test_windows_names_are_usable_through_the_file_system(self):
        fs = self.make_fs(windows=True)
        names = fs.readdir("/HomeDomain/Library/Notes", 0)
        self.assertIn("what__file_.txt", names)
        self.assertEqual(
            self.read_all(fs, "/HomeDomain/Library/Notes/what__file_.txt"),
            b"windows-hostile name")

    def test_exit_request_is_acted_on_by_the_next_request(self):
        fs = self.make_fs()
        hook = mock.Mock()
        fs.exit_hook = hook
        fs.getattr("/")
        hook.assert_not_called()
        fs.request_exit()
        fs.getattr("/")
        hook.assert_called_once_with()

    def test_init_reports_ready(self):
        fs = self.make_fs()
        fs.on_ready = ready = mock.Mock()
        fs.init("/")
        ready.assert_called_once_with()

    def test_concurrent_readers_get_consistent_data(self):
        fs = self.make_fs()
        errors = []

        def reader():
            try:
                for _ in range(3):
                    data = self.read_all(fs, fs_path(*MOV))
                    if data != fb.content_of(*MOV):
                        errors.append("mismatch")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class FilesystemOnUnencryptedBackupTests(FilesystemTests):
    encrypted = False

    def test_data_is_served_in_place_and_nothing_is_cached(self):
        fs = self.make_fs()
        self.assertEqual(self.read_all(fs, fs_path(*MOV)),
                         fb.content_of(*MOV))
        self.assertFalse(os.path.exists(self.cache))


class EncryptedCacheTests(MountCase):
    def test_decrypted_data_is_cached_and_the_cache_can_be_removed(self):
        fs = self.make_fs()
        self.read_all(fs, fs_path(*MOV))
        self.assertTrue(os.listdir(self.cache))
        shutil.rmtree(self.cache)
        self.assertEqual(self.read_all(fs, fs_path(*MOV)),
                         fb.content_of(*MOV))   # decrypted again on demand


class LeakTests(unittest.TestCase):
    def test_a_surviving_traceback_cannot_leave_the_decrypted_manifest(self):
        """An error raised inside the library's cursor context keeps the
        library object alive through its traceback. Closing the session must
        still delete the decrypted Manifest.db, on the right thread."""
        import gc
        import sys
        tmp = tempfile.mkdtemp(prefix="ibe-leak-")
        self.addCleanup(shutil.rmtree, tmp, True)
        backup_dir, ids = fb.build_backup(tmp)
        made, unraisable = [], []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            made.append(path)
            return path

        session = app.BackupSession()
        with mock.patch("tempfile.mkdtemp", spy):
            session.open(backup_dir, fb.PASSPHRASE).result(60)
        missing = ids[("HomeDomain", "Library/missing.bin")]
        failure = session.cache_file(missing, os.path.join(tmp, "c"))             .exception(60)              # keep it (and its traceback) alive
        self.assertIsNotNone(failure)
        session.close()
        session._executor.shutdown(wait=True)

        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]), "decrypted manifest left")
        old_hook = sys.unraisablehook
        sys.unraisablehook = lambda info: unraisable.append(info)
        try:
            del failure
            gc.collect()
        finally:
            sys.unraisablehook = old_hook
        self.assertEqual(unraisable, [])


# ── the Mount handle (with a stand-in for FUSE) ───────────────

class StubFuse:
    """Plays libfuse: calls init, then serves until asked to exit."""

    def __init__(self, fail_with=None, never_ready=False):
        self.fail_with = fail_with
        self.never_ready = never_ready
        self.calls = []
        self.exits = 0

    def fuse_exit(self):
        self.exits += 1

    def FUSE(self, filesystem, mountpoint, **options):   # noqa: N802
        self.calls.append((mountpoint, options))
        if self.fail_with:
            raise self.fail_with
        if not self.never_ready:
            filesystem.init("/")
        while not filesystem._exit_requested:
            time.sleep(0.01)
        filesystem.exit_hook()


class MountHandleTests(MountCase):
    def new_mount(self, windows, stub, **kwargs):
        patcher = mock.patch.object(bm, "_IS_WINDOWS", windows)
        patcher.start()
        self.addCleanup(patcher.stop)
        cache = os.path.join(self.tmp, "mount-cache")
        os.makedirs(cache)
        target = (dict(share="share1") if windows
                  else dict(mountpoint=os.path.join(self.tmp, "mnt")))
        return bm.Mount(self.make_fs(), cache_dir=cache, fuse=stub,
                        **target, **kwargs), cache

    def test_windows_mount_is_unc_only_and_uses_forward_slashes(self):
        stub = StubFuse()
        mount, cache = self.new_mount(True, stub)
        with mock.patch.object(os.path, "exists", return_value=True):
            mount.start()
        mountpoint, options = stub.calls[0]
        self.assertEqual(mountpoint, "")   # no drive letter
        self.assertEqual(options["VolumePrefix"], "/ios-backup/share1")
        self.assertTrue(options["ro"])
        self.assertEqual(mount.display_path, r"\\ios-backup\share1")
        self.assertTrue(mount.running)
        with mock.patch.object(os, "stat"):
            self.assertTrue(mount.stop())
        self.assertFalse(mount.running)
        self.assertFalse(os.path.exists(cache))      # cache removed
        self.assertEqual(stub.exits, 1)

    def test_posix_mount_uses_the_folder_and_unmounts_with_the_helper(self):
        stub = StubFuse()
        mount, cache = self.new_mount(False, stub)
        mount.start()
        self.assertEqual(stub.calls[0][0], os.path.join(self.tmp, "mnt"))
        self.assertNotIn("VolumePrefix", stub.calls[0][1])
        self.assertEqual(mount.display_path, os.path.join(self.tmp, "mnt"))
        with mock.patch.object(bm.subprocess, "run") as run, \
                mock.patch.object(bm.shutil, "which",
                                  side_effect=lambda n: "/bin/" + n
                                  if n == "fusermount3" else None), \
                mock.patch.object(bm.platform, "system",
                                  return_value="Linux"):
            self.assertTrue(mount.stop())
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0],
                         ["/bin/fusermount3", "-u",
                          os.path.join(self.tmp, "mnt")])

    def test_macos_unmounts_with_umount(self):
        stub = StubFuse()
        mount, _ = self.new_mount(False, stub)
        mount.start()
        with mock.patch.object(bm.subprocess, "run") as run, \
                mock.patch.object(bm.platform, "system",
                                  return_value="Darwin"):
            mount.stop()
        self.assertEqual(run.call_args[0][0][0], "umount")

    def test_a_failing_fuse_is_reported_and_cleaned_up(self):
        stub = StubFuse(fail_with=RuntimeError("1"))
        mount, cache = self.new_mount(False, stub)
        with self.assertRaises(bm.MountError):
            mount.start()
        self.assertFalse(os.path.exists(cache))
        self.assertFalse(mount.running)

    def test_on_stopped_fires_when_fuse_ends(self):
        stub = StubFuse()
        stopped = threading.Event()
        mount, _ = self.new_mount(False, stub)
        mount.on_stopped = stopped.set
        mount.start()
        with mock.patch.object(bm.subprocess, "run"):
            mount.stop()
        self.assertTrue(stopped.wait(5))

    def test_arguments_are_validated(self):
        with mock.patch.object(bm, "_IS_WINDOWS", True):
            with self.assertRaises(ValueError):
                bm.Mount(self.make_fs())
        with mock.patch.object(bm, "_IS_WINDOWS", False):
            with self.assertRaises(ValueError):
                bm.Mount(self.make_fs())

    def test_stop_before_start_is_harmless(self):
        mount, _ = self.new_mount(False, StubFuse())
        self.assertTrue(mount.stop())


class HelperTests(unittest.TestCase):
    def test_share_names(self):
        self.assertEqual(bm.default_share_name("C:/x/00001111-AB12"),
                         "00001111-AB12")
        self.assertEqual(bm.default_share_name("C:/x/we ird:name"),
                         "we_ird_name")
        self.assertEqual(bm.default_share_name(""), "backup")
        self.assertEqual(len(bm.default_share_name("a" * 100)), 40)
        self.assertEqual(bm.unc_path("abc"), "\\\\ios-backup\\abc")

    def test_load_fuse_explains_what_is_missing(self):
        real_import = __import__

        def no_mfusepy(name, *args, **kwargs):
            if name == "mfusepy":
                raise ImportError("no mfusepy")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", no_mfusepy):
            with self.assertRaises(bm.MountUnavailableError) as ctx:
                bm.load_fuse()
        self.assertIn("pip install mfusepy", str(ctx.exception))

    def test_unsupported_platforms_are_reported(self):
        with mock.patch.object(bm.platform, "system", return_value="Plan9"):
            with self.assertRaises(bm.MountUnavailableError):
                bm.load_fuse()


# ── a real mount (Windows + WinFsp + mfusepy only) ────────────

def _real_mount_unavailable():
    if os.name != "nt":
        return "the real mount test covers Windows/WinFsp"
    try:
        bm.load_fuse()
    except bm.MountUnavailableError as exc:
        return str(exc).splitlines()[0]
    return None


@unittest.skipIf(_real_mount_unavailable(), _real_mount_unavailable() or "")
class RealWinFspMountTests(unittest.TestCase):
    def mount(self, encrypted):
        tmp = tempfile.mkdtemp(prefix="ibe-realmount-")
        self.addCleanup(shutil.rmtree, tmp, True)
        backup_dir, _ = fb.build_backup(tempfile.mkdtemp(dir=tmp),
                                        encrypted=encrypted)
        session = app.BackupSession()
        self.addCleanup(lambda: (session.close(),
                                 session._executor.shutdown(wait=True)))
        if encrypted:
            session.open(backup_dir, fb.PASSPHRASE).result(60)
        else:
            session.open(backup_dir).result(60)
        cache = os.path.join(tmp, "cache")
        tree = bm.BackupTree(session.list_all().result(60))
        fs = bm.BackupFilesystem(
            tree, lambda fid: session.cache_file(fid, cache).result(60))
        mount = bm.Mount(fs, share=f"ibe-test-{os.getpid()}-{encrypted:d}",
                         cache_dir=cache)
        mount.start()
        self.addCleanup(mount.stop)
        return mount, cache

    def check(self, encrypted):
        mount, cache = self.mount(encrypted)
        root = mount.display_path
        self.assertTrue(root.startswith("\\\\ios-backup\\"))
        self.assertIn(fb.NOTES_DOMAIN, os.listdir(root))
        movie = os.path.join(root, fb.NOTES_DOMAIN, *fb.NOTES_MOV.split("/"))
        with open(movie, "rb") as handle:
            self.assertEqual(handle.read(), fb.content_of(*MOV))   # binary-safe
        with self.assertRaises(OSError):
            open(movie, "wb")                                      # read-only
        with self.assertRaises(OSError):
            os.mkdir(os.path.join(root, "new"))
        self.assertTrue(mount.stop())
        self.assertFalse(os.path.exists(root))                     # gone
        self.assertFalse(os.path.exists(cache))                    # cache gone

    def test_mount_an_encrypted_backup_as_a_unc_path(self):
        self.check(encrypted=True)

    def test_mount_an_unencrypted_backup_as_a_unc_path(self):
        self.check(encrypted=False)


if __name__ == "__main__":
    unittest.main()
