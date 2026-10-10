# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Tables of records (the common shape of the small apps), their export,
the Safari reader, and the keyed-archive reader."""

import csv
import io
import json
import os
import plistlib
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from ios_apps import keyed_archive as ka
from ios_apps import records as rc
from ios_apps import records_export as rx
from ios_apps import safari as sf
from ios_apps.common import APPLE_EPOCH
from tests import fixture_safari as fs
from tests.fixture_apps import T0, database_bytes


def connect(testcase, builder, name="db.sqlite"):
    folder = tempfile.mkdtemp(prefix="ibe-rec-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


def slurp(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


def sample():
    columns = [rc.Column("name", "Name", 100),
               rc.Column("when", "When", 100, "date"),
               rc.Column("count", "Count", 60, "number", "e"),
               rc.Column("length", "Length", 60, "duration"),
               rc.Column("size", "Size", 60, "size")]
    rows = [{"name": "banana", "when": 1_700_000_000, "count": 1500,
             "length": 65, "size": 2048},
            {"name": "Apple", "when": 1_600_000_000, "count": 3,
             "length": 3725, "size": 10},
            {"name": "cherry", "when": None, "count": None, "length": None,
             "size": None},
            {"name": "date <b>", "when": 1_650_000_000, "count": 20,
             "length": 5, "size": 5_000_000}]
    return rc.Dataset("fruit", "Fruit & Veg", columns, rows,
                      sort=("when", True))


class ColumnTests(unittest.TestCase):
    def test_how_values_are_shown(self):
        c = rc.Column
        self.assertEqual(c("a", "A").show("x"), "x")
        self.assertEqual(c("a", "A").show(5), "5")
        self.assertEqual(c("a", "A", kind="number").show(1500), "1,500")
        self.assertEqual(c("a", "A", kind="number").show(2.5), "2.50")
        self.assertEqual(c("a", "A", kind="duration").show(3725), "1:02:05")
        self.assertEqual(c("a", "A", kind="size").show(2048), "2.0 KB")
        self.assertRegex(c("a", "A", kind="date").show(1_700_000_000),
                         r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        for kind in ("text", "date", "number", "duration", "size"):
            self.assertEqual(c("a", "A", kind=kind).show(None), "")
            self.assertEqual(c("a", "A", kind=kind).show(""), "")


class DatasetTests(unittest.TestCase):
    def test_sorting_puts_rows_without_a_value_last_either_way(self):
        data = sample()
        names = lambda key, desc: [r["name"] for r in
                                   data.sorted_rows(data.rows, key, desc)]
        self.assertEqual(names("when", True),
                         ["banana", "date <b>", "Apple", "cherry"])
        self.assertEqual(names("when", False),
                         ["Apple", "date <b>", "banana", "cherry"])
        self.assertEqual(names("count", True)[-1], "cherry")

    def test_text_sorts_ignoring_case(self):
        data = sample()
        names = [r["name"] for r in data.sorted_rows(data.rows, "name", False)]
        self.assertEqual(names, ["Apple", "banana", "cherry", "date <b>"])

    def test_the_default_sort(self):
        data = sample()
        self.assertEqual(data.sorted_rows(data.rows)[0]["name"], "banana")
        plain = rc.Dataset("x", "X", data.columns, data.rows)
        self.assertEqual([r["name"] for r in plain.sorted_rows(plain.rows)],
                         [r["name"] for r in plain.rows])

    def test_mixed_values_do_not_crash_the_sort(self):
        data = sample()
        rows = data.rows + [{"name": "zzz", "count": "many"}]
        self.assertEqual(len(data.sorted_rows(rows, "count", False)), 5)

    def test_search_wants_every_word_and_sees_what_is_shown(self):
        data = sample()
        found = lambda text: [r["name"] for r in data.search(data.rows, text)]
        self.assertEqual(found("apple"), ["Apple"])
        self.assertEqual(found("1,500"), ["banana"])         # as displayed
        self.assertEqual(found("1:02:05 apple"), ["Apple"])
        self.assertEqual(found("apple banana"), [])
        self.assertEqual(len(found("")), 4)
        self.assertEqual(len(found("   ")), 4)

    def test_search_looks_in_the_details_too(self):
        data = sample()
        data.details = lambda row: "extra text " + row["name"].upper()
        self.assertEqual(
            [r["name"] for r in data.search(data.rows, "EXTRA TEXT CHERRY")],
            ["cherry"])

    def test_a_missing_table_gives_no_rows(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(rc.sqlite_rows(conn, "SELECT * FROM nothing"), [])
        self.assertEqual(rc.sqlite_rows(conn, "SELECT 1"), [(1,)])


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-recx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = sample()

    def test_csv(self):
        (path,) = rx.export(self.data, self.data.rows, "csv", self.tmp)
        self.assertEqual(os.path.basename(path), "fruit-&-veg.csv")
        raw = slurp(path, "rb")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),
                                           newline="")))
        self.assertEqual(rows[0], ["Name", "When", "Count", "Length", "Size"])
        self.assertEqual(rows[1][2:], ["1,500", "1:05", "2.0 KB"])
        self.assertEqual(rows[3][1:], ["", "", "", ""])
        self.assertEqual(len(rows), 5)

    def test_json_uses_real_values(self):
        (path,) = rx.export(self.data, self.data.rows, "json", self.tmp)
        data = json.loads(slurp(path, encoding="utf-8"))
        self.assertEqual(data[0]["count"], 1500)
        self.assertEqual(data[0]["length"], 65)
        self.assertEqual(data[0]["when"], datetime.fromtimestamp(
            1_700_000_000, timezone.utc).isoformat(timespec="seconds"))
        self.assertIsNone(data[2]["when"])
        self.assertIsNone(data[2]["count"])

    def test_text(self):
        (path,) = rx.export(self.data, self.data.rows, "txt", self.tmp)
        lines = slurp(path, encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("Name: banana", lines[0])
        self.assertEqual(lines[2], "Name: cherry")

    def test_the_web_page_is_escaped_and_aligned(self):
        (path,) = rx.export(self.data, self.data.rows, "html", self.tmp)
        page = slurp(path, encoding="utf-8")
        self.assertIn("date &lt;b&gt;", page)
        self.assertNotIn("date <b>", page)
        self.assertIn("<h1>Fruit &amp; Veg</h1>", page)
        self.assertIn("<td class=\"num\">1,500</td>", page)
        self.assertNotIn("<script", page)

    def test_the_rows_given_are_the_rows_written(self):
        (path,) = rx.export(self.data, self.data.rows[:1], "csv", self.tmp)
        self.assertEqual(len(slurp(path, encoding="utf-8-sig").splitlines()),
                         2)

    def test_a_dataset_can_bring_its_own_formats(self):
        def writer(base, rows):
            path = base + ".special"
            with open(path, "w") as handle:
                handle.write(str(len(rows)))
            return [path]

        self.data.formats = {"special": ("Special", writer)}
        self.assertEqual(list(rx.formats_for(self.data))[-1], "special")
        (path,) = rx.export(self.data, self.data.rows, "special", self.tmp)
        self.assertEqual(slurp(path), "4")

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            rx.export(self.data, self.data.rows, "doc", self.tmp)

    def test_every_format_works_for_no_rows(self):
        for fmt in rx.FORMATS:
            with self.subTest(fmt=fmt):
                (path,) = rx.export(self.data, [], fmt,
                                    os.path.join(self.tmp, fmt))
                self.assertTrue(os.path.isfile(path))


class OpenCopiesTests(unittest.TestCase):
    def test_siblings_are_opened_and_closed(self):
        folder = tempfile.mkdtemp(prefix="ibe-sib-")
        self.addCleanup(shutil.rmtree, folder, True)
        for name in ("a.db", "b.db"):
            conn = sqlite3.connect(os.path.join(folder, name))
            conn.execute("CREATE TABLE t (x)")
            conn.commit()
            conn.close()
        main = sqlite3.connect(os.path.join(folder, "a.db"))
        self.addCleanup(main.close)
        with rc.open_copies(main, ["D/x/a.db", "D/x/b.db", "D/x/c.db"]) \
                as found:
            self.assertIs(found["D/x/a.db"], main)
            self.assertIsNot(found["D/x/b.db"], main)
            self.assertIsNone(found["D/x/c.db"])
            self.assertEqual(found["D/x/b.db"].execute(
                "SELECT count(*) FROM t").fetchone(), (0,))
            with self.assertRaises(sqlite3.OperationalError):
                found["D/x/b.db"].execute("INSERT INTO t VALUES (1)")
            other = found["D/x/b.db"]
        with self.assertRaises(sqlite3.ProgrammingError):
            other.execute("SELECT 1")                 # closed again
        main.execute("SELECT 1")                      # the main one is not


class SafariTests(unittest.TestCase):
    def datasets(self, make, build):
        conn = connect(self, build)
        return {d.key: d for d in make(conn)}

    def test_history(self):
        data = self.datasets(sf.history_datasets, fs.build_history)
        history = data["history"]
        self.assertEqual(len(history.rows), 7)
        first = history.sorted_rows(history.rows, "when", True)[0]
        self.assertEqual(first["url"], "https://www.example.com/page?a=1&b=2")
        self.assertEqual(first["when"], T0 + 900 + APPLE_EPOCH)
        self.assertEqual(first["site"], "www.example.com")
        failed = [r for r in history.rows if r["failed"]]
        self.assertEqual([r["title"] for r in failed], ["Other"])
        self.assertEqual(failed[0]["site"], "example.com")      # lower-cased
        about = next(r for r in history.rows if r["url"] == "about:blank")
        self.assertEqual((about["site"], about["title"]), ("", ""))

    def test_sites_visited(self):
        sites = self.datasets(sf.history_datasets,
                              fs.build_history)["sites"]
        by_site = {r["site"]: r for r in sites.rows}
        self.assertEqual(by_site["www.example.com"]["visits"], 3)
        self.assertEqual(by_site["www.example.com"]["pages"], 1)
        self.assertEqual(by_site["www.example.com"]["last"],
                         T0 + 900 + APPLE_EPOCH)
        self.assertIn("(no site)", by_site)
        self.assertEqual(sites.rows and sites.sorted_rows(
            sites.rows)[0]["site"], "www.example.com")

    def test_bookmarks_with_their_folders(self):
        data = self.datasets(sf.bookmark_datasets, fs.build_bookmarks)
        marks = {r["title"]: r for r in data["bookmarks"].rows}
        self.assertEqual(marks["Example"]["folder"], "Favorites")
        self.assertEqual(marks["Shop <one>"]["folder"],
                         "Favorites/Shopping")
        self.assertEqual(marks["Deep"]["folder"],
                         "Favorites/Shopping/Deals & Offers")
        self.assertEqual(marks["At the root"]["folder"], "")
        self.assertNotIn("Removed", marks)              # deleted
        self.assertIn("", marks)                        # untitled is kept
        self.assertEqual(marks["Example"]["modified"], T0 + 1 + APPLE_EPOCH)
        self.assertIsNone(marks["At the root"]["modified"])

    def test_the_reading_list_is_its_own_table(self):
        data = self.datasets(sf.bookmark_datasets, fs.build_bookmarks)
        self.assertEqual([r["title"] for r in data["reading"].rows],
                         ["Read later"])
        self.assertNotIn("Read later", [r["title"] for r in
                                        data["bookmarks"].rows])

    def test_open_tabs(self):
        data = self.datasets(sf.tab_datasets, fs.build_tabs)["tabs"]
        rows = {r["url"]: r for r in data.rows}
        self.assertEqual(len(rows), 3)                  # (not the one with
        self.assertEqual(rows["https://tab1.example.com/"]["group"],  # no
                         "This device")                  # address)
        self.assertEqual(rows["https://private.example.com/"]["group"],
                         "Private tabs")

    def test_a_netscape_bookmarks_file(self):
        folder = tempfile.mkdtemp(prefix="ibe-ns-")
        self.addCleanup(shutil.rmtree, folder, True)
        data = self.datasets(sf.bookmark_datasets, fs.build_bookmarks)
        dataset = data["bookmarks"]
        (path,) = rx.export(dataset, dataset.rows, "netscape", folder)
        text = slurp(path, encoding="utf-8")
        self.assertTrue(text.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>"))
        self.assertIn("<H3>Favorites/Shopping</H3>", text)
        self.assertIn("&lt;one&gt;", text)
        self.assertIn('HREF="https://shop.example.net/?a=1&amp;b=&quot;2&quot;"',
                      text)
        self.assertNotIn("<one>", text)
        self.assertEqual(text.count("<DT><A "), len(dataset.rows))

    def test_the_reader_uses_whichever_databases_are_there(self):
        folder = tempfile.mkdtemp(prefix="ibe-saf-")
        self.addCleanup(shutil.rmtree, folder, True)
        for name, build in (("History.db", fs.build_history),
                            ("SafariTabs.db", fs.build_tabs)):
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(database_bytes(build))
        conn = sqlite3.connect(os.path.join(folder, "History.db"))
        self.addCleanup(conn.close)
        keys = [d.key for d in sf.SafariReader(conn).datasets()]
        self.assertEqual(keys, ["history", "sites", "tabs"])

    def test_empty_databases_give_no_tables(self):
        def empty(conn):
            conn.execute("CREATE TABLE history_items (id, url)")
            conn.execute("CREATE TABLE history_visits (id, history_item, "
                         "visit_time, title, load_successful)")
            conn.commit()

        self.assertEqual(sf.history_datasets(connect(self, empty)), [])
        self.assertEqual(sf.tab_datasets(connect(self, empty)), [])

    def test_hosts(self):
        for url, host in (("https://Www.Example.com:8080/x", "www.example.com"),
                          ("http://[::1]/", "::1"), ("about:blank", ""),
                          ("", ""), (None, ""), ("not a url", ""),
                          ("https://", "")):
            with self.subTest(url=url):
                self.assertEqual(sf.host_of(url), host)


def archive(root, objects=()):
    """A keyed archive of *root*, built the way NSKeyedArchiver does."""
    table = ["$null"]
    table.extend(objects)
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                           "$top": {"root": plistlib.UID(len(table))},
                           "$objects": table + [root]},
                          fmt=plistlib.FMT_BINARY)


class KeyedArchiveTests(unittest.TestCase):
    def test_a_custom_object_becomes_a_dictionary(self):
        data = plistlib.dumps({
            "$archiver": "NSKeyedArchiver", "$version": 100000,
            "$top": {"root": plistlib.UID(1)},
            "$objects": ["$null",
                         {"$class": plistlib.UID(2), "text": plistlib.UID(3),
                          "score": 0.5, "items": plistlib.UID(4)},
                         {"$classname": "Thing", "$classes": ["Thing"]},
                         "hello",
                         {"$class": plistlib.UID(5),
                          "NS.objects": [plistlib.UID(3), plistlib.UID(0)]},
                         {"$classname": "NSArray"}]},
            fmt=plistlib.FMT_BINARY)
        value = ka.load(data)
        self.assertEqual(value, {"$class": "Thing", "text": "hello",
                                 "score": 0.5, "items": ["hello", None]})
        self.assertEqual(ka.find(value, "text"), ["hello"])
        self.assertEqual(ka.find([value, {"x": {"text": "deep"}}], "text"),
                         ["hello", "deep"])

    def test_dictionaries_dates_urls_and_data(self):
        data = plistlib.dumps({
            "$archiver": "NSKeyedArchiver", "$version": 100000,
            "$top": {"root": plistlib.UID(1)},
            "$objects": [
                "$null",
                {"$class": plistlib.UID(2), "NS.keys": [plistlib.UID(3),
                                                        plistlib.UID(4)],
                 "NS.objects": [plistlib.UID(5), plistlib.UID(7)]},
                {"$classname": "NSDictionary"},
                "when", "link",
                {"$class": plistlib.UID(6), "NS.time": 86400.0},
                {"$classname": "NSDate"},
                {"$class": plistlib.UID(8), "NS.base": plistlib.UID(0),
                 "NS.relative": plistlib.UID(9)},
                {"$classname": "NSURL"}, "https://example.com/"]},
            fmt=plistlib.FMT_BINARY)
        value = ka.load(data)
        self.assertEqual(value["when"],
                         datetime(2001, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(value["link"], "https://example.com/")

    def test_a_loop_does_not_crash(self):
        data = plistlib.dumps({
            "$archiver": "NSKeyedArchiver", "$version": 100000,
            "$top": {"root": plistlib.UID(1)},
            "$objects": ["$null",
                         {"$class": plistlib.UID(2), "me": plistlib.UID(1)},
                         {"$classname": "Loop"}]}, fmt=plistlib.FMT_BINARY)
        self.assertEqual(ka.load(data), {"$class": "Loop", "me": None})

    def test_what_is_not_an_archive_is_refused(self):
        binary = plistlib.FMT_BINARY
        for data in (b"not a plist", plistlib.dumps({"a": 1}),
                     plistlib.dumps([1, 2]),
                     plistlib.dumps({"$objects": 5, "$top": {}}),
                     plistlib.dumps({"$objects": ["$null"], "$top": {
                         "root": plistlib.UID(9)}}, fmt=binary)):
            with self.subTest(data=data[:12]):
                with self.assertRaises(ka.ArchiveError):
                    ka.load(data)

    def test_looks_like_an_archive(self):
        self.assertTrue(ka.is_keyed_archive(archive("x")))
        self.assertFalse(ka.is_keyed_archive(b"plain"))
        self.assertFalse(ka.is_keyed_archive(plistlib.dumps({"a": 1})))


if __name__ == "__main__":
    unittest.main()
