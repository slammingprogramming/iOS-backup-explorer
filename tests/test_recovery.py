# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Tests for ``ios_apps.recovery``: the hash formats it builds, and its
subprocess plumbing against the stand-ins in ``fixture_recovery`` (neither
real hashcat nor real CUPP is something a test machine can be assumed to
have; see that module's docstring)."""

import os
import plistlib
import shutil
import struct
import sys
import tempfile
import threading
import unittest

from ios_apps import keychain_crypto as kc
from ios_apps import notes_crypto as nc
from ios_apps import recovery as rec
from tests import fixture_keychain as fk
from tests import fixture_recovery as fr


def _entry(tag, value):
    if isinstance(value, int):
        value = struct.pack(">L", value)
    return tag + struct.pack(">L", len(value)) + value


class ToolLocationTests(unittest.TestCase):
    def test_an_explicit_path_that_does_not_exist_is_not_found(self):
        self.assertIsNone(rec.find_tool("hashcat", explicit="/nope/nope"))

    def test_an_explicit_path_that_exists_is_used_as_is(self):
        with tempfile.NamedTemporaryFile(suffix=".exe") as handle:
            self.assertEqual(rec.find_tool("x", explicit=handle.name),
                             os.path.abspath(handle.name))

    def test_nothing_on_a_machine_with_neither_tool(self):
        # Not a claim that hashcat/CUPP are absent from every test machine,
        # only that an impossible name finds nothing.
        self.assertIsNone(rec.locate_hashcat(
            explicit="/definitely/not/a/real/path/hashcat"))
        self.assertIsNone(rec.locate_cupp(
            explicit="/definitely/not/a/real/path/cupp.py"))


class BackupHashTests(unittest.TestCase):
    def test_the_format_and_fields(self):
        blob = fk.keybag_blob(dpic=1000, iterations=20)
        found = rec.backup_hash_from_keybag(blob)
        self.assertEqual(found.mode, "14800")
        self.assertEqual(found.kind, "backup")
        prefix, ver, wpky, iterations, salt, dpic, dpsl = \
            found.text.split("*")
        self.assertEqual(prefix, "$itunes_backup$")
        self.assertEqual(ver, "10")
        self.assertEqual(iterations, "20")
        self.assertEqual(dpic, "1000")
        self.assertEqual(salt, (b"S" * 20).hex())
        self.assertEqual(dpsl, (b"D" * 20).hex())
        bytes.fromhex(wpky)              # does not raise: it is hex

    def test_a_pre_ios_10_key_bag_is_not_available(self):
        # DPIC/DPSL are missing: this program's own unlock_keybag could
        # never check a found password against this backup either.
        blob = (_entry(b"UUID", b"U" * 16) + _entry(b"WRAP", 1)
               + _entry(b"SALT", b"S" * 20) + _entry(b"ITER", 20))
        with self.assertRaises(rec.RecoveryUnavailable):
            rec.backup_hash_from_keybag(blob)

    def test_a_key_bag_with_no_password_protected_class_is_not_available(self):
        # every class is "this device only" (WRAP 1): the password unlocks
        # nothing, so there is nothing for hashcat to try it against either.
        blob = (_entry(b"UUID", b"U" * 16) + _entry(b"WRAP", 1)
               + _entry(b"SALT", b"S" * 20) + _entry(b"ITER", 20)
               + _entry(b"DPIC", 7) + _entry(b"DPSL", b"D" * 20)
               + _entry(b"UUID", bytes([9]) * 16) + _entry(b"CLAS", 9)
               + _entry(b"WRAP", 1) + _entry(b"WPKY", b"\xee" * 40))
        with self.assertRaises(rec.RecoveryUnavailable):
            rec.backup_hash_from_keybag(blob)

    def test_from_a_manifest_file(self):
        blob = fk.keybag_blob()
        tmp = tempfile.mkdtemp(prefix="ibe-recovery-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "Manifest.plist")
        with open(path, "wb") as handle:
            plistlib.dump({"BackupKeyBag": blob, "IsEncrypted": True},
                          handle)
        self.assertEqual(rec.backup_hash_from_manifest(path).text,
                         rec.backup_hash_from_keybag(blob).text)

    def test_a_manifest_with_no_key_bag(self):
        tmp = tempfile.mkdtemp(prefix="ibe-recovery-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "Manifest.plist")
        with open(path, "wb") as handle:
            plistlib.dump({"IsEncrypted": False}, handle)
        with self.assertRaises(rec.RecoveryUnavailable):
            rec.backup_hash_from_manifest(path)


class NoteHashTests(unittest.TestCase):
    def test_the_format_and_fields(self):
        salt, rounds, password = b"S" * 16, 1000, "correct horse"
        kek = nc.derive_key(password.encode("utf-8"), salt, rounds)
        wrapped = nc.key_wrap(kek, b"K" * 16)
        found = rec.note_hash(40, salt, rounds, wrapped)
        self.assertEqual(found.mode, "16200")
        self.assertEqual(found.kind, "note")
        prefix, pk, iterations, found_salt, found_wrapped = \
            found.text.split("*")
        self.assertEqual(prefix, "$ASN$")
        self.assertEqual(pk, "40")
        self.assertEqual(iterations, "1000")
        self.assertEqual(found_salt, salt.hex())
        self.assertEqual(found_wrapped, wrapped.hex())

    def test_missing_details_are_not_available(self):
        with self.assertRaises(rec.RecoveryUnavailable):
            rec.note_hash(40, None, None, None)
        with self.assertRaises(rec.RecoveryUnavailable):
            rec.note_hash(40, b"S" * 16, 0, b"K" * 16)


class HashcatRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-recovery-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hashcat = [sys.executable, fr.fake_hashcat(self.tmp)]

    def _run(self, recovery_hash, wordlist_lines, extra_args=()):
        wordlist = os.path.join(self.tmp, f"words-{id(wordlist_lines)}.txt")
        with open(wordlist, "w", encoding="utf-8") as handle:
            handle.write("\n".join(wordlist_lines) + "\n")
        lines, done = [], threading.Event()
        result = {}

        def on_done(password, note):
            result["password"], result["note"] = password, note
            done.set()

        run = rec.HashcatRun(self.hashcat, recovery_hash, wordlist=wordlist,
                             extra_args=extra_args, on_line=lines.append,
                             on_done=on_done)
        run.start()
        return run, lines, done, result

    def test_a_crack_that_succeeds(self):
        found = rec.RecoveryHash("$itunes_backup$*FOUND-ME*x", "14800",
                                 "backup")
        run, lines, done, result = self._run(found, ["nope", "FOUND-ME"])
        self.assertTrue(done.wait(10))
        run.close()
        self.assertEqual(result["password"], "FOUND-ME")
        self.assertIsNone(result["note"])
        self.assertTrue(any("hashcat (fake)" in line for line in lines))

    def test_a_crack_that_exhausts_the_wordlist(self):
        found = rec.RecoveryHash("$itunes_backup$*FOUND-ME*x", "14800",
                                 "backup")
        run, lines, done, result = self._run(found, ["nope", "nope-either"])
        self.assertTrue(done.wait(10))
        run.close()
        self.assertIsNone(result["password"])
        self.assertIsNone(result["note"])   # exhausted, not an error

    def test_an_unexpected_exit_is_reported(self):
        found = rec.RecoveryHash("$itunes_backup$*x", "14800", "backup")
        run, lines, done, result = self._run(found, ["x"],
                                             extra_args=["--fake-fail"])
        self.assertTrue(done.wait(10))
        run.close()
        self.assertIsNone(result["password"])
        self.assertIn("status 2", result["note"])

    def test_stopping_a_run_in_progress(self):
        found = rec.RecoveryHash("$itunes_backup$*FOUND-ME*x", "14800",
                                 "backup")
        run, lines, done, result = self._run(
            found, ["FOUND-ME"], extra_args=["--fake-sleep", "5"])
        run.stop()
        self.assertTrue(done.wait(10))
        self.assertEqual(result["note"], "Stopped.")
        run.close()

    def test_close_removes_the_working_folder(self):
        found = rec.RecoveryHash("$itunes_backup$*x", "14800", "backup")
        run, lines, done, result = self._run(found, ["x"])
        self.assertTrue(done.wait(10))
        folder = run.folder
        run.close()
        self.assertFalse(os.path.isdir(folder))

    def _run_mask(self, recovery_hash, mask, extra_args=()):
        lines, done = [], threading.Event()
        result = {}

        def on_done(password, note):
            result["password"], result["note"] = password, note
            done.set()

        run = rec.HashcatRun(self.hashcat, recovery_hash, mask=mask,
                             extra_args=extra_args, on_line=lines.append,
                             on_done=on_done)
        run.start()
        return run, lines, done, result

    def test_a_mask_attack_that_succeeds(self):
        # A wordlist is never sent on this path: if it were (a mixed-up
        # argument list), the fake would try to open None as a file and
        # this would error out instead of reporting "Cracked".
        found = rec.RecoveryHash("$itunes_backup$*4242*x", "14800", "backup")
        run, lines, done, result = self._run_mask(found, "?d?d?d?d")
        self.assertTrue(done.wait(10))
        run.close()
        self.assertEqual(result["password"], "4242")
        self.assertIsNone(result["note"])

    def test_a_mask_attack_that_exhausts_the_pattern(self):
        found = rec.RecoveryHash("$itunes_backup$*4242*x", "14800", "backup")
        run, lines, done, result = self._run_mask(found, "?d?d?d")  # 3, not 4
        self.assertTrue(done.wait(10))
        run.close()
        self.assertIsNone(result["password"])
        self.assertIsNone(result["note"])


class CuppProfileTests(unittest.TestCase):
    def test_a_name_is_needed(self):
        self.assertFalse(rec.cupp_answers_valid({}))
        self.assertTrue(rec.cupp_answers_valid({"first_name": "Alex"}))

    def test_a_birthdate_must_be_blank_or_eight_digits(self):
        base = {"first_name": "Alex"}
        self.assertTrue(rec.cupp_answers_valid(
            dict(base, birthdate="")))
        self.assertTrue(rec.cupp_answers_valid(
            dict(base, birthdate="01021990")))
        self.assertFalse(rec.cupp_answers_valid(
            dict(base, birthdate="1990")))
        self.assertFalse(rec.cupp_answers_valid(
            dict(base, partner_birthdate="not-a-date")))


class RunCuppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-recovery-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cupp = fr.fake_cupp(self.tmp)

    def test_the_answers_reach_cupp_in_the_order_it_asks(self):
        output = os.path.join(self.tmp, "out.txt")
        profile = {"first_name": "Robin", "pet_name": "Max",
                   "company": "Acme"}
        rec.run_cupp(self.cupp, profile, output, extra_words="hiking,blue",
                     add_numbers=True)
        with open(output, encoding="utf-8") as handle:
            words = handle.read().splitlines()
        self.assertEqual(words, ["Robin", "Max", "Acme", "hiking", "blue",
                                 "Robin123"])

    def test_an_invalid_profile_is_refused_before_running_anything(self):
        with self.assertRaises(rec.RecoveryUnavailable):
            rec.run_cupp(self.cupp, {}, os.path.join(self.tmp, "x.txt"))

    def test_leet_and_special_chars(self):
        output = os.path.join(self.tmp, "out2.txt")
        rec.run_cupp(self.cupp, {"first_name": "pete"}, output,
                     add_special_chars=True, use_leet=True)
        with open(output, encoding="utf-8") as handle:
            words = handle.read().splitlines()
        self.assertEqual(words, ["pete", "pete!", "p3t3"])


if __name__ == "__main__":
    unittest.main()
