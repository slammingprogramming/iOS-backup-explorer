# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Notes locked with a password: the cryptography and the reader."""

import os
import shutil
import sqlite3
import tempfile
import unicodedata
import unittest

from ios_apps import notes as nt
from ios_apps import notes_crypto as nc
from tests import fixture_notes as fn
from tests import fixture_notes_locked as fl


class KeyWrapTests(unittest.TestCase):
    # RFC 3394, section 4.1: 128 bits of key data with a 128-bit KEK
    KEK = bytes.fromhex("000102030405060708090A0B0C0D0E0F")
    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    WRAPPED = bytes.fromhex(
        "1FA68B0A8112B447AEF34BD8FB5A7B829D3E862371D2CFE5")

    def test_the_rfc_vector_wraps(self):
        self.assertEqual(nc.key_wrap(self.KEK, self.KEY), self.WRAPPED)

    def test_the_rfc_vector_unwraps(self):
        self.assertEqual(nc.key_unwrap(self.KEK, self.WRAPPED), self.KEY)

    def test_a_longer_key_round_trips(self):
        kek = bytes(range(32))
        key = bytes(range(100, 132))
        self.assertEqual(nc.key_unwrap(kek, nc.key_wrap(kek, key)), key)

    def test_the_wrong_key_encryption_key_is_noticed(self):
        with self.assertRaises(nc.WrongPassword):
            nc.key_unwrap(bytes(16), self.WRAPPED)

    def test_damage_is_noticed(self):
        damaged = bytearray(self.WRAPPED)
        damaged[10] ^= 1
        with self.assertRaises(nc.WrongPassword):
            nc.key_unwrap(self.KEK, bytes(damaged))

    def test_a_wrapped_key_of_the_wrong_length(self):
        for bad in (b"", self.WRAPPED[:16], self.WRAPPED + b"\x00"):
            with self.subTest(length=len(bad)), \
                    self.assertRaises(nc.WrongPassword):
                nc.key_unwrap(self.KEK, bad)

    def test_it_agrees_with_the_library_own_implementation(self):
        from Crypto.Cipher import AES
        if not hasattr(AES, "MODE_KW"):
            self.skipTest("this pycryptodome has no key wrap mode")
        cipher = AES.new(self.KEK, AES.MODE_KW)
        self.assertEqual(cipher.seal(self.KEY), self.WRAPPED)


class DecryptTests(unittest.TestCase):
    def setUp(self):
        self.salt, self.key, self.iv = b"s" * 16, b"k" * 16, b"i" * 16
        self.wrapped, self.tag, self.data = nc.encrypt(
            "open sesame", self.salt, 500, self.key, self.iv, b"the note")

    def open(self, password="open sesame", **change):
        args = dict(salt=self.salt, iterations=500, wrapped_key=self.wrapped,
                    iv=self.iv, tag=self.tag, data=self.data)
        args.update(change)
        return nc.decrypt(password, **args)

    def test_the_right_password(self):
        self.assertEqual(self.open(), b"the note")

    def test_wrong_passwords(self):
        for bad in ("", "open sesame ", "Open sesame", "x"):
            with self.subTest(password=bad), \
                    self.assertRaises(nc.WrongPassword):
                self.open(bad)

    def test_damaged_data_is_never_returned_as_text(self):
        flipped = bytes([self.data[0] ^ 1]) + self.data[1:]
        with self.assertRaises(nc.WrongPassword):
            self.open(data=flipped)
        with self.assertRaises(nc.WrongPassword):
            self.open(tag=bytes(16))

    def test_the_other_settings_matter(self):
        for change in ({"iterations": 501}, {"salt": b"t" * 16},
                       {"iv": b"j" * 16}):
            with self.subTest(change=change), \
                    self.assertRaises(nc.WrongPassword):
                self.open(**change)

    def test_incomplete_details(self):
        for name in ("salt", "iterations", "wrapped_key", "iv", "tag",
                     "data"):
            with self.subTest(missing=name), \
                    self.assertRaises(nc.WrongPassword):
                self.open(**{name: None})

    def test_an_accented_password_either_way(self):
        wrapped, tag, data = nc.encrypt(
            "café", self.salt, 500, self.key, self.iv, b"accent")
        for form in ("NFC", "NFD"):
            typed = unicodedata.normalize(form, "café")
            self.assertEqual(
                nc.decrypt(typed, self.salt, 500, wrapped, self.iv, tag,
                           data), b"accent", form)

    def test_the_key_is_pbkdf2_sha256_of_sixteen_bytes(self):
        # a published PBKDF2-HMAC-SHA256 vector ("password", "salt", 1 round)
        key = nc.derive_key(b"password", b"salt", 1)
        self.assertEqual(key.hex(), "120fb6cffcf8b32c43e7225256c4f837")
        self.assertEqual(len(key), 16)

    def test_the_spellings_are_not_repeated(self):
        self.assertEqual(len(nc.spellings("plain")), 1)
        self.assertEqual(len(nc.spellings("café")), 2)

    def test_notes_keys_of_every_aes_size(self):
        for size in (16, 24, 32):
            wrapped, tag, data = nc.encrypt(
                "pw", self.salt, 500, b"y" * size, self.iv, b"sized")
            with self.subTest(size=size):
                self.assertEqual(nc.decrypt("pw", self.salt, 500, wrapped,
                                            self.iv, tag, data), b"sized")

    def test_a_wrapped_key_that_is_not_an_aes_key_is_refused(self):
        kek = nc.derive_key(b"pw", self.salt, 500)
        wrapped = nc.key_wrap(kek, b"y" * 40)           # not a key size
        with self.assertRaises(nc.WrongPassword):
            nc.decrypt("pw", self.salt, 500, wrapped, self.iv, self.tag,
                       self.data)


def open_database():
    conn = sqlite3.connect(":memory:")
    fl.build(conn)
    return conn


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.conn = open_database()
        self.addCleanup(self.conn.close)
        self.tmp = tempfile.mkdtemp(prefix="ibe-locked-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.reader = nt.NotesReader(
            self.conn, lambda media, name: f"Media/{media}/{name}")
        self.notes = {n.pk: n for n in self.reader.notes()}

    def text(self, pk):
        return self.reader.load(self.notes[pk]).text

    def test_the_locked_notes_are_known_and_have_their_details(self):
        locked = sorted(n.pk for n in self.notes.values() if n.locked)
        self.assertEqual(locked, [12, fl.BANK, fl.DIARY, fl.VAULT, fl.BROKEN])
        self.assertEqual(self.notes[fl.VAULT].hint, fl.HINT)
        self.assertEqual(self.notes[fl.BANK].hint, "")
        self.assertEqual(self.notes[fl.BANK].crypto["rounds"], fl.ROUNDS)
        self.assertIsNone(self.notes[10].crypto)         # an ordinary note

    def test_without_a_password_a_locked_note_says_so(self):
        note = self.reader.load(self.notes[fl.BANK])
        self.assertEqual(note.paragraphs, [])
        self.assertIn("locked with a password", note.error)
        self.assertIn("enter the password", note.error)
        self.assertFalse(note.unlocked)

    def test_the_right_password_opens_every_note_it_fits(self):
        opened, still = self.reader.try_password(
            list(self.notes.values()), fl.SHARED)
        self.assertEqual(sorted(n.pk for n in opened), [fl.BANK, fl.DIARY])
        self.assertEqual(sorted(n.pk for n in still), [12, fl.VAULT, fl.BROKEN])
        self.assertIn("PIN for the card is 4821", self.text(fl.BANK))
        self.assertIn("nothing happened", self.text(fl.DIARY))
        self.assertTrue(self.notes[fl.BANK].unlocked)
        self.assertEqual(self.notes[fl.BANK].error[:9], "1 attache")

    def test_a_note_that_is_open_stays_open_under_a_wrong_password(self):
        self.reader.try_password([self.notes[fl.BANK]], fl.SHARED)
        opened, still = self.reader.try_password(
            [self.notes[fl.BANK], self.notes[fl.VAULT]], "wrong")
        self.assertEqual([n.pk for n in opened], [fl.BANK])
        self.assertEqual([n.pk for n in still], [fl.VAULT])
        self.assertTrue(self.notes[fl.BANK].unlocked)

    def test_a_wrong_password_opens_nothing_and_is_not_kept(self):
        opened, still = self.reader.try_password(
            list(self.notes.values()), "nope")
        self.assertEqual(opened, [])
        self.assertEqual(len(still), 5)
        self.assertEqual(self.reader.password_count, 0)

    def test_a_password_is_remembered_for_the_next_note(self):
        self.reader.try_password([self.notes[fl.BANK]], fl.SHARED)
        # the diary was never tried; it opens on its own when looked at
        self.assertIn("nothing happened", self.text(fl.DIARY))
        self.assertTrue(self.notes[fl.DIARY].unlocked)

    def test_a_note_looked_at_before_the_password_opens_after_it(self):
        self.assertEqual(self.text(fl.DIARY), "")
        self.reader.try_password([self.notes[fl.BANK]], fl.SHARED)
        self.assertIn("nothing happened", self.text(fl.DIARY))
        self.assertEqual(self.notes[fl.DIARY].error, "")

    def test_a_different_password_for_a_different_note(self):
        self.reader.try_password([self.notes[fl.BANK]], fl.SHARED)
        self.assertEqual(self.text(fl.VAULT), "")        # still locked
        self.assertIn("locked", self.notes[fl.VAULT].error)
        opened, _ = self.reader.try_password([self.notes[fl.VAULT]], fl.OTHER)
        self.assertEqual([n.pk for n in opened], [fl.VAULT])
        self.assertIn("spare key", self.text(fl.VAULT))
        self.assertEqual(self.reader.password_count, 2)

    def test_the_password_is_typed_with_the_other_accent_form(self):
        typed = unicodedata.normalize("NFD", fl.OTHER)
        self.assertNotEqual(typed, fl.OTHER)
        opened, _ = self.reader.try_password([self.notes[fl.VAULT]], typed)
        self.assertEqual(len(opened), 1)

    def test_forgetting_locks_them_again(self):
        self.reader.try_password(list(self.notes.values()), fl.SHARED)
        self.reader.forget_passwords()
        self.assertEqual(self.reader.password_count, 0)
        self.assertFalse(self.notes[fl.BANK].unlocked)
        self.assertEqual(self.text(fl.BANK), "")
        self.assertIn("locked", self.notes[fl.BANK].error)

    def test_search_finds_words_only_in_the_notes_that_are_open(self):
        self.assertEqual(self.reader.search("nothing happened"), [])
        self.reader.try_password([self.notes[fl.DIARY]], fl.SHARED)
        self.assertEqual([n.pk for n in self.reader.search("nothing happened")],
                         [fl.DIARY])
        self.assertEqual([n.pk for n in self.reader.search("4821")], [fl.BANK])

    def test_a_note_with_no_details_never_opens_and_never_fails(self):
        for pk in (12, fl.BROKEN):
            note = self.notes[pk]
            self.assertFalse(self.reader.unlock(note, [fl.SHARED, fl.OTHER]))
            self.assertIn("locked", self.reader.load(note).error)

    def attachments(self):
        self.reader.try_password([self.notes[fl.BANK]], fl.SHARED)
        return self.reader.load(self.notes[fl.BANK]).attachments

    def test_a_locked_file_with_its_details_can_be_opened(self):
        attachment = self.attachments()["ATT-LOCKED"]
        self.assertIn("MEDIA-LOCKED", attachment.path)
        self.assertTrue(callable(attachment.decrypt))
        local = os.path.join(self.tmp, "copy.bin")
        with open(local, "wb") as handle:
            handle.write(fl.locked_file())         # a copy as the backup has it
        attachment.decrypt(local)
        with open(local, "rb") as handle:
            self.assertEqual(handle.read(), fl.LOCKED_PLAIN)

    def test_a_file_without_details_is_not_offered(self):
        attachments = self.attachments()
        self.assertEqual(attachments["ATT-PHOTO"].path, "")
        self.assertIsNone(attachments["ATT-PHOTO"].decrypt)
        note = self.notes[fl.BANK]
        self.assertIn("1 attached file of this locked note cannot be opened",
                      note.error)

    def test_an_ordinary_notes_files_are_left_alone(self):
        found = self.reader.load(self.notes[10]).attachments.values()
        self.assertTrue(any(a.path for a in found))
        self.assertTrue(all(a.decrypt is None for a in found))

    def test_a_file_that_does_not_open_is_left_as_it_was(self):
        attachment = self.attachments()["ATT-LOCKED"]
        local = os.path.join(self.tmp, "copy.bin")
        damaged = bytearray(fl.locked_file())
        damaged[3] ^= 1
        with open(local, "wb") as handle:
            handle.write(damaged)
        with self.assertRaises(nc.WrongPassword):
            attachment.decrypt(local)
        with open(local, "rb") as handle:
            self.assertEqual(handle.read(), bytes(damaged))
        self.assertEqual(os.listdir(self.tmp), ["copy.bin"])

    def test_a_failure_while_writing_leaves_nothing_behind(self):
        from unittest import mock
        attachment = self.attachments()["ATT-LOCKED"]
        local = os.path.join(self.tmp, "copy.bin")
        with open(local, "wb") as handle:
            handle.write(fl.locked_file())
        with mock.patch("ios_apps.notes_crypto.os.replace",
                        side_effect=OSError("disk full")),                 self.assertRaises(OSError):
            attachment.decrypt(local)
        self.assertEqual(os.listdir(self.tmp), ["copy.bin"])
        with open(local, "rb") as handle:
            self.assertEqual(handle.read(), fl.locked_file())

    def test_the_media_folder_of_a_path(self):
        self.assertEqual(nt._media_id_of("D/Accounts/A/Media/ID/1_G/f"), "ID")
        self.assertEqual(nt._media_id_of("D/Media/ID/f"), "ID")
        self.assertEqual(nt._media_id_of("D/Media/f"), "")
        self.assertEqual(nt._media_id_of("D/x/f"), "")

    def test_forgetting_takes_the_means_of_opening_away(self):
        self.attachments()
        self.reader.forget_passwords()
        note = self.notes[fl.BANK]
        self.assertIsNone(note.password)
        self.assertEqual(note.attachments, {})

    def test_ordinary_notes_are_not_touched(self):
        self.assertIn("Milk", self.text(10))
        self.assertFalse(self.notes[10].unlocked)
        self.assertTrue(self.reader.unlock(self.notes[10]))     # nothing to do

    def test_a_note_needs_all_three_details_to_be_unlockable(self):
        note = self.notes[fl.BANK]
        self.assertTrue(note.unlockable)
        for missing in ("salt", "wrapped", "rounds"):
            details = dict(note.crypto, **{missing: None})
            other = nt.Note(1, "x", locked=True, crypto=details)
            with self.subTest(missing=missing):
                self.assertFalse(other.unlockable)
        self.assertFalse(nt.Note(1, "x", crypto=note.crypto).unlockable)

    def test_locked_notes_of_a_list(self):
        subset = [self.notes[10], self.notes[fl.DIARY], self.notes[fl.VAULT]]
        self.assertEqual([n.pk for n in self.reader.locked_notes(subset)],
                         [fl.DIARY, fl.VAULT])

    def test_an_old_database_without_the_columns(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        fn.build(conn)                  # no crypto columns at all
        reader = nt.NotesReader(conn)
        note = next(n for n in reader.notes() if n.locked)
        self.assertFalse(reader.unlock(note, ["anything"]))
        self.assertIn("locked", reader.load(note).error)


if __name__ == "__main__":
    unittest.main()
