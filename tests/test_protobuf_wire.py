# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""ios_apps/protobuf_wire.py: reading protocol buffer messages without a
schema, from invented messages."""

import struct
import unittest

from ios_apps import protobuf_wire as pb
from tests.protobuf_builder import field, message, nested, varint


class ParseTests(unittest.TestCase):
    def test_the_kinds_of_field(self):
        data = message((1, 150), (2, "text"), (3, 2.5), (4, b"\x00\x01"))
        self.assertEqual(pb.parse(data), [
            (1, pb.VARINT, 150), (2, pb.LENGTH_DELIMITED, b"text"),
            (3, pb.FIXED64, 2.5), (4, pb.LENGTH_DELIMITED, b"\x00\x01")])

    def test_a_published_example(self):
        # the protobuf documentation's example: field 1 = 150 is 08 96 01
        self.assertEqual(varint(150), b"\x96\x01")
        self.assertEqual(pb.parse(b"\x08\x96\x01"), [(1, pb.VARINT, 150)])
        self.assertEqual(pb.parse(b"\x12\x07testing"),
                         [(2, pb.LENGTH_DELIMITED, b"testing")])

    def test_a_32_bit_field_is_a_float(self):
        data = varint(5 << 3 | 5) + struct.pack("<f", 1.5)
        self.assertEqual(pb.parse(data), [(5, pb.FIXED32, 1.5)])

    def test_big_numbers_and_empty_messages(self):
        self.assertEqual(pb.parse(message((1, 1 << 40))),
                         [(1, pb.VARINT, 1 << 40)])
        self.assertEqual(pb.parse(b""), [])

    def test_what_is_not_a_message_is_refused(self):
        for data in (b"\x00\x01",                    # field number 0
                     b"\x08",                        # a value is missing
                     b"\x0a\x05ab",                  # a length too long
                     b"\x0b\x01",                    # a group (not read)
                     b"\x09\x00\x00",                # a short 64-bit value
                     varint(5000 << 3) + b"\x01",    # a field number too large
                     b"\x08" + b"\xff" * 12 + b"\x01",  # a number too long
                     b"\x08" + b"\xff" * 12):       # one that never ends
            with self.subTest(data):
                self.assertIsNone(pb.parse(data))


class ReachTests(unittest.TestCase):
    def setUp(self):
        self.data = message(
            (1, message((2, message((3, "deep"), (4, 7), (5, 1.25))))),
            (1, message((2, message((3, "again"))))),
            (6, "top"), (7, b"\xff\xfe"))

    def test_text_at_a_path(self):
        self.assertEqual(pb.texts_at(self.data, (1, 2, 3)), ["deep", "again"])
        self.assertEqual(pb.texts_at(self.data, (6,)), ["top"])

    def test_nothing_there(self):
        self.assertEqual(pb.texts_at(self.data, (9,)), [])
        self.assertEqual(pb.texts_at(self.data, (1, 9, 3)), [])
        self.assertEqual(pb.texts_at(self.data, ()), [])
        self.assertEqual(pb.texts_at(b"\x00", (1,)), [])

    def test_bytes_that_are_not_text_are_not_text(self):
        self.assertEqual(pb.texts_at(self.data, (7,)), [])
        self.assertFalse(pb.is_text(b"\xff\xfe"))
        self.assertFalse(pb.is_text(b""))
        self.assertFalse(pb.is_text(b"a\x00b"))
        self.assertTrue(pb.is_text("na\u00efve\nline".encode()))

    def test_numbers_at_a_path(self):
        self.assertEqual(pb.numbers_at(self.data, (1, 2, 4)), [7])
        self.assertEqual(pb.numbers_at(self.data, (1, 2, 5), pb.FIXED64),
                         [1.25])
        self.assertEqual(pb.numbers_at(self.data, (1, 2, 4), pb.FIXED64), [])
        self.assertEqual(pb.numbers_at(self.data, ()), [])

    def test_messages_at_follows_every_repeat(self):
        self.assertEqual(len(pb.messages_at(self.data, (1,))), 2)
        self.assertEqual(len(pb.messages_at(self.data, (1, 2))), 2)
        self.assertEqual(pb.messages_at(self.data, ()), [self.data])

    def test_a_number_where_a_message_is_expected_is_not_followed(self):
        data = message((1, 5), (1, message((2, "inside"))), (1, 9))
        self.assertEqual(pb.texts_at(data, (1, 2)), ["inside"])
        self.assertEqual(len(pb.messages_at(data, (1,))), 1)
        self.assertEqual(pb.texts_at(data, (1, 2, 3)), [])

    def test_nested_builds_what_messages_at_follows(self):
        leaf = field(9, "x")
        built = nested((1, 2, 3), leaf)
        self.assertEqual(pb.texts_at(built, (1, 2, 3, 9)), ["x"])


if __name__ == "__main__":
    unittest.main()
