# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""tools/schema_report.py and tools/health_kinds_report.py: reports meant to
be pasted into an issue. They must show the shape of a backup (tables,
columns, counts) and never what it holds."""

import importlib.util
import io
import os
import plistlib
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests import fixture_backup as fb
from tests import fixture_health as fh
from tests import fixture_notes as fn
from tests import fixture_reminders as fr
from tests.fixture_apps import database_bytes

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ("Sam's iPhone", "Smart Scale", "Sam Example", "Shopping list",
           "Pancakes", "Alex Example")


def load_tool(name):
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plain_backup(parent, files, encrypted=False):
    folder, _ids = fb.build_backup(parent, files=files, encrypted=encrypted)
    return folder


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-reports-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.access = load_tool("backup_access")
        self.schema = load_tool("schema_report")
        self.kinds = load_tool("health_kinds_report")

    def backup(self, files, **kw):
        return plain_backup(self.tmp, files, **kw)

    def opened(self, folder, password=None):
        return self.access.open_backup(folder, password)


class SchemaTests(ReportCase):
    def files(self):
        return (fh.backup_files() + fr.backup_files()
                + fn.backup_files(include_media=False))

    def test_the_report_gives_tables_columns_and_counts(self):
        with self.opened(self.backup(self.files())) as opened:
            text = self.schema.build(opened)
        self.assertIn("### `HealthDomain/Health/healthdb_secure.sqlite`", text)
        self.assertRegex(text, r"\| samples \| [\d,]+ \| .*data_type")
        self.assertIn("| data_provenances |", text)
        self.assertIn("Known files this backup does not have", text)
        self.assertIn("`HomeDomain/Library/SMS/sms.db`", text)    # (absent)

    def test_it_says_nothing_of_what_the_backup_holds(self):
        with self.opened(self.backup(self.files())) as opened:
            text = self.schema.build(opened, sql=True)
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertNotIn(self.tmp, text)

    def test_core_data_entities_are_named(self):
        with self.opened(self.backup(self.files())) as opened:
            text = self.schema.build(opened, [
                "HomeDomain/" + fr.FOLDER + "/Data-AAAA.sqlite"])
        self.assertIn("Entities:", text)
        self.assertIn("25 REMCDList", text)

    def test_the_create_statements_are_given_on_request(self):
        with self.opened(self.backup(self.files())) as opened:
            path = ["HealthDomain/Health/healthdb.sqlite"]
            without = self.schema.build(opened, path)
            with_sql = self.schema.build(opened, path, sql=True)
        self.assertNotIn("CREATE TABLE", without)
        self.assertIn("CREATE TABLE", with_sql)
        self.assertIn("<details>", with_sql)

    def test_a_property_list_shows_only_its_top_level(self):
        plist = plistlib.dumps({
            "Settings": {"SECRET-NETWORK-NAME": {"password": "x"}},
            "List of known networks": [{"SSID": "SECRET-SSID"}] * 3,
            "Blob": b"0123456789", "Name": "SECRET-TEXT", "Flag": True})
        files = [("SystemPreferencesDomain",
                  "SystemConfiguration/com.apple.wifi.plist", plist)]
        with self.opened(self.backup(files)) as opened:
            text = self.schema.build(opened, [
                "SystemPreferencesDomain/SystemConfiguration/"
                "com.apple.wifi.plist"])
        self.assertIn("| Settings | dictionary of 1 |", text)
        self.assertIn("| List of known networks | list of 3 |", text)
        self.assertIn("| Blob | 10 bytes |", text)
        self.assertIn("| Name | text of 11 |", text)
        self.assertNotIn("SECRET", text)

    def test_a_file_asked_for_that_the_backup_does_not_have_is_listed(self):
        with self.opened(self.backup(self.files())) as opened:
            text = self.schema.build(opened, ["HomeDomain/Library/none.db"])
        self.assertIn("Known files this backup does not have", text)
        self.assertIn("`HomeDomain/Library/none.db`", text)
        self.assertNotIn("###  ", text)

    def test_what_the_phone_had_not_yet_written_to_the_main_file_is_seen(self):
        """A database's journal file is copied beside it, so a table that
        is only in the journal is reported."""
        path = os.path.join(self.tmp, "wal.sqlite")
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 0")
        conn.execute("CREATE TABLE in_the_main_file (a)")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("CREATE TABLE only_in_the_journal (a)")
        conn.execute("INSERT INTO only_in_the_journal VALUES (1)")
        conn.commit()
        with open(path, "rb") as handle:
            main = handle.read()
        with open(path + "-wal", "rb") as handle:
            wal = handle.read()
        conn.close()
        self.assertGreater(len(wal), 0)
        files = [("HomeDomain", "Library/x/wal.sqlite", main),
                 ("HomeDomain", "Library/x/wal.sqlite-wal", wal)]
        with self.opened(self.backup(files)) as opened:
            text = self.schema.build(opened, ["HomeDomain/Library/x/wal.sqlite"])
        self.assertIn("| in_the_main_file |", text)
        self.assertIn("| only_in_the_journal | 1 |", text)

    def test_other_files_are_not_described(self):
        files = [("HomeDomain", "Library/notes.txt", b"SECRET words")]
        with self.opened(self.backup(files)) as opened:
            text = self.schema.build(opened, ["HomeDomain/Library/notes.txt"])
        self.assertIn("neither a SQLite database nor a property list", text)
        self.assertNotIn("SECRET", text)

    def test_a_damaged_database_is_reported_not_raised(self):
        files = [("HomeDomain", "Library/SMS/sms.db",
                  b"SQLite format 3\x00" + b"\xff" * 200)]
        with self.opened(self.backup(files)) as opened:
            text = self.schema.build(opened, ["HomeDomain/Library/SMS/sms.db"])
        self.assertIn("could not be read", text)

    def test_find_lists_database_files_by_a_word(self):
        with self.opened(self.backup(self.files())) as opened:
            found = self.schema.find_paths(opened.index, "reminders")
            none = self.schema.find_paths(opened.index, "zzzz")
        self.assertTrue(found)
        self.assertTrue(all("reminders" in p.lower() for p in found))
        self.assertTrue(all(p.lower().endswith((".sqlite", ".db", ".plist"))
                            for p in found))
        self.assertEqual(none, [])

    def test_the_command(self):
        folder = self.backup(self.files())
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.schema.main([folder, "--path",
                                     "HealthDomain/Health/healthdb.sqlite"])
        self.assertEqual(code, 0)
        self.assertIn("| sources |", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            self.schema.main([folder, "--find", "healthdb"])
        self.assertIn("HealthDomain/Health/healthdb_secure.sqlite",
                      out.getvalue())

    def test_a_folder_that_is_not_a_backup(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.schema.main([empty])
        self.assertEqual(code, 1)
        self.assertIn("did not open", out.getvalue())

    def test_an_encrypted_backup_with_the_password_asked_on_the_terminal(self):
        folder = self.backup(self.files(), encrypted=True)
        out = io.StringIO()
        with mock.patch("getpass.getpass", return_value=fb.PASSPHRASE), \
                redirect_stdout(out):
            code = self.schema.main([folder, "--password-prompt", "--path",
                                     "HealthDomain/Health/healthdb.sqlite"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("| sources |", out.getvalue())

    def test_a_wrong_password_is_a_message(self):
        folder = self.backup(self.files(), encrypted=True)
        out = io.StringIO()
        with mock.patch("getpass.getpass", return_value="wrong"), \
                redirect_stdout(out):
            code = self.schema.main([folder, "--password-prompt"])
        self.assertEqual(code, 1)
        self.assertIn("did not open", out.getvalue())

    def test_no_temporary_files_are_left(self):
        before = {n for n in os.listdir(tempfile.gettempdir())
                  if n.startswith("ibe-report-")}
        with self.opened(self.backup(self.files())) as opened:
            self.schema.build(opened)
        after = {n for n in os.listdir(tempfile.gettempdir())
                 if n.startswith("ibe-report-")}
        self.assertEqual(after - before, set())

    def test_the_known_files_come_from_the_tabs(self):
        with self.opened(self.backup(self.files())) as opened:
            found, missing = self.schema.known_paths(opened.index)
        self.assertIn("HealthDomain/Health/healthdb_secure.sqlite", found)
        self.assertIn("HomeDomain/Library/SMS/sms.db", missing)
        self.assertFalse(set(found) & set(missing))


class HealthKindTests(ReportCase):
    def test_the_unnamed_kinds_are_listed(self):
        with self.opened(self.backup(fh.backup_files())) as opened:
            text = self.kinds.build(opened)
        self.assertIn("| Number | Samples | Years |", text)
        self.assertRegex(text, rf"\| {fh.UNKNOWN} \| 2 \| \d{{4}} \| "
                         r"measurement \|")
        self.assertRegex(text, rf"\| {fh.UNKNOWN + 1} \| ")      # (an event)
        self.assertNotRegex(text, rf"\| {fh.STEPS} \| ")         # (named)

    def test_it_shows_no_date_source_or_name(self):
        with self.opened(self.backup(fh.backup_files())) as opened:
            text = self.kinds.build(opened)
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertNotRegex(text, r"\d{4}-\d{2}-\d{2}")       # no full date

    def test_an_old_database_that_names_nothing(self):
        def old(conn):
            conn.execute("CREATE TABLE samples (data_id INTEGER PRIMARY KEY, "
                         "start_date REAL, end_date REAL, data_type INTEGER)")
            conn.execute("CREATE TABLE quantity_samples (data_id INTEGER "
                         "PRIMARY KEY, quantity REAL, original_quantity REAL, "
                         "original_unit INTEGER)")
            for number, kind in enumerate([7, 7, 4242], 1):
                conn.execute("INSERT INTO samples VALUES (?, 1.0, 2.0, ?)",
                             (number, kind))
                conn.execute("INSERT INTO quantity_samples VALUES "
                             "(?, 3.5, 3.5, 0)", (number,))
            conn.commit()
        files = [("HealthDomain", fh.HEALTH, database_bytes(old))]
        with self.opened(self.backup(files)) as opened:
            text = self.kinds.build(opened)
        self.assertIn("| 4242 |", text)
        self.assertNotRegex(text, r"\| 7 \| ")           # named by the table
        self.assertIn("does not name its kinds", text)

    def test_the_years_of_a_kind_are_a_range(self):
        def spread(conn):
            conn.execute("CREATE TABLE samples (data_id INTEGER PRIMARY KEY, "
                         "start_date REAL, end_date REAL, data_type INTEGER)")
            # Apple time: 2017-06, 2019-06, 2021-06 (seconds since 2001)
            for n, stamp in enumerate([518400000, 581000000, 644000000], 1):
                conn.execute("INSERT INTO samples VALUES (?, ?, ?, 7777)",
                             (n, stamp, stamp + 60))
            conn.commit()
        files = [("HealthDomain", fh.HEALTH, database_bytes(spread))]
        with self.opened(self.backup(files)) as opened:
            text = self.kinds.build(opened)
        self.assertRegex(text, r"\| 7777 \| 3 \| 2017-2021 \|")

    def test_every_kind_named(self):
        def named(conn):
            conn.execute("CREATE TABLE samples (data_id INTEGER PRIMARY KEY, "
                         "start_date REAL, end_date REAL, data_type INTEGER)")
            conn.execute("INSERT INTO samples VALUES (1, 1.0, 2.0, 7)")
            conn.commit()
        files = [("HealthDomain", fh.HEALTH, database_bytes(named))]
        with self.opened(self.backup(files)) as opened:
            text = self.kinds.build(opened)
        self.assertIn("Every kind is named", text)

    def test_event_values_are_listed_without_a_long_tail(self):
        def events(conn):
            conn.execute("CREATE TABLE samples (data_id INTEGER PRIMARY KEY, "
                         "start_date REAL, end_date REAL, data_type INTEGER)")
            conn.execute("CREATE TABLE category_samples (data_id INTEGER "
                         "PRIMARY KEY, value INTEGER)")
            for n in range(40):
                conn.execute("INSERT INTO samples VALUES (?, 1.0, 2.0, 8888)",
                             (n,))
                conn.execute("INSERT INTO category_samples VALUES (?, ?)",
                             (n, n))
            conn.commit()
        files = [("HealthDomain", fh.HEALTH, database_bytes(events))]
        with self.opened(self.backup(files)) as opened:
            text = self.kinds.build(opened)
        self.assertIn("| 8888 | 40 |", text)
        self.assertIn("event", text)
        self.assertIn("0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ...", text)
        self.assertNotIn("39", text)

    def test_a_backup_without_health(self):
        files = [("HomeDomain", "Library/x.txt", b"x")]
        with self.opened(self.backup(files)) as opened:
            self.assertIn("no Health database", self.kinds.build(opened))

    def test_the_command(self):
        folder = self.backup(fh.backup_files())
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.kinds.main([folder])
        self.assertEqual(code, 0)
        self.assertIn("kinds;", out.getvalue())


if __name__ == "__main__":
    unittest.main()
