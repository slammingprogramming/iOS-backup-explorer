# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The invented demo backup (tools/make_demo_backup.py) makes a backup that
the program opens, with every tab, and that holds only invented data."""

import getpass
import importlib.util
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import ios_backup_explorer as app
from file_index import FileIndex
from ios_apps import registry

ROOT = Path(__file__).resolve().parent.parent

try:
    import PIL                                      # noqa: F401
except ImportError:                                  # the photos need it
    PIL = None


def load_maker():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        spec = importlib.util.spec_from_file_location(
            "make_demo_backup", ROOT / "tools" / "make_demo_backup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ROOT / "tools"))


@unittest.skipIf(PIL is None, "the demo's photos need Pillow")
class DemoBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="ibe-demo-test-")
        cls.root = os.path.join(cls.folder, "Demo iPhone Backup")
        cls.maker = load_maker()
        cls.count = cls.maker.make(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_it_is_an_extracted_backup(self):
        self.assertEqual(app.detect_backup(self.root), app.EXTRACTED)
        self.assertGreater(self.count, 250)

    def test_every_tab_has_its_data(self):
        session = app.BackupSession()
        self.addCleanup(lambda: (session.close(),
                                 session._executor.shutdown(wait=True)))
        session.open(self.root).result(60)
        index = FileIndex(session.scan().result(60))
        titles = [e.title for e in registry.available_apps(index)]
        self.assertEqual(sorted(titles), sorted(e.title
                                                for e in registry.APPS))
        self.assertEqual(len(titles), 21)

    def test_the_phone_numbers_are_invented(self):
        # every number in the address book is in area code 555, which does
        # not exist, so none can be a real person's
        path = os.path.join(self.root, "HomeDomain", "Library", "AddressBook",
                            "AddressBook.sqlitedb")
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        numbers = [v for (v,) in conn.execute(
            "SELECT value FROM ABMultiValue WHERE property = 3")]
        self.assertTrue(numbers)
        for number in numbers:
            digits = re.sub(r"\D", "", number)[-10:]
            self.assertRegex(digits, r"^555010\d{4}$", number)

    def test_the_addresses_are_not_real(self):
        path = os.path.join(self.root, "HomeDomain", "Library", "AddressBook",
                            "AddressBook.sqlitedb")
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        for (email,) in conn.execute(
                "SELECT value FROM ABMultiValue WHERE property = 4"):
            self.assertRegex(email, r"@example\.(com|org|net)$")

    def test_nothing_in_it_names_the_computer_it_was_made_on(self):
        home = os.path.expanduser("~")
        try:
            login = os.getlogin()
        except (AttributeError, OSError):       # no terminal (CI)
            login = ""
        names = {os.path.basename(home), getpass.getuser(), login} - {""}
        for folder, _dirs, files in os.walk(self.root):
            for name in files:
                data = (Path(folder) / name).read_bytes()
                for who in names:
                    if len(who) >= 4:
                        self.assertNotIn(who.encode().lower(), data.lower(),
                                         f"{name} mentions {who!r}")

    def test_a_folder_that_is_not_empty_is_refused(self):
        with redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            self.maker.main([self.root])

    def test_making_it_again_gives_the_same_files(self):
        other = os.path.join(self.folder, "Again")
        self.maker.make(other)

        def names(root):
            return sorted(os.path.relpath(os.path.join(f, n), root)
                          for f, _d, ns in os.walk(root) for n in ns)

        self.assertEqual(names(other), names(self.root))


if __name__ == "__main__":
    unittest.main()
