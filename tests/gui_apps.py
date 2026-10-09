# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A base class for tests of the app tabs in the real window (skipped
without a display)."""

import gc
import os
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

import ios_backup_explorer as app
from tests import fixture_backup as fb


class AppGuiCase(unittest.TestCase):
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
        self.tmp = tempfile.mkdtemp(prefix="ibe-appview-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dialogs = []
        for name in ("showerror", "showinfo", "showwarning"):
            patcher = mock.patch.object(
                app.messagebox, name,
                side_effect=lambda *a, _n=name, **k: self.dialogs.append(
                    (_n, a)))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(app.BackupExplorer, "BACKUP_PATHS", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.explorer = app.BackupExplorer(self.root)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        ex = self.explorer
        ex._cancel_timers()
        ex._clear_app_tabs()
        ex.apps.reset()
        ex.session.close()
        ex.session._executor.shutdown(wait=True)
        for child in self.root.winfo_children():
            child.destroy()
        # Drop the window and collect its garbage here, on the Tk thread:
        # left for later, the collector can run on a worker thread, which
        # may not finalise Tk variables.
        self.explorer = None
        gc.collect()

    def wait_for(self, condition, what, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}; status="
                  f"{self.explorer.status_var.get()!r}")

    def open_files(self, files, encrypted=False):
        """Make a backup holding *files* (``[(domain, path, bytes)]``) and
        open it in the window."""
        files = list(files) + [("HomeDomain", "Library/Other/readme.txt",
                                b"hello")]
        parent = tempfile.mkdtemp(dir=self.tmp)
        backup_dir, self.ids = fb.build_backup(parent, files=files,
                                               encrypted=encrypted)
        ex = self.explorer
        previous = ex.panel.index
        ex.path_var.set(backup_dir)
        if encrypted:
            ex.pass_var.set(fb.PASSPHRASE)
        ex._decrypt()
        self.wait_for(lambda: ex.panel.index is not None
                      and ex.panel.index is not previous,
                      "the new file index")
        return backup_dir

    def tab_titles(self):
        return [self.explorer.notebook.tab(t, "text")
                for t in self.explorer.notebook.tabs()]

    def panel_titled(self, title):
        for panel in self.explorer._app_panels:
            if self.explorer.notebook.tab(panel, "text") == title:
                return panel
        self.fail(f"no {title!r} tab among {self.tab_titles()}")

    def show_tab(self, title):
        panel = self.panel_titled(title)
        self.explorer.notebook.select(panel)
        self.root.update()
        return panel
