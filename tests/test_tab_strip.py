# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The row of tabs shrinks to fit when there are many of them."""

import unittest
from tkinter import ttk
from unittest import mock

from tests import fixture_small_tabs as fx
from tests import fixture_voicemail as fv
from tests.gui_apps import AppGuiCase


def padding():
    return [int(p) for p in str(ttk.Style().lookup(
        "TNotebook.Tab", "padding")).split()][0]


class TabStripTests(AppGuiCase):
    def setUp(self):
        super().setUp()
        self.open_files(fx.files() + fv.backup_files())
        self.assertGreaterEqual(len(self.tab_titles()), 6)

    def fit(self, width):
        with mock.patch.object(self.explorer.notebook, "winfo_width",
                               lambda: width):
            self.explorer._fit_tabs()

    def test_a_wide_window_keeps_the_roomy_tabs(self):
        self.fit(5000)
        self.assertEqual(padding(), 16)

    def test_a_narrow_window_makes_the_tabs_tighter(self):
        self.fit(5000)
        roomy = padding()
        self.fit(330)
        self.assertLess(padding(), roomy)
        self.fit(5000)
        self.assertEqual(padding(), roomy)               # and back again

    def test_a_window_not_yet_shown_changes_nothing(self):
        self.fit(5000)
        self.fit(1)
        self.assertEqual(padding(), 16)

    def test_fitting_is_scheduled_once(self):
        self.explorer._fit_job = None
        self.explorer._schedule_fit_tabs()
        job = self.explorer._fit_job
        self.assertIsNotNone(job)
        self.explorer._schedule_fit_tabs()
        self.assertEqual(self.explorer._fit_job, job)
        self.root.update()
        self.assertIsNone(self.explorer._fit_job)


if __name__ == "__main__":
    unittest.main()
