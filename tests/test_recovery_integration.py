# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The "Forgot password?" button on the main window: it only appears for an
encrypted backup, and the hash it builds is a real one, from the same
backup the rest of the suite already opens with a typed password (skipped
without a display)."""

import os
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

import ios_backup_explorer as app
from ios_apps import recovery
from tests import fixture_backup as fb

try:
    import iphone_backup_decrypt  # noqa: F401
except ImportError:  # pragma: no cover
    iphone_backup_decrypt = None


def _make_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    return root


@unittest.skipIf(iphone_backup_decrypt is None, "library not installed")
class ForgotPasswordButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _make_root()
        if cls.root is None:
            raise unittest.SkipTest("no display available")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-recovery-gui-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backup_dir, self.ids = fb.build_backup(self.tmp)
        self.plain_dir, _ = fb.build_backup(
            tempfile.mkdtemp(dir=self.tmp), encrypted=False)
        patcher = mock.patch.object(app.BackupExplorer, "BACKUP_PATHS", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.explorer = app.BackupExplorer(self.root)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.explorer._cancel_timers()
        self.explorer.session.close()
        self.explorer.session._executor.shutdown(wait=True)
        for child in self.root.winfo_children():
            child.destroy()
        self.explorer = None

    def wait_for(self, condition, what, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}")

    def test_disabled_until_an_encrypted_backup_is_chosen(self):
        ex = self.explorer
        self.assertTrue(ex.forgot_btn.instate(["disabled"]))
        ex.path_var.set(self.plain_dir)
        self.wait_for(lambda: ex._backup_kind == app.UNENCRYPTED,
                      "the unencrypted hint")
        self.assertTrue(ex.forgot_btn.instate(["disabled"]))
        ex.path_var.set(self.backup_dir)
        self.wait_for(lambda: ex._backup_kind == app.ENCRYPTED,
                      "the encrypted hint")
        self.assertTrue(ex.forgot_btn.instate(["!disabled"]))

    def test_the_hash_it_builds_is_real(self):
        # Not a GUI assertion: this is the same path _forgot_backup_password
        # takes, against the real fixture backup the rest of the suite
        # opens with fb.PASSPHRASE, with no password typed at all.
        manifest = os.path.join(self.backup_dir, "Manifest.plist")
        found = recovery.backup_hash_from_manifest(manifest)
        self.assertEqual(found.mode, "14800")
        self.assertTrue(found.text.startswith("$itunes_backup$*10*"))

    def test_using_a_recovered_password_fills_in_the_field_and_opens(self):
        ex = self.explorer
        ex.path_var.set(self.backup_dir)
        self.wait_for(lambda: ex._backup_kind == app.ENCRYPTED,
                      "the encrypted hint")
        ex._use_recovered_password(fb.PASSPHRASE)
        self.assertEqual(ex.pass_var.get(), fb.PASSPHRASE)
        ex._decrypt()
        self.wait_for(lambda: ex.backup_open, "backup to open")


if __name__ == "__main__":
    unittest.main()
