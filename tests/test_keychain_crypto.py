# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The cryptography and the formats of the keychain (no window)."""

import struct
import unittest

from ios_apps import keychain_crypto as kc
from tests import fixture_keychain as fk


class GcmTests(unittest.TestCase):
    """The GCM done here against pycryptodome's, for the nonces it allows,
    and the nonce it does not (none)."""

    KEY = bytes(range(32))

    def library(self, iv, plain, aad=b""):
        from Crypto.Cipher import AES
        cipher = AES.new(self.KEY, AES.MODE_GCM, nonce=iv)
        cipher.update(aad)
        return cipher.encrypt_and_digest(plain)

    def test_it_agrees_with_the_library_for_many_nonces(self):
        for iv_length in (1, 5, 12, 16, 17, 60):
            for size in (0, 1, 15, 16, 17, 33, 100):
                for aad in (b"", b"header"):
                    iv = bytes(range(1, iv_length + 1))
                    plain = bytes((i * 7) & 0xFF for i in range(size))
                    expected = self.library(iv, plain, aad)
                    with self.subTest(iv=iv_length, size=size, aad=aad):
                        self.assertEqual(
                            kc.gcm_encrypt(self.KEY, iv, plain, aad),
                            expected)
                        self.assertEqual(
                            kc.gcm_decrypt(self.KEY, iv, expected[0],
                                           expected[1], aad), plain)

    def test_a_published_vector(self):
        # NIST GCM test case 2: zero key, zero 96-bit nonce, one zero block
        key, iv = bytes(16), bytes(12)
        ciphertext, tag = kc.gcm_encrypt(key, iv, bytes(16))
        self.assertEqual(ciphertext.hex(), "0388dace60b6a392f328c2b971b2fe78")
        self.assertEqual(tag.hex(), "ab6e47d42cec13bdf53a67b21257bddf")

    def test_an_empty_nonce_round_trips_and_is_not_any_other(self):
        plain = b"the keychain item"
        ciphertext, tag = kc.gcm_encrypt(self.KEY, b"", plain)
        self.assertEqual(kc.gcm_decrypt(self.KEY, b"", ciphertext, tag),
                         plain)
        # the first counter block is all zeros, so no other nonce is the same
        for iv in (bytes(12), bytes(16), b"\0"):
            self.assertNotEqual(kc.gcm_encrypt(self.KEY, iv, plain)[0],
                                ciphertext)

    def test_a_wrong_key_or_damage_is_refused(self):
        ciphertext, tag = kc.gcm_encrypt(self.KEY, b"", b"secret")
        with self.assertRaises(ValueError):
            kc.gcm_decrypt(bytes(32), b"", ciphertext, tag)
        with self.assertRaises(ValueError):
            kc.gcm_decrypt(self.KEY, b"", b"x" + ciphertext[1:], tag)
        with self.assertRaises(ValueError):
            kc.gcm_decrypt(self.KEY, b"", ciphertext, bytes(16))
        with self.assertRaises(ValueError):
            kc.gcm_decrypt(self.KEY, b"", ciphertext, tag, b"extra")


class DerTests(unittest.TestCase):
    def decode(self, data):
        value, rest = kc.der_decode(data)
        self.assertEqual(rest, b"")
        return value

    def test_the_basic_types(self):
        self.assertEqual(self.decode(fk.der_value("héllo")), "héllo")
        self.assertEqual(self.decode(fk.der_value(b"\x00\xff")), b"\x00\xff")
        self.assertEqual(self.decode(fk.der_value(True)), True)
        self.assertEqual(self.decode(fk.der_value(False)), False)
        self.assertIsNone(self.decode(fk.der_value(None)))

    def test_integers(self):
        for number in (0, 1, 127, 128, 255, 256, 65535, 2 ** 40, -1, -129):
            with self.subTest(number=number):
                self.assertEqual(self.decode(fk.der_value(number)), number)

    def test_long_lengths(self):
        for size in (127, 128, 255, 256, 70000):
            data = bytes(size)
            with self.subTest(size=size):
                self.assertEqual(self.decode(fk.der_value(data)), data)

    def test_dates_become_unix_seconds(self):
        self.assertEqual(self.decode(fk.der_value(fk.WHEN)),
                         fk.WHEN.timestamp())
        self.assertEqual(self.decode(fk.der(0x18, b"20240305143000.5Z")),
                         fk.WHEN.timestamp() + 0.5)
        # a UTCTime, and a date that is no date
        self.assertEqual(self.decode(fk.der(0x17, b"240305143000Z")),
                         fk.WHEN.timestamp())
        self.assertEqual(self.decode(fk.der(0x18, b"20241340000000Z")),
                         "20241340000000Z")

    def test_nested_values(self):
        data = fk.der(0x30, fk.der_value("a") + fk.der(
            0x31, fk.der_value(1) + fk.der_value(2)))
        self.assertEqual(self.decode(data), ["a", [1, 2]])

    def test_the_attributes_of_an_item(self):
        found = kc.attributes(fk.der_attributes(
            {"acct": "me", "port": 443, "v_Data": b"pw"}))
        self.assertEqual(found, {"acct": "me", "port": 443, "v_Data": b"pw"})

    def test_it_agrees_with_asn1crypto(self):
        try:
            import asn1crypto.core as core
        except ImportError:
            self.skipTest("asn1crypto is not installed")
        data = fk.der_attributes({"acct": "me", "port": 443, "ok": True})
        parsed = core.Asn1Value.load(data).native \
            if hasattr(core.Asn1Value, "native") else None
        del parsed                           # (loading is the check)
        self.assertEqual(kc.attributes(data)["acct"], "me")

    def test_damage_is_refused_not_crashed_on(self):
        good = fk.der_attributes({"acct": "me"})
        for bad in (b"", b"\x31", b"\x31\x05abc", good[:-1],
                    b"\x30\x80", b"\x02\x84\xff\xff\xff\xff"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                kc.der_decode(bad)

    def test_too_deep_is_refused(self):
        data = fk.der_value(1)
        for _ in range(20):
            data = fk.der(0x30, data)
        with self.assertRaises(ValueError):
            kc.der_decode(data)

    def test_attributes_ignores_what_is_not_a_pair(self):
        data = fk.der(0x31, fk.der(0x30, fk.der_value("only one"))
                      + fk.der(0x30, fk.der_value("k") + fk.der_value("v"))
                      + fk.der_value(7))
        self.assertEqual(kc.attributes(data), {"k": "v"})
        self.assertEqual(kc.attributes(fk.der_value("not a set")), {})


class ItemTests(unittest.TestCase):
    ATTRS = {"acct": "me", "svce": "thing", "v_Data": b"password"}

    def key(self, clas=6):
        return fk.CLASS_KEYS[clas]

    def test_an_item_opens_with_its_class_key(self):
        blob = fk.make_item(self.ATTRS, 6)
        self.assertEqual(kc.open_item(blob, self.key(6)), self.ATTRS)
        self.assertEqual(kc.class_of(blob), 6)

    def test_every_class_of_the_backup(self):
        for clas in (6, 7, 8):
            blob = fk.make_item(self.ATTRS, clas)
            self.assertEqual(kc.open_item(blob, self.key(clas)), self.ATTRS)

    def test_the_wrong_class_key_is_refused(self):
        blob = fk.make_item(self.ATTRS, 6)
        with self.assertRaises(kc.ItemError) as caught:
            kc.open_item(blob, self.key(7))
        self.assertIn("unwrapped", caught.exception.reason)

    def test_no_key_for_a_device_only_class(self):
        blob = fk.make_item(self.ATTRS, 10)
        with self.assertRaises(kc.ItemError) as caught:
            kc.open_item(blob, None)
        self.assertTrue(caught.exception.device_only)
        self.assertIn("phone", caught.exception.reason)

    def test_a_device_only_item_whose_class_key_does_not_fit(self):
        # a real backup's key bag lists keys for these classes, but the
        # items were wrapped with the phone's own keys
        for clas in (9, 10, 11):
            blob = fk.make_item(self.ATTRS, clas)
            with self.subTest(clas=clas), \
                    self.assertRaises(kc.ItemError) as caught:
                kc.open_item(blob, b"\x99" * 32)
            self.assertTrue(caught.exception.device_only)
            self.assertIn("phone", caught.exception.reason)

    def test_no_key_for_another_class_is_not_device_only(self):
        blob = fk.make_item(self.ATTRS, 7)
        with self.assertRaises(kc.ItemError) as caught:
            kc.open_item(blob, None)
        self.assertFalse(caught.exception.device_only)

    def test_damage_is_noticed(self):
        blob = bytearray(fk.make_item(self.ATTRS, 6))
        for position in (len(blob) - 1, len(blob) - 20, 20):
            damaged = bytearray(blob)
            damaged[position] ^= 1
            with self.subTest(position=position), \
                    self.assertRaises(kc.ItemError):
                kc.open_item(bytes(damaged), self.key(6))

    def test_version_two_holds_a_property_list(self):
        blob = fk.make_item(self.ATTRS, 6, version=2)
        self.assertEqual(kc.open_item(blob, self.key(6)), self.ATTRS)

    def test_old_and_odd_formats_are_refused(self):
        good = fk.make_item(self.ATTRS, 6)
        for blob in (b"", b"short", struct.pack("<I", 0) + good[4:],
                     struct.pack("<I", 9) + good[4:],
                     good[:8] + struct.pack("<I", 41) + good[12:],
                     None, "text"):
            with self.subTest(blob=blob), self.assertRaises(kc.ItemError):
                kc.open_item(blob, self.key(6))
        self.assertIsNone(kc.class_of(b"short"))

    def test_the_reasons_are_told_apart(self):
        good = fk.make_item(self.ATTRS, 6)
        with self.assertRaises(kc.ItemError) as caught:
            kc.open_item(good[:8] + struct.pack("<I", 41) + good[12:],
                         self.key(6))
        self.assertIn("unexpected size", caught.exception.reason)
        with self.assertRaises(kc.ItemError) as caught:
            kc.open_item(b"short", self.key(6))
        self.assertIn("too short", caught.exception.reason)

    def test_the_three_device_only_classes(self):
        self.assertEqual(kc.DEVICE_ONLY, frozenset({9, 10, 11}))
        for clas in (9, 10, 11):
            blob = fk.make_item(self.ATTRS, clas)
            with self.subTest(clas=clas), \
                    self.assertRaises(kc.ItemError) as caught:
                kc.open_item(blob, None)
            self.assertTrue(caught.exception.device_only)
        for clas in (6, 7, 8):
            blob = fk.make_item(self.ATTRS, clas)
            with self.assertRaises(kc.ItemError) as caught:
                kc.open_item(blob, None)
            self.assertFalse(caught.exception.device_only)

    def test_the_class_is_read_from_its_low_bits(self):
        blob = bytearray(fk.make_item(self.ATTRS, 6))
        blob[4] |= 0x10                    # (a flag above the class)
        self.assertEqual(kc.class_of(bytes(blob)), 6)

    def test_garbage_that_opens_is_not_taken_for_an_item(self):
        key = b"k" * 32
        wrapped = kc.notes_crypto.key_wrap(self.key(6), key)
        cipher, tag = kc.gcm_encrypt(key, b"", b"\x01\x02 not der")
        blob = struct.pack("<III", 3, 6, 40) + wrapped + cipher + tag
        self.assertEqual(kc.open_item(blob, self.key(6)), {})


class KeyBagTests(unittest.TestCase):
    def test_the_right_password_unlocks_every_class(self):
        keys = kc.unlock_keybag(fk.keybag_blob(), fk.PASSWORD)
        self.assertEqual(keys.classes(), [6, 7, 8])
        for clas, key in fk.CLASS_KEYS.items():
            self.assertEqual(keys.key(clas), key)
        self.assertIsNone(keys.key(10))

    def test_classes_the_password_cannot_open_are_left_out(self):
        keys = kc.unlock_keybag(
            fk.keybag_blob(device_wrapped=(10, 11)), fk.PASSWORD)
        self.assertEqual(keys.classes(), [6, 7, 8])
        self.assertIsNone(keys.key(10))

    def test_the_wrong_password(self):
        with self.assertRaises(kc.WrongBackupPassword):
            kc.unlock_keybag(fk.keybag_blob(), "wrong")

    def test_it_agrees_with_the_decryption_library(self):
        try:
            from iphone_backup_decrypt import utils
            bag = utils.BackupKeyBag(fk.keybag_blob())
        except (ImportError, AttributeError):
            self.skipTest("this version of the library has no BackupKeyBag")
        self.assertTrue(bag.unlock_with_passphrase(fk.PASSWORD))
        ours = kc.unlock_keybag(fk.keybag_blob(), fk.PASSWORD)
        self.assertEqual({c: ours.key(c) for c in ours.classes()},
                         dict(bag.classes_keys))

    def test_a_key_bag_that_is_not_one(self):
        for blob in (b"", b"junk", fk._entry(b"VERS", 5)):
            with self.subTest(blob=blob), self.assertRaises(ValueError):
                kc.unlock_keybag(blob, fk.PASSWORD)

    def test_absurd_round_counts_are_refused(self):
        with self.assertRaises(ValueError):
            kc.unlock_keybag(fk.keybag_blob(claimed_dpic=4_000_000_000), fk.PASSWORD)
        with self.assertRaises(ValueError):
            kc.unlock_keybag(fk.keybag_blob(claimed_iterations=0),
                              fk.PASSWORD)

    def test_class_keys_from_the_library_object(self):
        class Bag:
            classes_keys = {6: b"k" * 32}

        class Backup:
            keybag = Bag()

        keys = kc.keys_from_library(Backup())
        self.assertEqual(keys.key(6), b"k" * 32)
        self.assertIsNone(kc.keys_from_library(object()))


if __name__ == "__main__":
    unittest.main()
