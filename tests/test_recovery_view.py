# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Tests for the "Forgot password?" dialog (skipped without a display).
Uses the stand-ins in ``fixture_recovery`` the same way ``test_recovery``
does, so these exercise the real subprocess path, not a mock of it."""

import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

from ios_apps import recovery as rec
from ios_apps import recovery_view as rv
from tests import fixture_recovery as fr


def all_texts(widget):
    """Every "text" option under *widget*, recursively (buttons, labels)."""
    found = []
    if "text" in widget.keys():
        found.append(widget.cget("text"))
    for child in widget.winfo_children():
        found.extend(all_texts(child))
    return found


def display_available():
    try:
        probe = tk.Tk()
    except tk.TclError:
        return False
    probe.destroy()
    return True


@unittest.skipUnless(display_available(), "no display available")
class DialogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-recovery-view-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.found = []
        self.dialog = None
        self.shown = []
        for name in ("showerror", "showinfo", "showwarning"):
            patcher = mock.patch.object(
                rv.messagebox, name,
                side_effect=lambda *a, _n=name, **k: self.shown.append(
                    (_n, a)))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._close)

    def _close(self):
        if self.dialog is not None:
            self.dialog._on_close()

    def open(self, hash_factory=None, official=("Ask Apple.",),
             workaround=("Check Keychain Access.",)):
        self.dialog = rv.ForgotPasswordDialog(
            self.root, "this backup", official, workaround,
            hash_factory or (lambda: rec.RecoveryHash(
                "$itunes_backup$*x", "14800", "backup")),
            self.found.append)
        return self.dialog

    def wait_for(self, condition, what, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}")


class WithoutHashcatTests(DialogCase):
    def test_hashcat_not_found_offers_to_locate_it(self):
        with mock.patch.object(rec, "locate_hashcat", return_value=None):
            dialog = self.open()
        self.assertTrue(any("not found" in t
                            for t in all_texts(dialog._tool_frame)))
        self.assertFalse(hasattr(dialog, "_start_button"))


class WithFakeHashcatTests(DialogCase):
    def setUp(self):
        super().setUp()
        self.hashcat = [sys.executable, fr.fake_hashcat(self.tmp)]

    def open(self, **kw):
        dialog = super().open(**kw)
        dialog._hashcat_path = self.hashcat
        for child in dialog._run_frame.winfo_children():
            child.destroy()
        dialog._build_run_controls(dialog._run_frame)
        return dialog

    def test_a_missing_wordlist_is_refused(self):
        dialog = self.open()
        dialog._wordlist_var.set(os.path.join(self.tmp, "nope.txt"))
        dialog._attack_var.set("wordlist")
        dialog._start()
        self.assertIsNone(dialog._run)

    def test_a_successful_crack_can_be_used(self):
        wordlist = os.path.join(self.tmp, "words.txt")
        with open(wordlist, "w", encoding="utf-8") as handle:
            handle.write("nope\nFOUND-ME\n")
        dialog = self.open(hash_factory=lambda: rec.RecoveryHash(
            "$itunes_backup$*FOUND-ME*x", "14800", "backup"))
        dialog._wordlist_var.set(wordlist)
        dialog._attack_var.set("wordlist")
        dialog._start_button.invoke()
        self.wait_for(lambda: dialog._found_var.get() == "FOUND-ME",
                      "the password to be found")
        dialog._use_found()
        self.assertEqual(self.found, ["FOUND-ME"])

    def test_an_unavailable_hash_is_reported_before_starting(self):
        def unavailable():
            raise rec.RecoveryUnavailable("not this backup")
        dialog = self.open(hash_factory=unavailable)
        dialog._wordlist_var.set(__file__)      # any existing file
        dialog._start()
        self.assertIsNone(dialog._run)

    def test_the_stop_button_stops_the_run(self):
        # The run's own stop/cancel behaviour (the process actually ending,
        # "Stopped." being reported) is tested directly, with time to spare
        # for it to really be in progress, in test_recovery.HashcatRunTests.
        # This only checks the button is wired to it.
        dialog = self.open()
        stub = mock.Mock()
        dialog._run = stub
        dialog._stop_button.configure(state="normal")
        dialog._stop_button.invoke()
        stub.stop.assert_called_once_with()


class CuppDialogTests(DialogCase):
    def test_building_a_wordlist_fills_in_the_wordlist_field(self):
        dialog = self.open()
        cupp_path = fr.fake_cupp(self.tmp)
        cupp = rv.CuppDialog(dialog, cupp_path, lambda p: None,
                             dialog._on_wordlist_built)
        cupp._vars["first_name"].set("Robin")
        cupp._vars["pet_name"].set("Max")
        cupp._build_button.invoke()
        self.wait_for(lambda: dialog._wordlist_var.get(), "the wordlist")
        with open(dialog._wordlist_var.get(), encoding="utf-8") as handle:
            words = handle.read().splitlines()
        self.assertEqual(words, ["Robin", "Max"])

    def test_an_incomplete_profile_is_refused(self):
        dialog = self.open()
        cupp_path = fr.fake_cupp(self.tmp)
        cupp = rv.CuppDialog(dialog, cupp_path, lambda p: None,
                             dialog._on_wordlist_built)
        cupp._build_button.invoke()
        self.assertEqual(dialog._wordlist_var.get(), "")
        cupp._on_close()


if __name__ == "__main__":
    unittest.main()
