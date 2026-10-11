# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Keychain tab: how it gets its keys from each kind of backup, the
window (skipped without a display), and what it never writes to disk."""

import os
import plistlib
import shutil
import tempfile
import time
import unittest
from unittest import mock

import file_index as fi
import ios_backup_explorer as app
from ios_apps import keychain as kn
from ios_apps import keychain_crypto as kc
from ios_apps import keychain_view as kv
from tests import fixture_backup as fb
from tests import fixture_keychain as fk
from tests.gui_apps import AppGuiCase

KEYCHAIN = ("KeychainDomain", "keychain-backup.plist")
FILES = [(KEYCHAIN[0], KEYCHAIN[1], fk.keychain_plist())]


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-keychain-view-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.session = app.BackupSession()
        self.addCleanup(self._close)

    def _close(self):
        self.session.close()
        self.session._executor.shutdown(wait=True)

    def encrypted(self):
        folder, ids = fb.build_backup(
            tempfile.mkdtemp(dir=self.tmp), files=FILES,
            extra_class_keys=fk.CLASS_KEYS)
        return folder

    def open(self, folder, password=None):
        return self.session.open(folder, password).result(60)


class KeySourceTests(SessionCase):
    def test_an_encrypted_backup_hands_over_its_class_keys(self):
        self.open(self.encrypted(), fb.PASSPHRASE)
        mode, keys = self.session.keychain_source().result(60)
        self.assertEqual(mode, "keys")
        for clas, key in fk.CLASS_KEYS.items():
            self.assertEqual(keys.key(clas), key)
        self.assertIsNone(keys.key(10))

    def test_those_keys_open_the_keychain_of_that_backup(self):
        self.open(self.encrypted(), fb.PASSPHRASE)
        _mode, keys = self.session.keychain_source().result(60)
        items, unreadable = kn.open_items(
            kn.read_plist(fk.keychain_plist()), keys)
        self.assertEqual(len(items), 8)
        self.assertEqual(sum(unreadable.values()), 2)

    def test_an_unencrypted_backup_says_why_not(self):
        folder, _ = fb.build_backup(tempfile.mkdtemp(dir=self.tmp),
                                    files=FILES, encrypted=False)
        self.open(folder)
        mode, why = self.session.keychain_source().result(60)
        self.assertEqual(mode, "none")
        self.assertIn("not encrypted", why)

    def extracted(self, with_key_bag):
        root = os.path.join(self.tmp, "Extracted")
        for domain, path, data in FILES:
            target = os.path.join(root, domain, *path.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(data)
        if with_key_bag:
            with open(os.path.join(root, "Manifest.plist"), "wb") as handle:
                plistlib.dump({"BackupKeyBag": fk.keybag_blob()}, handle)
        return root

    def test_an_extracted_folder_without_a_key_bag(self):
        self.assertEqual(app.detect_backup(self.extracted(False)),
                         app.EXTRACTED)
        self.open(self.extracted(False))
        mode, why = self.session.keychain_source().result(60)
        self.assertEqual(mode, "none")
        self.assertIn("key bag", why)

    def test_an_extracted_folder_that_kept_the_key_bag(self):
        root = self.extracted(True)
        self.assertEqual(app.detect_backup(root), app.EXTRACTED)
        self.open(root)
        mode, bag = self.session.keychain_source().result(60)
        self.assertEqual(mode, "keybag")
        keys = kc.unlock_keybag(bag, fk.PASSWORD)
        self.assertEqual(keys.key(6), fk.CLASS_KEYS[6])

    def test_a_manifest_that_is_not_a_key_bag_is_still_refused(self):
        root = self.extracted(False)
        with open(os.path.join(root, "Manifest.plist"), "wb") as handle:
            handle.write(b"x")
        with self.assertRaises(app.BackupFormatError):
            app.detect_backup(root)
        with open(os.path.join(root, "Manifest.plist"), "wb") as handle:
            plistlib.dump({"Something": "else"}, handle)
        with self.assertRaises(app.BackupFormatError):
            app.detect_backup(root)


class ExtractionKeepsTheKeychainTests(SessionCase):
    def test_extracting_everything_keeps_the_key_bag(self):
        self.open(self.encrypted(), fb.PASSPHRASE)
        out = os.path.join(self.tmp, "all")
        report = self.session.extract_all(out).result(60)
        self.assertEqual(report.errors, [])
        self.assertTrue(report.key_bag_kept)
        with open(os.path.join(out, "Manifest.plist"), "rb") as handle:
            kept = plistlib.load(handle)
        self.assertEqual(set(kept), {"BackupKeyBag", "IsEncrypted", "Note"})
        keys = kc.unlock_keybag(bytes(kept["BackupKeyBag"]), fb.PASSPHRASE)
        self.assertEqual(keys.key(7), fk.CLASS_KEYS[7])

    def test_the_extraction_can_be_opened_again_for_its_keychain(self):
        self.open(self.encrypted(), fb.PASSPHRASE)
        out = os.path.join(self.tmp, "all")
        self.session.extract_all(out).result(60)
        second = app.BackupSession()
        self.addCleanup(lambda: (second.close(),
                                 second._executor.shutdown(wait=True)))
        second.open(out).result(60)
        mode, bag = second.keychain_source().result(60)
        self.assertEqual(mode, "keybag")
        keys = kc.unlock_keybag(bag, fb.PASSPHRASE)
        data = kn.read_plist(os.path.join(out, *KEYCHAIN[0:1],
                                          KEYCHAIN[1]))
        items, _ = kn.open_items(data, keys)
        self.assertEqual(len(items), 8)

    def test_an_unencrypted_extraction_has_no_key_bag_to_keep(self):
        folder, _ = fb.build_backup(tempfile.mkdtemp(dir=self.tmp),
                                    files=FILES, encrypted=False)
        self.open(folder)
        out = os.path.join(self.tmp, "all")
        report = self.session.extract_all(out).result(60)
        self.assertFalse(report.key_bag_kept)
        self.assertFalse(os.path.exists(os.path.join(out, "Manifest.plist")))

    def test_the_kept_file_holds_no_password_and_no_key(self):
        self.open(self.encrypted(), fb.PASSPHRASE)
        out = os.path.join(self.tmp, "all")
        self.session.extract_all(out).result(60)
        with open(os.path.join(out, "Manifest.plist"), "rb") as handle:
            raw = handle.read()
        self.assertNotIn(fb.PASSPHRASE.encode(), raw)
        for key in fk.CLASS_KEYS.values():
            self.assertNotIn(key, raw)


class KeychainGuiCase(AppGuiCase):
    def setUp(self):
        super().setUp()
        self.asked = []
        self.answers = []
        patcher = mock.patch.object(kv, "ask_password", side_effect=self.ask)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, parent, title, message, hint=""):
        self.asked.append(message)
        return self.answers.pop(0) if self.answers else None

    def open_encrypted(self):
        self.open_files(FILES, encrypted=True,
                        extra_class_keys=fk.CLASS_KEYS)

    def open_folder(self, with_key_bag=True):
        root = os.path.join(tempfile.mkdtemp(dir=self.tmp), "Extracted")
        for domain, path, data in FILES:
            target = os.path.join(root, domain, *path.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(data)
        if with_key_bag:
            with open(os.path.join(root, "Manifest.plist"), "wb") as handle:
                plistlib.dump({"BackupKeyBag": fk.keybag_blob()}, handle)
        ex = self.explorer
        previous = ex.panel.index
        ex.path_var.set(root)
        ex._decrypt()
        self.wait_for(lambda: ex.panel.index is not None
                      and ex.panel.index is not previous, "the folder")

    @property
    def tab(self):
        return self.panel_titled("Keychain")

    def show(self):
        tab = self.show_tab("Keychain")
        self.wait_for(lambda: tab.datasets, "the keychain")
        return tab

    def pump(self, seconds=0.5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.01)


class EncryptedBackupTests(KeychainGuiCase):
    def test_the_tab_opens_without_asking_for_anything(self):
        self.open_encrypted()
        tab = self.show()
        self.assertEqual(self.asked, [])
        self.assertEqual(list(tab.datasets), ["passwords", "certificates",
                                              "keys", "unreadable"])
        self.assertEqual(len(tab.datasets["passwords"].rows), 5)

    def test_it_does_not_ask_once_it_has_the_keys(self):
        self.open_encrypted()
        tab = self.show()
        tab.ask_for_password()
        self.assertEqual(self.asked, [])

    def test_the_passwords_are_shown_in_the_clear(self):
        self.open_encrypted()
        tab = self.show()
        tab.choose_dataset("passwords")
        self.pump()
        shown = [tab.tree.item(i, "values") for i in tab.tree.get_children()]
        flat = " ".join(" ".join(map(str, v)) for v in shown)
        self.assertIn("espresso2024", flat)
        self.assertIn("mail password", flat)

    def test_the_tab_is_only_there_when_the_backup_has_a_keychain(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")],
                        encrypted=True)
        self.assertNotIn("Keychain", self.tab_titles())
        self.open_encrypted()
        self.assertIn("Keychain", self.tab_titles())

    def test_nothing_readable_is_written_to_the_working_folder(self):
        self.open_encrypted()
        self.show()
        self.pump()
        found = []
        for folder, _dirs, files in os.walk(self.explorer.apps.workspace.path
                                            if hasattr(
                                                self.explorer.apps.workspace,
                                                "path") else self.tmp):
            for name in files:
                with open(os.path.join(folder, name), "rb") as handle:
                    data = handle.read()
                for secret in (b"espresso2024", b"mail password",
                               b"s3cret!"):
                    if secret in data:
                        found.append((name, secret))
        self.assertEqual(found, [])

    def test_exporting_asks_first_and_warns(self):
        self.open_encrypted()
        tab = self.show()
        tab.choose_dataset("passwords")
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(kv.messagebox, "askokcancel",
                               return_value=False) as ask, \
                mock.patch("ios_apps.records_view.ask_export",
                           return_value=("csv", "all", out)) as dialog:
            tab.export()
        self.assertTrue(ask.called)
        self.assertIn("readable form", ask.call_args[0][1])
        dialog.assert_not_called()
        self.assertFalse(os.path.exists(out))

    def test_exporting_after_the_warning(self):
        self.open_encrypted()
        tab = self.show()
        tab.choose_dataset("passwords")
        out = os.path.join(self.tmp, "export")
        before = len(self.dialogs)
        with mock.patch.object(kv.messagebox, "askokcancel",
                               return_value=True), \
                mock.patch("ios_apps.records_view.ask_export",
                           return_value=("csv", "all", out)):
            tab.export()
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        with open(os.path.join(out, os.listdir(out)[0]),
                  encoding="utf-8-sig") as handle:
            text = handle.read()
        self.assertIn("espresso2024", text)

    def test_the_table_of_what_cannot_be_opened_needs_no_warning(self):
        self.open_encrypted()
        tab = self.show()
        tab.choose_dataset("unreadable")
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(kv.messagebox, "askokcancel") as ask, \
                mock.patch("ios_apps.records_view.ask_export",
                           return_value=("csv", "all", out)):
            tab.export()
        ask.assert_not_called()


class ExtractedFolderTests(KeychainGuiCase):
    def test_the_backup_password_is_asked_for(self):
        self.open_folder()
        self.answers = [fk.PASSWORD]
        tab = self.show()
        self.assertEqual(len(self.asked), 1)
        self.assertIn("backup password", self.asked[0])
        self.assertEqual(len(tab.datasets["passwords"].rows), 5)
        self.assertEqual(tab.password_button.winfo_manager(), "")

    def test_a_wrong_password_asks_again(self):
        self.open_folder()
        self.answers = ["wrong", fk.PASSWORD]
        self.show()
        self.assertEqual(len(self.asked), 2)
        self.assertTrue([d for d in self.dialogs if d[0] == "showwarning"])

    def test_the_password_is_not_kept(self):
        self.open_folder()
        self.answers = [fk.PASSWORD]
        tab = self.show()
        self.pump()
        for value in vars(tab).values():
            self.assertNotEqual(value, fk.PASSWORD)

    def test_cancelling_leaves_a_button_to_try_again(self):
        self.open_folder()
        self.answers = [None]
        tab = self.show_tab("Keychain")
        self.wait_for(lambda: self.asked, "the question")
        self.pump()
        self.assertFalse(tab.datasets)
        self.assertIn("stays closed", tab.state_var.get())
        self.assertEqual(tab.password_button.winfo_manager(), "pack")
        self.answers = [fk.PASSWORD]
        tab.password_button.invoke()
        self.wait_for(lambda: tab.datasets, "the keychain")

    def test_a_folder_without_a_key_bag_says_so(self):
        self.open_folder(with_key_bag=False)
        tab = self.show_tab("Keychain")
        self.wait_for(lambda: "key bag" in tab.state_var.get(), "the message")
        self.assertEqual(self.asked, [])
        self.assertFalse(tab.datasets)


class UnencryptedBackupTests(KeychainGuiCase):
    def test_the_tab_explains(self):
        self.open_files(FILES, encrypted=False)
        tab = self.show_tab("Keychain")
        self.wait_for(lambda: "not encrypted" in tab.state_var.get(),
                      "the message")
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
