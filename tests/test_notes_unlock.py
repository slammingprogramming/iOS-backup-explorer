# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""``PasswordDialog``'s optional "Forgot password?" button (skipped
without a display)."""

import tkinter as tk
import unittest

from ios_apps import notes_unlock as nu
from ios_apps import recovery as rec


def display_available():
    try:
        probe = tk.Tk()
    except tk.TclError:
        return False
    probe.destroy()
    return True


def all_texts(widget):
    """Every "text" option under *widget*, recursively (buttons, labels)."""
    found = []
    if "text" in widget.keys():
        found.append(widget.cget("text"))
    for child in widget.winfo_children():
        found.extend(all_texts(child))
    return found


@unittest.skipUnless(display_available(), "no display available")
class PasswordDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.dialog = None
        self.addCleanup(self._close)

    def _close(self):
        if self.dialog is not None:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass      # already gone (a found password closes itself)

    def test_no_button_without_recovery(self):
        self.dialog = nu.PasswordDialog(self.root, "Title", "Message")
        self.assertNotIn("Forgot password?", all_texts(self.dialog))

    def test_the_button_appears_and_opens_the_dialog(self):
        recovery = ("this backup", rec.BACKUP_OFFICIAL, rec.BACKUP_WORKAROUND,
                   lambda: rec.RecoveryHash("$x", "14800", "backup"))
        self.dialog = nu.PasswordDialog(self.root, "Title", "Message",
                                        recovery=recovery)
        self.assertIn("Forgot password?", all_texts(self.dialog))

    def test_a_password_found_fills_the_entry_and_submits(self):
        recovery = ("this backup", rec.BACKUP_OFFICIAL, rec.BACKUP_WORKAROUND,
                   lambda: rec.RecoveryHash("$x", "14800", "backup"))
        self.dialog = nu.PasswordDialog(self.root, "Title", "Message",
                                        recovery=recovery)
        self.dialog._use_recovered_password("the-password")
        self.assertEqual(self.dialog.result, "the-password")


if __name__ == "__main__":
    unittest.main()
