# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Shared plumbing for the app views (no GUI)."""

import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

import file_index as fi
import ios_backup_explorer as app
from ios_apps import common
from tests import fixture_apps as fa
from tests import fixture_backup as fb


class AppleTimeTests(unittest.TestCase):
    def test_no_value_means_no_time(self):
        for value in (None, "", 0, 0.0, "junk", b"x", object()):
            self.assertIsNone(common.apple_time(value), repr(value))

    def test_seconds_since_2001(self):
        self.assertEqual(common.apple_time(1), 978_307_201)
        self.assertEqual(common.apple_time(778_000_000), 1_756_307_200)
        self.assertEqual(common.apple_time(-100), 978_307_100)

    def test_nanoseconds_are_recognised(self):
        self.assertEqual(common.apple_time(778_000_000 * 10 ** 9),
                         1_756_307_200)
        self.assertEqual(common.apple_time(str(778_000_000 * 10 ** 9)),
                         1_756_307_200)

    def test_both_scales_agree(self):
        self.assertEqual(common.apple_time(500_000_000),
                         common.apple_time(500_000_000 * 10 ** 9))

    def test_formatting(self):
        self.assertRegex(common.format_datetime(1_756_307_200),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertRegex(common.format_datetime(1_756_307_200, seconds=True),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(common.format_datetime(None), "")
        self.assertEqual(common.format_datetime(10 ** 20), "")


class WorkspaceTests(unittest.TestCase):
    def test_it_is_private_and_removed_on_close(self):
        space = common.Workspace()
        self.assertTrue(os.path.isdir(space.path))
        folder = space.subfolder("messages")
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(space.subfolder("messages"), folder)   # reusable
        space.close()
        self.assertFalse(os.path.exists(space.path))
        space.close()                                          # harmless

    def test_each_workspace_is_separate(self):
        a, b = common.Workspace(), common.Workspace()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        self.assertNotEqual(a.path, b.path)


def rows(*paths):
    return [(f"{i:040x}", d, p, 1, 10, 1, 1)
            for i, (d, p) in enumerate(paths, 1)]


class LocateDatabaseTests(unittest.TestCase):
    def test_finds_the_database_and_its_journal_files(self):
        index = fi.FileIndex(rows(
            ("HomeDomain", "Library/SMS/sms.db"),
            ("HomeDomain", "Library/SMS/sms.db-wal"),
            ("HomeDomain", "Library/SMS/sms.db-shm"),
            ("HomeDomain", "Library/SMS/other.db-wal")))
        self.assertEqual(
            common.locate_database(index, "HomeDomain/Library/SMS/sms.db"),
            [(f"{1:040x}", "sms.db"), (f"{2:040x}", "sms.db-wal"),
             (f"{3:040x}", "sms.db-shm")])

    def test_siblings_are_optional(self):
        index = fi.FileIndex(rows(("D", "a/x.db")))
        self.assertEqual(common.locate_database(index, "D/a/x.db"),
                         [(f"{1:040x}", "x.db")])

    def test_missing_or_not_a_file(self):
        index = fi.FileIndex(rows(("D", "a/x.db-wal"), ("D", "a/y.db")))
        self.assertEqual(common.locate_database(index, "D/a/x.db"), [])
        self.assertEqual(common.locate_database(index, "D/a"), [])
        self.assertEqual(common.locate_database(index, "D/nope.db"), [])


class SqliteSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-src-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "x.db")
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE t (n INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
        conn.commit()
        conn.close()
        self.source = common.SqliteSource(self.path)
        self.addCleanup(self.source.close)

    def test_queries_run_and_return_results(self):
        total = self.source.run(
            lambda conn: conn.execute("SELECT SUM(n) FROM t").fetchone()[0])
        self.assertEqual(total.result(10), 6)

    def test_every_call_runs_on_the_same_thread(self):
        threads = {self.source.run(lambda c: threading.get_ident()).result(10)
                   for _ in range(5)}
        self.assertEqual(len(threads), 1)
        self.assertNotIn(threading.get_ident(), threads)

    def test_it_can_be_used_from_other_threads(self):
        errors = []

        def worker():
            try:
                for _ in range(5):
                    self.source.run(lambda c: c.execute(
                        "SELECT COUNT(*) FROM t").fetchone()).result(10)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        pool = [threading.Thread(target=worker) for _ in range(4)]
        for t in pool:
            t.start()
        for t in pool:
            t.join()
        self.assertEqual(errors, [])

    def test_errors_come_back_through_the_future(self):
        future = self.source.run(lambda c: c.execute("SELECT nope FROM t"))
        self.assertIsInstance(future.exception(10), sqlite3.OperationalError)

    def test_the_copy_cannot_be_modified(self):
        future = self.source.run(lambda c: c.execute("DELETE FROM t"))
        self.assertIsNotNone(future.exception(10))
        total = self.source.run(
            lambda c: c.execute("SELECT COUNT(*) FROM t").fetchone()[0])
        self.assertEqual(total.result(10), 3)

    def test_table_columns(self):
        columns = self.source.run(common.table_columns, "t").result(10)
        self.assertEqual(columns, {"n"})
        self.assertEqual(self.source.run(common.table_columns,
                                         "missing").result(10), set())


class HandleKeyTests(unittest.TestCase):
    def test_phone_numbers_match_however_they_are_written(self):
        keys = {common.handle_key(n) for n in (
            "+1 (555) 010-1234", "5550101234", "555-010-1234",
            "+15550101234", " (555) 010 1234 ")}
        self.assertEqual(keys, {"5550101234"})

    def test_short_numbers_keep_their_digits(self):
        self.assertEqual(common.handle_key("12345"), "12345")

    def test_emails_are_lower_cased(self):
        self.assertEqual(common.handle_key(" Friend@Example.COM "),
                         "friend@example.com")

    def test_nothing(self):
        self.assertEqual(common.handle_key(None), "")
        self.assertEqual(common.handle_key(""), "")
        self.assertEqual(common.handle_key("abc"), "")


class ContactBookTests(unittest.TestCase):
    def book(self):
        conn = sqlite3.connect(":memory:")
        fa.build_addressbook(conn)
        self.addCleanup(conn.close)
        return common.ContactBook.from_connection(conn)

    def test_names_from_numbers_and_emails(self):
        book = self.book()
        self.assertEqual(book.name_for("+15550101234"), "Alice Example")
        self.assertEqual(book.name_for("5550101234"), "Alice Example")
        self.assertEqual(book.name_for("friend@example.com"), "Bob Sample")
        self.assertEqual(book.name_for("FRIEND@example.com"), "Bob Sample")
        self.assertEqual(book.name_for("+15550105678"), "Bob Sample")

    def test_organisations_and_nicknames_are_used_when_there_is_no_name(self):
        book = self.book()
        self.assertEqual(book.name_for("+1 555 010 7777"), "Pizza Place")
        self.assertEqual(book.name_for("+442079460000"), "Mum")

    def test_unknown_and_nameless_people(self):
        book = self.book()
        self.assertIsNone(book.name_for("+15550109999"))
        self.assertIsNone(book.name_for("5550106666"))     # a person, no name
        self.assertIsNone(book.name_for(""))
        self.assertIsNone(book.name_for(None))

    def test_other_kinds_of_value_are_ignored(self):
        self.assertIsNone(self.book().name_for("somewhere"))

    def test_counts(self):
        book = self.book()
        self.assertEqual(book.person_count, 4)     # 5 people, 1 with no name
        # Alice 1, Bob 2 (email + phone), Pizza Place 1, Mum 1; the nameless
        # person's number and the non-phone, non-email value are left out
        self.assertEqual(len(book), 5)

    def test_a_database_without_the_tables_gives_an_empty_book(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        book = common.ContactBook.from_connection(conn)
        self.assertEqual((len(book), book.person_count), (0, 0))
        self.assertIsNone(book.name_for("5550101234"))


class ExportFilesTests(unittest.TestCase):
    def check(self, encrypted):
        tmp = tempfile.mkdtemp(prefix="ibe-export-")
        self.addCleanup(shutil.rmtree, tmp, True)
        files = [("HomeDomain", "Library/SMS/sms.db", b"database bytes"),
                 ("HomeDomain", "Library/SMS/sms.db-wal", b"wal bytes"),
                 ("HomeDomain", "Library/empty", b"")]
        backup_dir, ids = fb.build_backup(tmp, files=files,
                                          encrypted=encrypted)
        session = app.BackupSession()
        self.addCleanup(lambda: (session.close(),
                                 session._executor.shutdown(wait=True)))
        session.open(backup_dir, fb.PASSPHRASE if encrypted else None) \
            .result(60)
        dest = os.path.join(tmp, "work")
        names = session.export_files(
            [(ids[("HomeDomain", "Library/SMS/sms.db")], "sms.db"),
             (ids[("HomeDomain", "Library/SMS/sms.db-wal")], "sms.db-wal"),
             (ids[("HomeDomain", "Library/empty")], "empty")],
            dest).result(60)
        self.assertEqual(names, ["sms.db", "sms.db-wal", "empty"])
        for name, content in (("sms.db", b"database bytes"),
                              ("sms.db-wal", b"wal bytes"), ("empty", b"")):
            with open(os.path.join(dest, name), "rb") as handle:
                self.assertEqual(handle.read(), content)

        for bad in ("../escape", "a/b", "", "..", "."):
            error = session.export_files(
                [(ids[("HomeDomain", "Library/SMS/sms.db")], bad)],
                dest).exception(60)
            self.assertIsInstance(error, ValueError, bad)
        self.assertIsInstance(
            session.export_files([("0" * 40, "x")], dest).exception(60),
            FileNotFoundError)

    def test_encrypted(self):
        self.check(True)

    def test_unencrypted(self):
        self.check(False)


if __name__ == "__main__":
    unittest.main()
