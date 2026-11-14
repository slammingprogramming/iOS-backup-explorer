# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The small helpers the panels share."""

import unittest

from ui_util import count_text


class CountTextTests(unittest.TestCase):
    def test_one_is_singular_and_the_rest_are_plural(self):
        self.assertEqual(count_text(0, "item"), "0 items")
        self.assertEqual(count_text(1, "item"), "1 item")
        self.assertEqual(count_text(2, "item"), "2 items")

    def test_thousands_are_separated(self):
        self.assertEqual(count_text(54101, "message"), "54,101 messages")
        self.assertEqual(count_text(1000, "note"), "1,000 notes")

    def test_a_plural_that_is_not_an_s(self):
        self.assertEqual(count_text(1, "entry", "entries"), "1 entry")
        self.assertEqual(count_text(3, "entry", "entries"), "3 entries")

    def test_a_longer_noun_phrase(self):
        self.assertEqual(count_text(1, "matching note"), "1 matching note")
        self.assertEqual(count_text(12, "matching note"), "12 matching notes")


if __name__ == "__main__":
    unittest.main()
