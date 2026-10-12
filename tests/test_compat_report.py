# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""tools/compat_report.py: the report of which tabs a backup gives. It must
carry counts and the program's own messages, never what the backup holds."""

import importlib.util
import io
import os
import plistlib
import shutil
import tempfile
import tkinter as tk
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests import fixture_health as fh
from tests import fixture_notes as fn

ROOT = Path(__file__).resolve().parent.parent


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "compat_report", ROOT / "tools" / "compat_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def display_available():
    try:
        probe = tk.Tk()
    except tk.TclError:
        return False
    probe.destroy()
    return True


def extracted_folder(parent, with_info=True):
    root = os.path.join(parent, "Extracted")
    files = fn.backup_files(include_media=False) + fh.backup_files()
    for domain, path, data in files:
        target = os.path.join(root, domain, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    if with_info:
        with open(os.path.join(root, "Info.plist"), "wb") as handle:
            plistlib.dump({"Product Version": "17.4", "Product Type":
                           "iPhone15,2", "Device Name": "SECRET NAME",
                           "Serial Number": "SECRETSERIAL"}, handle)
    return root


class FactsTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.mkdtemp(prefix="ibe-compat-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_only_the_version_and_the_kind_of_device_are_read(self):
        root = extracted_folder(self.tmp)
        facts = self.tool.backup_facts(root)
        self.assertEqual(facts, {"ios": "17.4", "device": "iPhone15,2",
                                 "encrypted": None})
        self.assertNotIn("SECRET", str(facts))

    def test_a_folder_with_no_plists(self):
        facts = self.tool.backup_facts(self.tmp)
        self.assertEqual(facts, {"ios": None, "device": None,
                                 "encrypted": None})

    def test_the_manifest_says_whether_it_is_encrypted(self):
        with open(os.path.join(self.tmp, "Manifest.plist"), "wb") as handle:
            plistlib.dump({"IsEncrypted": True}, handle)
        self.assertTrue(self.tool.backup_facts(self.tmp)["encrypted"])

    def test_damaged_plists_are_ignored(self):
        for name in ("Info.plist", "Manifest.plist"):
            with open(os.path.join(self.tmp, name), "wb") as handle:
                handle.write(b"not a plist")
        self.assertEqual(self.tool.backup_facts(self.tmp)["ios"], None)


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_a_report_becomes_a_table(self):
        text = self.tool.markdown({
            "opened": True, "ios": "16.7", "device": "iPhone10,6",
            "encrypted": True, "seconds": 3.5, "tabs": [
                {"tab": "Notes", "problem": False, "state": "3 notes",
                 "tables": {}},
                {"tab": "Health", "problem": True, "state": "Could not x",
                 "tables": {"sleep": 4}}]})
        self.assertIn("iOS 16.7 (iPhone10,6), encrypted", text)
        self.assertIn("| Notes | yes | 3 notes |  |", text)
        self.assertIn("| Health | no | Could not x | sleep 4 |", text)
        self.assertIn("2 tabs in 3.5 s", text)

    def test_a_backup_that_did_not_open(self):
        self.assertIn("did not open: bad password", self.tool.markdown(
            {"opened": False, "reason": "bad password"}))


@unittest.skipUnless(display_available(), "needs a display")
class RunTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.mkdtemp(prefix="ibe-compat-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_report_of_an_extracted_backup(self):
        root = extracted_folder(self.tmp)
        report = self.tool.run(root, patience=60, say=lambda *a: None)
        self.assertTrue(report["opened"])
        self.assertEqual((report["ios"], report["device"]),
                         ("17.4", "iPhone15,2"))
        tabs = {t["tab"]: t for t in report["tabs"]}
        self.assertIn("Notes", tabs)
        self.assertIn("Health", tabs)
        self.assertFalse(any(t["problem"] for t in report["tabs"]), tabs)
        self.assertIn("sleep", tabs["Health"]["tables"])

    def test_it_says_nothing_of_what_the_backup_holds(self):
        root = extracted_folder(self.tmp)
        report = self.tool.run(root, patience=60, say=lambda *a: None)
        text = self.tool.markdown(report) + str(report)
        for secret in ("SECRET", "Shopping list", "Pancakes", "Sam's iPhone",
                       "Alex Example", self.tmp):
            self.assertNotIn(secret, text)

    def test_the_version_can_be_given(self):
        root = extracted_folder(self.tmp, with_info=False)
        report = self.tool.run(root, ios="14.8", patience=60,
                               say=lambda *a: None)
        self.assertEqual(report["ios"], "14.8")

    def test_a_folder_that_is_not_a_backup(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.tool.main([empty])
        self.assertEqual(code, 1)
        self.assertIn("did not open", out.getvalue())


if __name__ == "__main__":
    unittest.main()
