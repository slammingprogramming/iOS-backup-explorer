# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""GUI behaviour for unencrypted backups (skipped without a display)."""

import os
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

import ios_backup_explorer as app
from tests import fixture_backup as fb


class UnencryptedGuiTests(unittest.TestCase):
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
        self.tmp = tempfile.mkdtemp(prefix="ibe-gui-plain-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plain_dir, _ = fb.build_backup(
            tempfile.mkdtemp(dir=self.tmp), encrypted=False)
        self.enc_dir, _ = fb.build_backup(tempfile.mkdtemp(dir=self.tmp))
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)

        self.dialogs = []
        for name in ("showerror", "showinfo", "showwarning"):
            patcher = mock.patch.object(
                app.messagebox, name,
                side_effect=lambda *a, _n=name, **k: self.dialogs.append(
                    (_n, a)))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(app.filedialog, "askdirectory",
                                    return_value=self.out)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.explorer = app.BackupExplorer(self.root)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.explorer._cancel_timers()
        self.explorer.session.close()
        self.explorer.session._executor.shutdown(wait=True)

    def wait_for(self, condition, what, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}; status="
                  f"{self.explorer.status_var.get()!r}")

    def password_entry_disabled(self):
        return self.explorer.pass_entry.instate(["disabled"])

    def test_choosing_a_folder_adapts_the_form(self):
        ex = self.explorer
        ex.path_var.set(self.plain_dir)
        self.wait_for(lambda: "not encrypted" in ex.status_var.get(),
                      "unencrypted hint")
        self.assertEqual(ex.decrypt_btn.cget("text"), "Open Backup")
        self.assertTrue(self.password_entry_disabled())

        ex.path_var.set(self.enc_dir)
        self.wait_for(lambda: "is encrypted" in ex.status_var.get(),
                      "encrypted hint")
        self.assertEqual(ex.decrypt_btn.cget("text"), "Decrypt & Open")
        self.assertFalse(self.password_entry_disabled())

        ex.path_var.set(self.plain_dir)
        self.wait_for(self.password_entry_disabled, "entry disabled again")

    def test_open_browse_and_extract_without_a_password(self):
        ex = self.explorer
        ex.path_var.set(self.plain_dir)
        ex._decrypt()  # no password typed
        self.wait_for(lambda: ex.backup_open, "backup to open")
        self.assertEqual(self.dialogs, [])
        self.assertTrue(ex.status_var.get().startswith("Opened!"),
                        ex.status_var.get())

        ex.domain_tree.selection_set("__ALL__")
        self.wait_for(lambda: len(ex.file_tree.get_children())
                      == len(fb.DEFAULT_FILES), "file list")
        ex.search_var.set("voice_memo_01")
        self.wait_for(lambda: len(ex.file_tree.get_children()) == 1,
                      "search result")
        ex.file_tree.selection_set(ex.file_tree.get_children()[0])
        ex._extract_selected()
        self.wait_for(lambda: not ex._extracting and self.dialogs,
                      "extraction")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])

        key = (fb.NOTES_DOMAIN, fb.NOTES_MOV)
        path = app.fs_path(app.build_output_path(self.out, *key))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), fb.content_of(*key))

    def test_typing_a_password_for_an_unencrypted_backup_is_harmless(self):
        ex = self.explorer
        ex.path_var.set(self.plain_dir)
        ex.pass_var.set("left over from another backup")
        with mock.patch.object(ex.session, "open",
                               wraps=ex.session.open) as opened:
            ex._decrypt()
        # The stray password must not even reach the session.
        opened.assert_called_once_with(self.plain_dir, None)
        self.wait_for(lambda: ex.backup_open, "backup to open")
        self.assertEqual(ex.pass_var.get(), "")

    def test_encrypted_backup_without_a_password_asks_for_one(self):
        ex = self.explorer
        ex.path_var.set(self.enc_dir)
        ex._decrypt()
        self.assertEqual(self.dialogs[0][0], "showerror")
        self.assertIn("encrypted", self.dialogs[0][1][1])
        self.assertFalse(ex.backup_open)

    def test_a_folder_that_is_not_a_backup_is_explained(self):
        ex = self.explorer
        ex.path_var.set(tempfile.mkdtemp(dir=self.tmp))
        ex._decrypt()
        self.assertEqual(self.dialogs[0][1][0], "Not a usable backup")
        self.assertIn("Manifest.plist", self.dialogs[0][1][1])

    def test_encrypted_flow_still_works(self):
        ex = self.explorer
        ex.path_var.set(self.enc_dir)
        ex.pass_var.set(fb.PASSPHRASE)
        ex._decrypt()
        self.wait_for(lambda: ex.backup_open, "backup to open")
        self.assertTrue(ex.status_var.get().startswith("Decrypted!"))


if __name__ == "__main__":
    unittest.main()
