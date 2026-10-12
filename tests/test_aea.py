# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Apple Encrypted Archives: opening one with its key, and refusing a wrong
key or a damaged file."""

import unittest
from unittest import mock

from ios_apps import aea
from tests import aea_builder as ab
from tests.keyed_builder import archive

PLAIN = (b"A line of an invented report. " * 40000)[:0x4000 * 32 * 2 + 100]


class KnownAnswerTests(unittest.TestCase):
    def test_hkdf_rfc_5869_case_1(self):
        okm = aea.hkdf(
            42, bytes.fromhex("0b" * 22), bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"),
            bytes.fromhex("000102030405060708090a0b0c"))
        self.assertEqual(okm.hex(), (
            "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
            "34007208d5b887185865"))

    def test_hkdf_without_a_salt_and_for_longer_output(self):
        okm = aea.hkdf(80, bytes.fromhex("0b" * 22), b"")
        self.assertEqual(len(okm), 80)
        self.assertEqual(okm[:32], aea.hkdf(32, bytes.fromhex("0b" * 22), b""))

    def test_murmur(self):
        # values from kinnay/AEA's implementation
        self.assertEqual(aea.murmur64a(b"hello world, murmur").hex(),
                         "1e579af592e032e0")
        self.assertEqual(aea.murmur64a(b"", 0).hex(), "0000000000000000")
        self.assertEqual(aea.murmur64a(b"12345678", 1).hex(),
                         "a0afad6f16600089")

    def test_an_archive_made_by_another_implementation(self):
        self.assertEqual(aea.decrypt(ab.REFERENCE_ARCHIVE, ab.KEY), ab.TEXT)


class OpenTests(unittest.TestCase):
    def test_variants_of_the_format(self):
        for options in ({}, {"compression": "z"},
                        {"compression": "x", "checksum": 1},
                        {"profile": 2, "checksum": 0}, {"auth": b"abc"},
                        {"segment_size": 0x8000, "per_cluster": 64}):
            with self.subTest(options):
                data = ab.build(PLAIN, **options)
                self.assertTrue(aea.is_archive(data))
                self.assertEqual(aea.decrypt(data, ab.KEY), PLAIN)

    def test_several_clusters_are_read_in_order(self):
        data = ab.build(PLAIN, compression="z")
        # three clusters of 32 segments of 16 KB: 2 full ones and a bit
        self.assertEqual(len(PLAIN), 0x4000 * 32 * 2 + 100)
        self.assertEqual(aea.decrypt(data, ab.KEY), PLAIN)

    def test_small_and_empty_contents(self):
        for plain in (b"", b"x", b"\0" * 0x4000, b"y" * 0x4001):
            with self.subTest(len(plain)):
                self.assertEqual(
                    aea.decrypt(ab.build(plain), ab.KEY), plain)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.data = ab.build(b"The quick brown fox. " * 500, compression="z")

    def test_a_wrong_key(self):
        with self.assertRaisesRegex(aea.ArchiveError, "does not open"):
            aea.decrypt(self.data, bytes(32))

    def test_a_key_of_the_wrong_size(self):
        for key in (b"short", None, "text", bytes(33)):
            with self.assertRaises(aea.ArchiveError):
                aea.decrypt(self.data, key)

    def test_not_an_archive(self):
        with self.assertRaisesRegex(aea.ArchiveError, "Apple Encrypted"):
            aea.decrypt(b"%PDF-1.4 not encrypted", ab.KEY)
        self.assertFalse(aea.is_archive(b"%PDF"))
        self.assertFalse(aea.is_archive(b""))

    def test_a_damaged_part_is_found_wherever_it_is(self):
        spots = (60, 100, 150, 400, len(self.data) - 100)
        for spot in spots:
            with self.subTest(spot):
                damaged = bytearray(self.data)
                damaged[spot] ^= 0x40
                with self.assertRaises(aea.ArchiveError):
                    aea.decrypt(bytes(damaged), ab.KEY)

    def test_a_part_that_lies_although_its_check_values_are_right(self):
        """Authentic but wrong inside: only the checksum and the size
        recorded for a part can tell."""
        with self.assertRaisesRegex(aea.ArchiveError, "checksum"):
            aea.decrypt(ab.build(b"plain text " * 100, fault="checksum"),
                        ab.KEY)
        with self.assertRaisesRegex(aea.ArchiveError, "wrong size"):
            aea.decrypt(ab.build(b"plain text " * 100, fault="size",
                                 compression="z"), ab.KEY)

    def test_a_short_file(self):
        for size in (3, 11, 12, 40, 100, 300, len(self.data) // 2):
            with self.subTest(size):
                with self.assertRaises(aea.ArchiveError):
                    aea.decrypt(self.data[:size], ab.KEY)

    def test_profiles_that_need_something_other_than_a_key(self):
        for profile in (0, 3, 4, 5):
            data = bytearray(self.data)
            data[4:7] = profile.to_bytes(3, "little")
            with self.subTest(profile):
                with self.assertRaisesRegex(aea.ArchiveError, "profile"):
                    aea.decrypt(bytes(data), ab.KEY)

    def test_lzfse_needs_its_package_and_says_so(self):
        # an archive claiming LZFSE: the segments here were not compressed
        # that way, so only the message matters
        with mock.patch.dict("sys.modules", {"liblzfse": None}):
            with self.assertRaisesRegex(aea.ArchiveError, "pyliblzfse"):
                aea._decompress("e", b"data", 10)
        with self.assertRaisesRegex(aea.ArchiveError, "not supported"):
            aea._decompress("?", b"data", 10)

    def test_a_damaged_compressed_part(self):
        with self.assertRaisesRegex(aea.ArchiveError, "damaged"):
            aea._decompress("z", b"not zlib", 10)
        with self.assertRaisesRegex(aea.ArchiveError, "damaged"):
            aea._decompress("x", b"not lzma", 10)


class KeyTests(unittest.TestCase):
    def test_the_key_in_the_database(self):
        blob = archive({"$class": "HKSymmetricKey", "sym_key": ab.KEY})
        self.assertEqual(aea.symmetric_key(blob), ab.KEY)

    def test_what_is_not_a_key(self):
        for blob in (b"", b"junk", b"bplist00", None,
                     archive({"$class": "X", "sym_key": b"short"}),
                     archive({"$class": "X", "other": ab.KEY}),
                     archive([1, 2])):
            with self.subTest(blob):
                self.assertIsNone(aea.symmetric_key(blob))


if __name__ == "__main__":
    unittest.main()
