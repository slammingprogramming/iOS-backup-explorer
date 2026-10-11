# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The keychain reader (no window): what is listed, how, and what is not."""

import os
import plistlib
import shutil
import tempfile
import unittest

from ios_apps import keychain as kn
from ios_apps import keychain_crypto as kc
from tests import fixture_keychain as fk


def keys():
    return kc.ClassKeys(fk.CLASS_KEYS)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.data = kn.read_plist(fk.keychain_plist())
        self.sets = {d.key: d for d in kn.datasets_for(self.data, keys())}

    def rows(self, key="passwords"):
        return self.sets[key].rows

    def row(self, where):
        return next(r for r in self.rows() if r["where"] == where)

    def test_the_tables(self):
        self.assertEqual(list(self.sets), ["passwords", "certificates",
                                           "keys", "unreadable"])

    def test_the_passwords_listed(self):
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(
            sorted(r["where"] for r in self.rows()),
            ["Cafe Wifi", "Example Mail", "Notes token",
             "https://www.example.com/login",
             "imaps://imap.example.org:993"])

    def test_a_wifi_password(self):
        row = self.row("Cafe Wifi")
        self.assertEqual(row["kind"], "Wi-Fi password")
        self.assertEqual(row["password"], "espresso2024")
        self.assertEqual(row["account"], "")
        self.assertEqual(row["access"], "After first unlock")

    def test_a_website_password(self):
        row = self.row("https://www.example.com/login")
        self.assertEqual(row["kind"], "Website or server password")
        self.assertEqual(row["account"], "taylor")
        self.assertEqual(row["password"], "s3cret! ✓")
        self.assertEqual(row["group"], "com.apple.cfnetwork")

    def test_a_port_is_shown_only_when_it_is_not_the_usual(self):
        self.assertIn("imaps://imap.example.org:993",
                      [r["where"] for r in self.rows()])
        self.assertNotIn(":443", self.row("https://www.example.com/login")
                         ["where"])

    def test_a_password_that_is_text_stays_text(self):
        self.assertEqual(self.row("Example Mail")["password"],
                         "mail password")

    def test_data_that_is_not_text_is_described_not_shown(self):
        self.assertEqual(self.row("Notes token")["password"],
                         "(16 bytes of data)")

    def test_dates_are_unix_seconds(self):
        row = self.row("Cafe Wifi")
        self.assertEqual(row["created"], fk.WHEN.timestamp())
        self.assertEqual(row["modified"], fk.LATER.timestamp())

    def test_deleted_items_are_left_out_and_counted(self):
        self.assertNotIn("Deleted thing", [r["where"] for r in self.rows()])
        self.assertIn("1 deleted", self.sets["passwords"].note)

    def test_certificates_and_keys(self):
        cert, = self.rows("certificates")
        self.assertEqual((cert["label"], cert["size"]),
                         ("Example CA", 21))
        key, = self.rows("keys")
        self.assertEqual(key["label"], "Example key")
        self.assertEqual(key["size"], 17)

    def test_what_cannot_be_opened_is_counted_and_explained(self):
        rows = self.rows("unreadable")
        self.assertEqual(sum(r["count"] for r in rows), 2)
        self.assertTrue(all(r["device_only"] for r in rows))
        self.assertTrue(all("phone" in r["reason"] for r in rows))
        self.assertEqual(sorted(r["access"] for r in rows), [
            "After first unlock, this device only",
            "When unlocked, this device only"])

    def test_the_details_show_every_attribute(self):
        text = self.sets["passwords"].details(self.row("Cafe Wifi"))
        for expected in ("Wi-Fi password", "svce: AirPort", "acct: Cafe Wifi",
                         "agrp: apple", "Value: espresso2024"):
            self.assertIn(expected, text)
        self.assertIn("2024-03-05", text)           # a date, written out
        binary = self.sets["passwords"].details(self.row("Notes token"))
        self.assertIn(bytes(range(1, 17)).hex(), binary)
        self.assertIn("16 bytes", binary)

    def test_the_search_finds_passwords_and_places(self):
        table = self.sets["passwords"]
        self.assertEqual(len(table.search(table.rows, "espresso2024")), 1)
        self.assertEqual(len(table.search(table.rows, "example.com")), 2)
        self.assertEqual(len(table.search(table.rows, "taylor")), 2)

    def test_nothing_is_listed_twice(self):
        keys_ = [(r["kind"], r["where"], r["account"]) for r in self.rows()]
        self.assertEqual(len(keys_), len(set(keys_)))


class OddAttributesTests(unittest.TestCase):
    """What a real keychain does: names stored as bytes, the protocol as the
    number of its four letters."""

    def rows(self, items):
        data = kn.read_plist(fk.keychain_plist(items))
        table, = kn.datasets_for(data, keys())
        return table.rows

    def test_the_protocol_as_a_number_or_as_text(self):
        number = int.from_bytes(b"htps", "big")
        rows = self.rows([
            ("inet", {"srvr": "a.example.com", "ptcl": number, "port": 443,
                      "path": "", "acct": "x", "v_Data": b"p"}, 6),
            ("inet", {"srvr": "b.example.com", "ptcl": "imps", "port": 993,
                      "path": "", "acct": "x", "v_Data": b"p"}, 6),
            ("inet", {"srvr": "c.example.com", "ptcl": 0, "port": 0,
                      "path": "/x", "acct": "x", "v_Data": b"p"}, 6),
            ("inet", {"srvr": "d.example.com", "ptcl": 7, "port": 0,
                      "path": "", "acct": "x", "v_Data": b"p"}, 6)])
        self.assertEqual(sorted(r["where"] for r in rows), [
            "c.example.com/x", "d.example.com", "https://a.example.com",
            "imaps://b.example.com:993"])

    def test_names_stored_as_bytes(self):
        rows = self.rows([
            ("genp", {"svce": b"Some service", "acct": b"an account",
                      "labl": "Label", "v_Data": b"p"}, 6),
            ("genp", {"svce": "Binary", "acct": bytes([0, 255, 7]),
                      "v_Data": b"p"}, 6)])
        by = {r["where"]: r for r in rows}
        self.assertEqual(by["Some service"]["account"], "an account")
        self.assertEqual(by["Binary"]["account"], "00ff07")


class WithoutKeysTests(unittest.TestCase):
    def test_nothing_opens_without_a_key_bag(self):
        data = kn.read_plist(fk.keychain_plist())
        sets = kn.datasets_for(data, None)
        self.assertEqual([d.key for d in sets], ["unreadable"])
        rows = sets[0].rows
        self.assertEqual(sum(r["count"] for r in rows), len(fk.ITEMS))
        reasons = {r["reason"] for r in rows}
        self.assertIn("the backup holds no key for its protection class",
                      reasons)
        self.assertIn("locked to the phone it came from", reasons)

    def test_the_biggest_group_that_cannot_be_opened_comes_first(self):
        items = [("genp", {"svce": "a", "v_Data": b"x"}, 10)] * 3 \
            + [("inet", {"srvr": "b", "v_Data": b"y"}, 9)]
        data = kn.read_plist(fk.keychain_plist(items))
        table, = kn.datasets_for(data, keys())
        self.assertEqual([r["count"] for r in table.rows], [3, 1])

    def test_a_key_for_one_class_opens_only_those_items(self):
        data = kn.read_plist(fk.keychain_plist())
        sets = {d.key: d for d in kn.datasets_for(
            data, kc.ClassKeys({6: fk.CLASS_KEYS[6]}))}
        self.assertEqual(sorted(r["where"] for r in sets["passwords"].rows),
                         ["Example Mail", "https://www.example.com/login"])
        self.assertNotIn("certificates", sets)

    def test_a_wrong_key_makes_the_items_unreadable_not_wrong(self):
        data = kn.read_plist(fk.keychain_plist())
        wrong = kc.ClassKeys({n: bytes([200 + n]) * 32 for n in (6, 7, 8)})
        sets = kn.datasets_for(data, wrong)
        self.assertEqual([d.key for d in sets], ["unreadable"])
        self.assertIn("its key could not be unwrapped",
                      {r["reason"] for r in sets[0].rows})


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-keychain-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_path_and_bytes_read_alike(self):
        path = os.path.join(self.tmp, "keychain-backup.plist")
        with open(path, "wb") as handle:
            handle.write(fk.keychain_plist())
        self.assertEqual(kn.read_plist(path).keys(),
                         kn.read_plist(fk.keychain_plist()).keys())
        reader = kn.KeychainReader(path, keys())
        self.assertEqual(reader.datasets()[0].key, "passwords")

    def test_a_file_that_is_not_a_keychain(self):
        path = os.path.join(self.tmp, "x.plist")
        with open(path, "wb") as handle:
            handle.write(plistlib.dumps([1, 2, 3]))
        with self.assertRaises(ValueError):
            kn.read_plist(path)
        with self.assertRaises(ValueError):
            kn.read_plist(b"not a plist at all")

    def test_odd_content_is_survived(self):
        data = {"genp": [None, {}, {"v_Data": b"short"}, "text"],
                "inet": None, "cert": [], "keys": [{"v_Data": 5}]}
        sets = kn.datasets_for(data, keys())
        self.assertEqual([d.key for d in sets], ["unreadable"])
        self.assertEqual(sum(r["count"] for r in sets[0].rows), 5)

    def test_counts_without_opening(self):
        data = kn.read_plist(fk.keychain_plist())
        self.assertEqual(kn.counts(data),
                         {"genp": 5, "inet": 3, "cert": 1, "keys": 1})

    def test_an_empty_keychain(self):
        self.assertEqual(kn.datasets_for({}, keys()), [])


class SecretTests(unittest.TestCase):
    def test_text_and_not_text(self):
        self.assertEqual(kn.secret_text("abc"), "abc")
        self.assertEqual(kn.secret_text(b"abc\n"), "abc\n")
        self.assertIsNone(kn.secret_text(b"\x00\x01"))
        self.assertIsNone(kn.secret_text(b"\xff\xfe"))
        self.assertIsNone(kn.secret_text(None))
        self.assertIsNone(kn.secret_text(12))


if __name__ == "__main__":
    unittest.main()
