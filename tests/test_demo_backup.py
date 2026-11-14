# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The invented demo backup (tools/make_demo_backup.py) makes a backup that
the program opens, with every tab, and that holds only invented data."""

import getpass
import importlib.util
import io
import os
import plistlib
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
        self.assertEqual(len(titles), 22)

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

    def test_the_keychain_opens_with_the_demo_password_and_is_invented(self):
        from ios_apps import keychain as kn
        from ios_apps import keychain_crypto as kc
        with open(os.path.join(self.root, "Manifest.plist"), "rb") as handle:
            bag = plistlib.load(handle)["BackupKeyBag"]
        with self.assertRaises(kc.WrongBackupPassword):
            kc.unlock_keybag(bag, "not the password")
        keys = kc.unlock_keybag(bag, self.maker.keychain.PASSWORD)
        data = kn.read_plist(os.path.join(
            self.root, "KeychainDomain", "keychain-backup.plist"))
        items, unreadable = kn.open_items(data, keys)
        self.assertEqual(len(items), 11)
        self.assertEqual(sum(unreadable.values()), 3)
        for item in items:
            secret = item.attrs.get("v_Data")
            if kn.secret_text(secret) is not None:
                self.assertTrue(secret.startswith(b"demo"), secret)
            for field in ("srvr", "acct"):
                value = str(item.attrs.get(field, ""))
                if "@" in value:
                    self.assertRegex(value, r"@example\.(com|org|net)$")
            if "srvr" in item.attrs:
                self.assertRegex(item.attrs["srvr"],
                                 r"example\.(com|org|net)$")

    # -- what was added after 2.0.0 shows in the demo too -------------------

    def database(self, *parts):
        path = os.path.join(self.root, *parts)
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        return conn

    def test_some_messages_belong_to_no_conversation(self):
        conn = self.database("HomeDomain", "Library", "SMS", "sms.db")
        rows = conn.execute(
            "SELECT m.text, m.is_from_me, m.attributedBody FROM message m "
            "WHERE NOT EXISTS (SELECT 1 FROM chat_message_join j "
            "WHERE j.message_id = m.ROWID)").fetchall()
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(any(r[1] for r in rows), "one is the owner's own")
        self.assertTrue(any(not r[1] for r in rows), "one is received")

    def test_a_note_is_locked_and_opens_with_the_demo_note_password(self):
        from ios_apps import notes as nt
        conn = self.database("AppDomainGroup-group.com.apple.notes",
                             "NoteStore.sqlite")
        reader = nt.NotesReader(
            conn, lambda media, name: f"Media/{media}/{name}")
        notes = reader.notes()
        locked = [n for n in notes if n.locked]
        self.assertEqual([n.title for n in locked], ["Private"])
        self.assertTrue(locked[0].hint, "the dialog shows the hint")
        opened, still = reader.try_password(
            notes, "not the demo note password")
        self.assertEqual(opened, [])
        opened, still = reader.try_password(
            notes, self.maker.media.NOTE_PASSWORD)
        self.assertEqual([n.title for n in opened], ["Private"])
        self.assertTrue(opened[0].unlocked)
        self.assertIn("Dana", reader.load(opened[0]).text)

    def test_health_shows_what_version_2_2_added(self):
        from ios_apps import health as hl
        conn = self.database("HealthDomain", "Health", "healthdb_secure.sqlite")
        keys = [d.key for d in hl.HealthReader(conn).datasets()]
        for wanted in ("sleep_nights", "medications", "medication_doses",
                       "lab_results", "immunizations", "conditions",
                       "prescriptions", "clinical_documents", "awards",
                       "audiograms", "sleep_schedules", "events",
                       "friend_workouts", "friend_activity"):
            self.assertIn(wanted, keys)

    def test_the_clinical_documents_have_files_that_open(self):
        from ios_apps import aea
        from ios_apps import health as hl
        from ios_apps import health_records as hr
        conn = self.database("HealthDomain", "Health", "healthdb_secure.sqlite")
        sets = {d.key: d for d in hl.HealthReader(conn).datasets()}
        documents = sets["clinical_documents"].rows
        self.assertGreaterEqual(len(documents), 2)
        found = [f for row in documents for f in row.get("attached", [])]
        self.assertGreaterEqual(len(found), 2)
        for item in found:
            path = os.path.join(self.root, *item["path"].split("/"))
            self.assertTrue(os.path.isfile(path), item["path"])
            with open(path, "rb") as handle:
                text = aea.decrypt(handle.read(), item["key"])
            self.assertTrue(text.strip(), item["path"])
            self.assertNotIn(b"%PDF", text[:8])      # (invented text only)

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
        names = {os.path.basename(home), getpass.getuser(), login} - {
            "", "root"}          # ("root" is a word the demo may use)
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
