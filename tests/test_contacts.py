# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reading and exporting the address book."""

import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from ios_apps import contacts as ct
from ios_apps import contacts_export as cx
from ios_apps.common import APPLE_EPOCH
from tests import fixture_contacts as fcn
from tests.fixture_apps import database_bytes


def connect(testcase, builder=fcn.build):
    folder = tempfile.mkdtemp(prefix="ibe-contacts-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, "AddressBook.sqlitedb")
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


class ContactsCase(unittest.TestCase):
    def setUp(self):
        self.reader = ct.ContactsReader(connect(self))
        self.contacts = self.reader.contacts()
        self.by_name = {c.display_name: c for c in self.contacts}


class HelperTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(ct.clean_label("_$!<Mobile>!$_"), "Mobile")
        self.assertEqual(ct.clean_label("_$!<HomeFAX>!$_"), "HomeFAX")
        self.assertEqual(ct.clean_label("Mother's mobile"), "Mother's mobile")
        self.assertEqual(ct.clean_label(None), "")
        self.assertEqual(ct.clean_label("  iPhone "), "iPhone")

    def test_birthdays(self):
        cases = {
            fcn.apple_seconds(1990, 5, 17): "1990-05-17",
            fcn.apple_seconds(2001, 1, 1) + 1: "2001-01-01",
            "1985-12-01 00:00:00 +0000": "1985-12-01",
            "--06-30": "--06-30",
            "1985-12-01": "1985-12-01",
            str(fcn.apple_seconds(2015, 8, 9)): "2015-08-09",
            "": "", None: "", "soon": "", 0: "",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(ct.format_birthday(value), expected)

    def test_an_absurd_timestamp_is_not_a_crash(self):
        self.assertEqual(ct.format_birthday(1e300), "")

    def test_addresses(self):
        address = ct.Address("Home", "1 Main St", "Springfield", "IL",
                             "62701", "United States")
        self.assertEqual(address.lines, ["1 Main St", "Springfield IL 62701",
                                         "United States"])
        self.assertEqual(str(address),
                         "1 Main St, Springfield IL 62701, United States")
        self.assertEqual(ct.Address(city="Naples").lines, ["Naples"])
        self.assertEqual(ct.Address().lines, [])


class ReaderTests(ContactsCase):
    def test_display_names(self):
        self.assertEqual(sorted(self.by_name), sorted([
            "Alice Example", "Bob Sample", "Pizza Place", "Mum",
            "555-010-6666", "Zed Q Zebra", "Sam Smith, Jr.", "Orphan"]))

    def test_order_by_last_name_then_company_then_nickname(self):
        self.assertEqual([c.display_name for c in self.contacts], [
            "Alice Example", "Mum", "Orphan", "Pizza Place", "Bob Sample",
            "Sam Smith, Jr.", "Zed Q Zebra", "555-010-6666"])

    def test_order_by_first_name(self):
        names = [c.display_name for c in self.reader.contacts(by="first")]
        self.assertEqual(names, [
            "Alice Example", "Bob Sample", "Mum", "Orphan", "Pizza Place",
            "Sam Smith, Jr.", "Zed Q Zebra", "555-010-6666"])

    def test_contacts_with_no_name_at_all_come_last(self):
        self.assertEqual(self.contacts[-1].display_name, "555-010-6666")

    def test_phones_and_emails_with_clean_labels(self):
        alice = self.by_name["Alice Example"]
        self.assertEqual(alice.phones, [("Mobile", "(555) 010-1234"),
                                        ("Work", "+1 555 010 0000")])
        self.assertEqual(alice.emails, [("Work", "alice@example.com")])
        self.assertEqual(self.by_name["Bob Sample"].phones,
                         [("iPhone", "+1 555 010 5678")])
        self.assertEqual(self.by_name["Mum"].phones,
                         [("Mother's mobile", "+44 20 7946 0000")])
        self.assertEqual(self.by_name["555-010-6666"].phones,
                         [("", "555-010-6666")])

    def test_postal_addresses(self):
        alice = self.by_name["Alice Example"]
        (address,) = alice.addresses
        self.assertEqual((address.label, address.street, address.city,
                          address.state, address.zip, address.country),
                         ("Home", "1 Main St", "Springfield", "IL", "62701",
                          "United States"))
        (partial,) = self.by_name["Pizza Place"].addresses
        self.assertEqual(partial.lines, ["9 Oven Rd", "Naples"])

    def test_websites_related_names_dates_and_messaging(self):
        self.assertEqual(self.by_name["Alice Example"].urls,
                         [("HomePage", "https://example.com/alice")])
        zed = self.by_name["Zed Q Zebra"]
        self.assertEqual(zed.related, [("Spouse", "Alice Example")])
        self.assertEqual(zed.dates, [("Anniversary", "2015-08-09")])
        self.assertEqual(zed.messaging, [("Skype", "zed.zebra")])

    def test_name_parts_company_and_notes(self):
        zed = self.by_name["Zed Q Zebra"]
        self.assertEqual((zed.prefix, zed.first, zed.middle, zed.last,
                          zed.suffix, zed.job_title),
                         ("Dr.", "Zed", "Q", "Zebra", "Jr.", "Zookeeper"))
        self.assertTrue(self.by_name["Pizza Place"].is_company)
        self.assertFalse(self.by_name["Alice Example"].is_company)
        alice = self.by_name["Alice Example"]
        self.assertEqual((alice.organization, alice.department),
                         ("Example Corp", "Research"))
        self.assertEqual(alice.note, "Met at the conference.\nLikes tea.")
        self.assertEqual(self.by_name["Bob Sample"].nickname, "Bobby")

    def test_birthdays_in_any_stored_form(self):
        self.assertEqual(self.by_name["Alice Example"].birthday, "1990-05-17")
        self.assertEqual(self.by_name["Bob Sample"].birthday, "1985-12-01")
        self.assertEqual(self.by_name["Zed Q Zebra"].birthday, "--06-30")
        self.assertEqual(self.by_name["Mum"].birthday, "")

    def test_dates_of_creation_and_change(self):
        alice = self.by_name["Alice Example"]
        self.assertEqual(alice.created, 700_000_000 + APPLE_EPOCH)
        self.assertEqual(alice.modified, 777_000_000 + APPLE_EPOCH)
        self.assertIsNone(self.by_name["Mum"].created)

    def test_empty_values_and_values_of_nobody_are_ignored(self):
        self.assertEqual(self.by_name["Sam Smith, Jr."].phones, [])
        total = sum(len(c.phones) for c in self.contacts)
        self.assertEqual(total, 2 + 1 + 1 + 1 + 1)       # not the 999 one

    def test_search(self):
        found = lambda text: sorted(c.display_name for c in
                                    ct.search_contacts(self.contacts, text))
        self.assertEqual(found("alice"), ["Alice Example", "Zed Q Zebra"])
        self.assertEqual(found("5550101234"), ["Alice Example"])
        self.assertEqual(found("springfield"), ["Alice Example"])
        self.assertEqual(found("TEA"), ["Alice Example"])
        self.assertEqual(found("zebra zookeeper"), ["Zed Q Zebra"])
        self.assertEqual(found("pizza oven"), ["Pizza Place"])
        self.assertEqual(found("bobby"), ["Bob Sample"])
        self.assertEqual(found("friend@example"), ["Bob Sample"])
        self.assertEqual(found("nobody"), [])
        self.assertEqual(len(found("")), len(self.contacts))
        self.assertEqual(found("442079460000"), ["Mum"])

    def test_the_search_text_has_no_empty_noise(self):
        self.assertNotIn("None", self.by_name["Mum"].search_text)


class SchemaTests(unittest.TestCase):
    def test_a_book_with_only_names(self):
        def build(conn):
            conn.execute("CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, "
                         "First TEXT, Last TEXT)")
            conn.execute("INSERT INTO ABPerson VALUES (1, 'Ann', 'Onymous')")
            conn.commit()

        (contact,) = ct.ContactsReader(connect(self, build)).contacts()
        self.assertEqual(contact.display_name, "Ann Onymous")
        self.assertEqual(contact.phones, [])

    def test_no_people_table_means_no_contacts(self):
        def build(conn):
            conn.execute("CREATE TABLE other (x)")
            conn.commit()

        self.assertEqual(ct.ContactsReader(connect(self, build)).contacts(),
                         [])

    def test_a_file_that_is_not_a_database_raises(self):
        folder = tempfile.mkdtemp(prefix="ibe-contacts-")
        self.addCleanup(shutil.rmtree, folder, True)
        junk = os.path.join(folder, "junk.sqlitedb")
        with open(junk, "wb") as handle:
            handle.write(b"this is not a database")
        broken = sqlite3.connect(junk)
        self.addCleanup(broken.close)
        with self.assertRaises(sqlite3.DatabaseError):
            ct.ContactsReader(broken).contacts()


def unfold(raw):
    return raw.replace("\r\n ", "")


def cards(text):
    """``[[line, ...], ...]`` for the vCards in *text* (unfolded)."""
    result, current = [], None
    for line in unfold(text).split("\r\n"):
        if line == "BEGIN:VCARD":
            current = []
        elif line == "END:VCARD":
            result.append(current)
            current = None
        elif current is not None:
            current.append(line)
    assert current is None
    return result


class VcardTests(ContactsCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="ibe-contactsx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def card_of(self, name):
        return cards("".join(
            line + "\r\n" for line in cx.vcard(self.by_name[name])))[0]

    def test_a_full_card(self):
        card = self.card_of("Alice Example")
        self.assertEqual(card[0], "VERSION:3.0")
        for expected in (
                "N:Example;Alice;;;", "FN:Alice Example",
                "ORG:Example Corp;Research", "TITLE:Engineer",
                "TEL;TYPE=CELL:(555) 010-1234", "TEL;TYPE=WORK:+1 555 010 0000",
                "EMAIL;TYPE=INTERNET;TYPE=WORK:alice@example.com",
                "ADR;TYPE=HOME:;;1 Main St;Springfield;IL;62701;United States",
                "URL:https://example.com/alice", "BDAY:1990-05-17",
                "NOTE:Met at the conference.\\nLikes tea."):
            with self.subTest(line=expected):
                self.assertIn(expected, card)
        rev = next(l for l in card if l.startswith("REV:"))
        self.assertRegex(rev, r"^REV:\d{8}T\d{6}Z$")

    def test_names_with_all_their_parts(self):
        self.assertIn("N:Zebra;Zed;Q;Dr.;Jr.", self.card_of("Zed Q Zebra"))

    def test_a_birthday_without_a_year_is_left_out(self):
        card = self.card_of("Zed Q Zebra")
        self.assertFalse([l for l in card if l.startswith("BDAY")])
        bob = self.card_of("Bob Sample")
        self.assertIn("BDAY:1985-12-01", bob)

    def test_company_nickname_and_custom_labels(self):
        pizza = self.card_of("Pizza Place")
        self.assertIn("X-ABShowAs:COMPANY", pizza)
        self.assertIn("FN:Pizza Place", pizza)
        self.assertIn("TEL;TYPE=MAIN:555-010-7777", pizza)
        self.assertIn("NICKNAME:Bobby", self.card_of("Bob Sample"))
        mum = self.card_of("Mum")
        self.assertIn("item1.TEL:+44 20 7946 0000", mum)
        self.assertIn("item1.X-ABLabel:Mother's mobile", mum)
        bob = self.card_of("Bob Sample")
        self.assertIn("TEL;TYPE=CELL;TYPE=IPHONE:+1 555 010 5678", bob)

    def test_related_names_dates_and_messaging(self):
        zed = self.card_of("Zed Q Zebra")
        self.assertIn("item1.X-ABRELATEDNAMES:Alice Example", zed)
        self.assertIn("item1.X-ABLabel:Spouse", zed)
        self.assertIn("item2.X-ABDATE:2015-08-09", zed)
        self.assertIn("item2.X-ABLabel:Anniversary", zed)
        self.assertIn("X-SKYPE:zed.zebra", zed)

    def test_special_characters_are_escaped(self):
        card = self.card_of("Sam Smith, Jr.")
        self.assertIn("N:Smith\\, Jr.;Sam;;;", card)
        self.assertIn("FN:Sam Smith\\, Jr.", card)
        note = next(l for l in card if l.startswith("NOTE:"))
        self.assertEqual(note, "NOTE:" + cx.escape_text(fcn.LONG_NOTE))
        self.assertIn("\\n", note)
        self.assertIn("\\;", note)
        self.assertIn("\\,", note)
        self.assertIn("\\\\", note)
        self.assertNotIn("\n", note)
        self.assertIn("日本語", note)

    def test_lines_are_folded_to_75_bytes_without_cutting_characters(self):
        lines = cx.vcard(self.by_name["Sam Smith, Jr."])
        self.assertTrue(any(l.startswith(" ") for l in lines))
        for line in lines:
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)
        # unfolding gives the whole note back, in whole characters
        text = unfold("\r\n".join(lines))
        self.assertIn("日本語", text)
        self.assertNotIn("�", text)

    def test_folding_never_splits_a_multibyte_character(self):
        for width in range(1, 6):
            line = "X:" + "é" * 40 + "日" * 40 + "\U0001F389" * 20
            pieces = cx.fold(line, 75 - width + 1)
            for piece in pieces:
                piece.encode("utf-8").decode("utf-8")
            self.assertEqual("".join(p[1:] if n else p
                                     for n, p in enumerate(pieces)), line)

    def test_short_lines_are_not_folded(self):
        self.assertEqual(cx.fold("FN:short"), ["FN:short"])
        self.assertEqual(cx.fold("x" * 75), ["x" * 75])
        self.assertEqual(len(cx.fold("x" * 76)), 2)

    def test_the_file(self):
        (path,) = cx.export(self.contacts, "vcf", self.tmp)
        raw = read(path, "rb")
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))    # CRLF only
        self.assertEqual(raw.count(b"BEGIN:VCARD\r\n"), len(self.contacts))
        self.assertEqual(raw.count(b"END:VCARD\r\n"), len(self.contacts))
        self.assertEqual(len(cards(raw.decode("utf-8"))), len(self.contacts))
        self.assertTrue(raw.endswith(b"END:VCARD\r\n"))

    def test_a_contact_with_nothing_still_makes_a_card(self):
        card = cards("".join(l + "\r\n" for l in cx.vcard(ct.Contact(1))))[0]
        self.assertIn("FN:(No name)", card)
        self.assertIn("N:;;;;", card)


class OtherFormatTests(ContactsCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="ibe-contactsx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_csv(self):
        (path,) = cx.export(self.contacts, "csv", self.tmp)
        raw = read(path, "rb")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),
                                           newline="")))
        self.assertEqual(rows[0], list(cx.CSV_COLUMNS))
        self.assertEqual(len(rows), len(self.contacts) + 1)
        alice = dict(zip(rows[0], rows[1]))
        self.assertEqual(alice["name"], "Alice Example")
        self.assertEqual(alice["phones"],
                         "Mobile: (555) 010-1234; Work: +1 555 010 0000")
        self.assertEqual(alice["addresses"],
                         "Home: 1 Main St, Springfield IL 62701, "
                         "United States")
        self.assertEqual(alice["note"], "Met at the conference.\nLikes tea.")
        self.assertEqual(alice["birthday"], "1990-05-17")
        unnamed = dict(zip(rows[0], rows[-1]))
        self.assertEqual(unnamed["phones"], "555-010-6666")

    def test_json(self):
        (path,) = cx.export(self.contacts, "json", self.tmp)
        data = json.loads(read(path, encoding="utf-8"))
        self.assertEqual(len(data), len(self.contacts))
        alice = data[0]
        self.assertEqual(alice["name"], "Alice Example")
        self.assertEqual(alice["phones"][0],
                         {"label": "Mobile", "value": "(555) 010-1234"})
        self.assertEqual(alice["addresses"][0]["city"], "Springfield")
        self.assertIsNone(alice["nickname"])
        self.assertRegex(alice["created"], r"\+00:00$")
        pizza = next(d for d in data if d["name"] == "Pizza Place")
        self.assertTrue(pizza["is_company"])

    def test_text(self):
        (path,) = cx.export(self.contacts, "txt", self.tmp)
        text = read(path, encoding="utf-8")
        self.assertIn("Alice Example\nExample Corp - Research"[:13], text)
        self.assertIn("Mobile: (555) 010-1234", text)
        self.assertIn("Home: 1 Main St, Springfield IL 62701, United States",
                      text)
        self.assertIn("Note: Met at the conference.\n      Likes tea.", text)
        self.assertEqual(text.count("\n\n"), len(self.contacts) - 1)

    def test_html_is_escaped(self):
        hostile = ct.Contact(1, first="<script>alert(1)</script>",
                             note="<b>bold</b> & \"quotes\"\nline two",
                             phones=[("<x>", "1&2")])
        (path,) = cx.export([hostile] + self.contacts, "html", self.tmp)
        page = read(path, encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>bold", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; &quot;quotes&quot;"
                      "<br>line two", page)
        self.assertIn("Alice Example", page)
        self.assertIn(f"{len(self.contacts) + 1} contacts", page)

    def test_every_format_works_for_no_contacts(self):
        for fmt in cx.FORMATS:
            with self.subTest(fmt=fmt):
                (path,) = cx.export([], fmt, os.path.join(self.tmp, fmt))
                self.assertTrue(os.path.isfile(path))

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            cx.export(self.contacts, "doc", self.tmp)


if __name__ == "__main__":
    unittest.main()
