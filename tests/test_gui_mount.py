# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""GUI behaviour for "Extract Entire Backup" and "Mount Backup"
(skipped without a display)."""

import os
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

import backup_mount as bm
import ios_backup_explorer as app
from tests import fixture_backup as fb
from tests.test_mount import StubFuse


def _real_mount_unavailable():
    if os.name != "nt":
        return "the real mount test covers Windows/WinFsp"
    try:
        bm.load_fuse()
    except bm.MountUnavailableError as exc:
        return str(exc).splitlines()[0]
    return None


class MountGuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display available")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-gui-mount-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plain_dir, _ = fb.build_backup(
            tempfile.mkdtemp(dir=self.tmp), encrypted=False)
        self.enc_dir, _ = fb.build_backup(tempfile.mkdtemp(dir=self.tmp))
        self.out = os.path.join(self.tmp, "out")
        self.mnt = os.path.join(self.tmp, "mnt")
        os.makedirs(self.out)
        os.makedirs(self.mnt)

        self.dialogs = []
        for name in ("showerror", "showinfo", "showwarning"):
            patcher = mock.patch.object(
                app.messagebox, name,
                side_effect=lambda *a, _n=name, **k: self.dialogs.append(
                    (_n, a)))
            patcher.start()
            self.addCleanup(patcher.stop)

        def ask(title, message, **kwargs):
            self.dialogs.append(("askyesno", (title, message)))
            return title != "Backup mounted"    # don't open Explorer

        patcher = mock.patch.object(app.messagebox, "askyesno",
                                    side_effect=ask)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            app.filedialog, "askdirectory",
            side_effect=lambda **kw: self.mnt if "EMPTY" in kw.get(
                "title", "") else self.out)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Never look at the real backups on the machine running the tests.
        patcher = mock.patch.object(app.BackupExplorer, "BACKUP_PATHS", {})
        patcher.start()
        self.addCleanup(patcher.stop)

        self.explorer = app.BackupExplorer(self.root)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        if self.explorer._mount is not None:
            self.explorer._mount.stop()
        self.explorer._cancel_timers()
        self.explorer.session.close()
        self.explorer.session._executor.shutdown(wait=True)
        # Take this test's windows down, or they pile up in the shared root.
        for child in self.root.winfo_children():
            child.destroy()

    def wait_for(self, condition, what, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}; status="
                  f"{self.explorer.status_var.get()!r}")

    def open_backup(self, encrypted=False):
        ex = self.explorer
        ex.path_var.set(self.enc_dir if encrypted else self.plain_dir)
        if encrypted:
            ex.pass_var.set(fb.PASSPHRASE)
        ex._decrypt()
        self.wait_for(lambda: ex.backup_open, "backup to open")
        self.wait_for(lambda: ex.panel.index is not None, "file index")


class ExtractEntireBackupTests(MountGuiCase):
    def check_everything_was_written(self, encrypted):
        ex = self.explorer
        self.open_backup(encrypted)
        with mock.patch.object(app, "MAX_ROWS", 2):   # the view is capped
            ex.domain_tree.selection_set("__ALL__")
            self.wait_for(lambda: len(ex.file_tree.get_children()) == 2,
                          "capped file list")
            ex._extract_entire()
            self.wait_for(lambda: not ex._extracting
                          and any(d[0] != "askyesno" for d in self.dialogs),
                          "extraction")
        self.assertTrue(any(d[0] == "askyesno" for d in self.dialogs))
        # missing.bin has no data in the backup: the run reports it, not dies
        self.assertEqual(self.dialogs[-1][0], "showwarning", self.dialogs[-1])
        self.assertIn("missing.bin", self.dialogs[-1][1][1])
        for domain, rel_path, content in fb.DEFAULT_FILES:
            if content is None:
                continue
            path = app.fs_path(app.build_output_path(self.out, domain,
                                                     rel_path))
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), content, rel_path)

    def test_extracts_every_file_of_an_encrypted_backup(self):
        self.check_everything_was_written(encrypted=True)

    def test_extracts_every_file_of_an_unencrypted_backup(self):
        self.check_everything_was_written(encrypted=False)

    def test_needs_an_open_backup(self):
        self.explorer._extract_entire()
        self.assertEqual(self.dialogs[0][0], "showinfo")

    def test_declining_the_confirmation_extracts_nothing(self):
        self.open_backup()
        with mock.patch.object(app.messagebox, "askyesno",
                               return_value=False):
            self.explorer._extract_entire()
        self.assertFalse(self.explorer._extracting)
        self.assertEqual(os.listdir(self.out), [])


class MountButtonTests(MountGuiCase):
    def test_buttons_exist(self):
        self.assertEqual(self.explorer.mount_btn.cget("text"), "Mount Backup")

    def test_mounting_needs_an_open_backup(self):
        self.explorer._toggle_mount()
        self.assertEqual(self.dialogs[0][0], "showinfo")

    def test_missing_mount_support_is_explained(self):
        self.open_backup()
        error = bm.MountUnavailableError("Mounting needs the optional "
                                         "'mfusepy' package.")
        with mock.patch.object(bm, "load_fuse", side_effect=error):
            self.explorer._toggle_mount()
        self.assertEqual(self.dialogs[-1][0], "showerror")
        self.assertEqual(self.dialogs[-1][1][0], "Mounting is not available")
        self.assertIsNone(self.explorer._mount)
        self.assertEqual(self.explorer.mount_btn.cget("text"), "Mount Backup")

    def test_declining_the_mount_confirmation_mounts_nothing(self):
        self.open_backup()
        stub = StubFuse()
        with mock.patch.object(bm, "load_fuse", return_value=stub), \
                mock.patch.object(app.messagebox, "askyesno",
                                  return_value=False):
            self.explorer._toggle_mount()
        self.assertEqual(stub.calls, [])
        self.assertIsNone(self.explorer._mount)

    def test_a_non_empty_mount_folder_is_refused(self):
        if os.name == "nt":
            self.skipTest("Windows mounts a UNC share, not a folder")
        self.open_backup()
        open(os.path.join(self.mnt, "x"), "w").close()
        with mock.patch.object(bm, "load_fuse", return_value=StubFuse()):
            self.explorer._toggle_mount()
        self.assertEqual(self.dialogs[-1][0], "showerror")
        self.assertIn("empty", self.dialogs[-1][1][1])

    def test_another_backup_cannot_be_opened_while_mounted(self):
        self.open_backup()
        self.explorer._mount = object()      # pretend something is mounted
        self.addCleanup(setattr, self.explorer, "_mount", None)
        self.explorer.path_var.set(self.enc_dir)
        self.explorer.pass_var.set(fb.PASSPHRASE)
        self.explorer._decrypt()
        self.assertEqual(self.dialogs[-1][0], "showinfo")
        self.assertIn("Unmount", self.dialogs[-1][1][1])

    def test_an_unmount_done_outside_the_app_resets_the_button(self):
        ex = self.explorer
        mount = mock.Mock()
        ex._mount = mount
        ex.mount_btn.configure(text="Unmount Backup")
        ex._on_mount_stopped(mount)
        self.assertIsNone(ex._mount)
        self.assertEqual(ex.mount_btn.cget("text"), "Mount Backup")
        mount.stop.assert_called_once_with()

    def test_closing_the_window_unmounts_first(self):
        ex = self.explorer
        order = []
        mount = mock.Mock()
        mount.stop.side_effect = lambda: order.append("unmount")
        ex._mount = mount
        with mock.patch.object(ex.session, "close",
                               side_effect=lambda: order.append("close")), \
                mock.patch.object(self.root, "destroy"):
            ex._on_close()
        ex._mount = None
        self.assertEqual(order, ["unmount", "close"])

    @unittest.skipIf(os.name == "nt", "stubbed FUSE flow is for POSIX")
    def test_mount_and_unmount_with_a_stand_in_for_fuse(self):
        self.open_backup(encrypted=True)
        ex = self.explorer
        stub = StubFuse()
        with mock.patch.object(bm, "load_fuse", return_value=stub), \
                mock.patch.object(bm.subprocess, "run"):
            ex._toggle_mount()
            self.wait_for(lambda: ex._mount is not None, "mount")
            self.assertEqual(ex.mount_btn.cget("text"), "Unmount Backup")
            self.assertIn("Mounted", ex.status_var.get())
            self.assertEqual(stub.calls[0][0], self.mnt)
            ex._toggle_mount()
            self.wait_for(lambda: ex._mount is None, "unmount")
        self.assertEqual(ex.mount_btn.cget("text"), "Mount Backup")


@unittest.skipIf(_real_mount_unavailable(), _real_mount_unavailable() or "")
class RealWindowsMountThroughTheGuiTests(MountGuiCase):
    def check(self, encrypted):
        ex = self.explorer
        self.open_backup(encrypted)
        ex._toggle_mount()
        self.wait_for(lambda: ex._mount is not None, "mount", timeout=60)
        root = ex._mount.display_path
        self.assertTrue(root.startswith("\\\\ios-backup\\"), root)
        self.assertEqual(ex.mount_btn.cget("text"), "Unmount Backup")
        movie = os.path.join(root, fb.NOTES_DOMAIN, *fb.NOTES_MOV.split("/"))
        with open(movie, "rb") as handle:
            self.assertEqual(handle.read(),
                             fb.content_of(fb.NOTES_DOMAIN, fb.NOTES_MOV))

        ex._toggle_mount()
        self.wait_for(lambda: ex._mount is None, "unmount", timeout=60)
        self.assertFalse(os.path.exists(root))
        self.assertEqual(ex.mount_btn.cget("text"), "Mount Backup")

    def test_mount_an_encrypted_backup_as_a_unc_path(self):
        self.check(encrypted=True)

    def test_mount_an_unencrypted_backup_as_a_unc_path(self):
        self.check(encrypted=False)


if __name__ == "__main__":
    unittest.main()
