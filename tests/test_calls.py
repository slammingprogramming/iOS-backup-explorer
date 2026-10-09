# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reading and exporting the call history."""

import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from ios_apps import calls as cl
from ios_apps import calls_export as cx
from ios_apps.common import APPLE_EPOCH, ContactBook
from tests import fixture_calls as fc
from tests.fixture_apps import T0, build_addressbook, database_bytes


def connect(testcase, builder):
    folder = tempfile.mkdtemp(prefix="ibe-calls-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, "CallHistory.storedata")
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


def contact_book(testcase):
    conn = connect(testcase, build_addressbook)
    return ContactBook.from_connection(conn)


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


class CallsCase(unittest.TestCase):
    def setUp(self):
        self.reader = cl.CallsReader(connect(self, fc.build),
                                     contact_book(self))
        self.calls = self.reader.calls()
        self.by_id = {c.rowid: c for c in self.calls}


class ReaderTests(CallsCase):
    def test_newest_first(self):
        self.assertEqual([c.rowid for c in self.calls],
                         [8, 7, 6, 5, 4, 3, 2, 1, 9])

    def test_directions(self):
        got = {pk: c.direction for pk, c in self.by_id.items()}
        self.assertEqual(got, {1: "outgoing", 2: "incoming", 3: "missed",
                               4: "outgoing", 5: "incoming", 6: "missed",
                               7: "outgoing", 8: "incoming", 9: "incoming"})

    def test_an_unanswered_outgoing_call_is_not_called_missed(self):
        self.assertEqual(self.by_id[7].direction_label, "Outgoing")
        self.assertEqual(self.by_id[7].duration, 0)

    def test_kinds(self):
        got = {pk: c.kind for pk, c in self.by_id.items()}
        self.assertEqual(got[1], "phone")
        self.assertEqual(got[4], "facetime_video")
        self.assertEqual(got[5], "facetime_audio")
        self.assertEqual(self.by_id[4].kind_label, "FaceTime video")
        self.assertEqual(self.by_id[5].service, "com.apple.FaceTime")

    def test_names_come_from_the_address_book_then_the_phones_cache(self):
        names = {pk: c.display_name for pk, c in self.by_id.items()}
        self.assertEqual(names[1], "Alice Example")
        self.assertEqual(names[2], "Bob Sample")       # number stored as bytes
        self.assertEqual(names[3], "Spam Likely")      # only in the cache
        self.assertEqual(names[4], "Bob Sample")       # by email address
        self.assertEqual(names[7], "Pizza Place")      # number formatted oddly
        self.assertEqual(names[8], "+15550106666")     # a contact with no name
        self.assertEqual(names[6], "Unknown caller")   # no number at all

    def test_the_address_book_wins_over_the_cached_name(self):
        reader = cl.CallsReader(connect(self, fc.build), contact_book(self))
        conn = reader.conn
        conn.execute("UPDATE ZCALLRECORD SET ZNAME = 'Old Cached Name' "
                     "WHERE Z_PK = 1")
        reader.calls()
        self.assertEqual(
            next(c for c in reader.calls() if c.rowid == 1).name,
            "Alice Example")

    def test_without_an_address_book_the_cached_name_or_number_is_used(self):
        reader = cl.CallsReader(connect(self, fc.build))
        by_id = {c.rowid: c for c in reader.calls()}
        self.assertEqual(by_id[1].display_name, "+15550101234")
        self.assertEqual(by_id[3].display_name, "Spam Likely")

    def test_dates_durations_places_and_unread(self):
        first = self.by_id[1]
        self.assertEqual(first.when, T0 + APPLE_EPOCH)
        self.assertEqual(first.duration, 125.0)
        self.assertEqual((first.location, first.country),
                         ("Seattle, WA", "us"))
        self.assertEqual(self.by_id[4].duration, 3725.5)
        self.assertEqual([c.rowid for c in self.calls if c.unread], [3])

    def test_search_by_name_number_and_place(self):
        ids = lambda text: sorted(c.rowid for c in self.reader.search(text))
        self.assertEqual(ids("alice"), [1, 5, 9])
        self.assertEqual(ids("ALICE example"), [1, 5, 9])
        self.assertEqual(ids("seattle"), [1])
        self.assertEqual(ids("spam"), [3])
        self.assertEqual(ids("unknown"), [6])
        self.assertEqual(ids("5550105678"), [2])         # the number itself
        self.assertEqual(ids("alice portland"), [9])
        self.assertEqual(ids("nobody at all"), [])
        self.assertEqual(ids(""), sorted(c.rowid for c in self.calls))

    def test_search_digits_ignore_punctuation(self):
        self.assertIn(7, [c.rowid for c in self.reader.search("5550107777")])
        self.assertIn(1, [c.rowid for c in self.reader.search("555010")])

    def test_search_can_be_limited_to_some_calls(self):
        missed = cl.filter_calls(self.calls, direction="missed")
        found = self.reader.search("unknown", missed)
        self.assertEqual([c.rowid for c in found], [6])
        self.assertEqual(self.reader.search("alice", missed), [])

    def test_summary(self):
        totals = cl.summarize(self.calls)
        self.assertEqual(totals["total"], 9)
        self.assertEqual((totals["outgoing"], totals["incoming"],
                          totals["missed"]), (3, 4, 2))
        self.assertEqual(totals["talk_seconds"],
                         125 + 61 + 3725.5 + 30 + 5 + 600)

    def test_filters(self):
        ids = lambda **kw: [c.rowid for c in cl.filter_calls(self.calls, **kw)]
        self.assertEqual(ids(direction="missed"), [6, 3])
        self.assertEqual(ids(kind="facetime"), [5, 4])
        self.assertEqual(ids(kind="facetime_audio"), [5])
        self.assertEqual(ids(kind="phone", direction="outgoing"), [7, 1])
        self.assertEqual(len(ids()), 9)

    def test_decode_address(self):
        self.assertEqual(cl.decode_address(b"+1555"), "+1555")
        self.assertEqual(cl.decode_address(memoryview(b"+1555")), "+1555")
        self.assertEqual(cl.decode_address("+1555\x00 "), "+1555")
        self.assertEqual(cl.decode_address(None), "")
        self.assertEqual(cl.decode_address(b"\xff\xfe1"), "��1")

    def test_kind_and_direction_rules(self):
        self.assertEqual(cl.classify_kind(None, "com.apple.FaceTime"),
                         "facetime_video")
        self.assertEqual(cl.classify_kind(None, ""), "other")
        self.assertEqual(cl.classify_kind(99), "other")
        self.assertEqual(cl.classify_direction(0, 0, 12.0), "incoming")
        self.assertEqual(cl.classify_direction(None, None, 0), "missed")
        self.assertEqual(cl.classify_direction(1, 0, 0), "outgoing")


class SchemaTests(unittest.TestCase):
    def test_a_table_with_only_a_few_columns_still_reads(self):
        def build(conn):
            conn.execute("CREATE TABLE ZCALLRECORD (Z_PK INTEGER PRIMARY KEY, "
                         "ZADDRESS BLOB, ZDATE TIMESTAMP)")
            conn.execute("INSERT INTO ZCALLRECORD VALUES (1, ?, 1000)",
                         (b"+155",))
            conn.commit()

        (call,) = cl.CallsReader(connect(self, build)).calls()
        self.assertEqual((call.address, call.direction, call.kind),
                         ("+155", "missed", "other"))
        self.assertEqual(call.when, 1000 + APPLE_EPOCH)

    def test_no_call_table_means_no_calls(self):
        def build(conn):
            conn.execute("CREATE TABLE other (x)")
            conn.commit()

        self.assertEqual(cl.CallsReader(connect(self, build)).calls(), [])


class ExportTests(CallsCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="ibe-callsx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_csv(self):
        (path,) = cx.export(self.calls, "csv", self.tmp)
        raw = read(path, "rb")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),
                                           newline="")))
        self.assertEqual(rows[0], list(cx.CSV_COLUMNS))
        self.assertEqual(len(rows), 10)
        alice = rows[1:][-2]            # call 1 (the oldest but one)
        record = dict(zip(rows[0], alice))
        self.assertEqual((record["name"], record["number"],
                          record["direction"], record["type"]),
                         ("Alice Example", "+15550101234", "Outgoing",
                          "Phone"))
        self.assertEqual((record["duration_seconds"], record["duration"],
                          record["location"]), ("125", "2:05", "Seattle, WA"))
        facetime = next(dict(zip(rows[0], r)) for r in rows[1:]
                        if r[5] == "FaceTime video")
        self.assertEqual(facetime["duration"], "1:02:06")

    def test_json(self):
        (path,) = cx.export(self.calls, "json", self.tmp)
        data = json.loads(read(path, encoding="utf-8"))
        self.assertEqual(len(data), 9)
        first = data[-2]
        self.assertEqual((first["direction"], first["type"], first["number"]),
                         ("outgoing", "phone", "+15550101234"))
        unknown = next(d for d in data if d["id"] == 6)
        self.assertIsNone(unknown["number"])
        self.assertIsNone(unknown["name"])
        self.assertRegex(first["date"], r"^\d{4}-\d\d-\d\dT.*\+00:00$")

    def test_text(self):
        (path,) = cx.export(self.calls, "txt", self.tmp)
        lines = read(path, encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 9)
        alice = next(l for l in lines if "Seattle" in l)
        self.assertIn("Outgoing", alice)
        self.assertIn("Alice Example (+15550101234)", alice)
        self.assertIn("2:05", alice)

    def test_html_is_escaped_and_marks_missed_calls(self):
        conn = self.reader.conn
        conn.execute("UPDATE ZCALLRECORD SET ZNAME = '<script>alert(1)</script>"
                     "&' WHERE Z_PK = 3")
        calls = cl.CallsReader(conn, contact_book(self)).calls()
        (path,) = cx.export(calls, "html", self.tmp)
        page = read(path, encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;&amp;", page)
        self.assertEqual(page.count("class=\"missed\""), 2)
        self.assertIn("9 calls", page)
        self.assertIn("2 missed", page)
        self.assertIn("Alice Example", page)

    def test_only_the_calls_given_are_written(self):
        (path,) = cx.export(cl.filter_calls(self.calls, direction="missed"),
                            "csv", self.tmp)
        self.assertEqual(len(read(path, encoding="utf-8-sig").splitlines()), 3)

    def test_an_empty_list_still_makes_a_valid_file(self):
        for fmt in cx.FORMATS:
            with self.subTest(fmt=fmt):
                (path,) = cx.export([], fmt, os.path.join(self.tmp, fmt))
                self.assertTrue(os.path.isfile(path))
        self.assertEqual(json.loads(read(os.path.join(self.tmp, "json",
                                                      "calls.json"))), [])

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            cx.export(self.calls, "doc", self.tmp)


if __name__ == "__main__":
    unittest.main()
