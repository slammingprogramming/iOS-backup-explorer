# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Medications and their log, from invented data in the layout Health uses."""

import sqlite3
import unittest

from ios_apps import health as hl
from ios_apps import health_medications as hm
from tests import fixture_health as fh

DAY = 86400
ONE, TWO, GONE = b"1" * 16, b"2" * 16, b"3" * 16


def build(conn):
    conn.executescript("""
        CREATE TABLE samples (data_id INTEGER PRIMARY KEY, start_date REAL,
            end_date REAL, data_type INTEGER);
        CREATE TABLE user_domain_concepts (udc_id INTEGER PRIMARY KEY,
            uuid BLOB, deleted INTEGER, creation_date REAL);
        CREATE TABLE medication_user_domain_concepts (udc_id INTEGER);
        CREATE TABLE user_domain_concept_localized_strings (
            ROWID INTEGER PRIMARY KEY, udc_id INTEGER, property_type INTEGER,
            string_value TEXT);
        CREATE TABLE user_domain_concept_properties (ROWID INTEGER PRIMARY KEY,
            udc_id INTEGER, property_type INTEGER, string_value TEXT);
        CREATE TABLE medication_schedules (ROWID INTEGER PRIMARY KEY,
            medication_uuid BLOB, deleted INTEGER);
        CREATE TABLE medication_dose_event_samples (data_id INTEGER PRIMARY KEY,
            log_origin INTEGER, medication_uuid BLOB,
            scheduled_dose_quantity REAL, dose_quantity REAL,
            scheduled_date REAL, status INTEGER);
    """)
    conn.executemany("INSERT INTO user_domain_concepts VALUES (?, ?, ?, ?)", [
        (1, ONE, 0, fh.T0), (2, TWO, 1, fh.T0 + DAY), (3, b"x" * 16, 0, 5)])
    conn.executemany("INSERT INTO medication_user_domain_concepts VALUES (?)",
                     [(1,), (2,)])
    conn.executemany(
        "INSERT INTO user_domain_concept_localized_strings (udc_id, "
        "property_type, string_value) VALUES (?, ?, ?)", [
            (1, 160007, "Example tablets"), (1, 160007, "second spelling"),
            (1, 160009, "Examplol, Sampleine"), (1, 160010, "Tablet"),
            (1, 160012, "Example tablets 10 mg Tablet"),
            (2, 160009, "Only the ingredients"), (3, 160007, "Not a med")])
    conn.execute("INSERT INTO user_domain_concept_properties (udc_id, "
                 "property_type, string_value) VALUES (1, 160000, 'A property')")
    conn.executemany("INSERT INTO medication_schedules (medication_uuid, "
                     "deleted) VALUES (?, ?)", [(ONE, 0), (ONE, 1), (ONE, 0)])
    events = [
        # (data_id, origin, uuid, planned, taken, scheduled, status, logged)
        (10, 2, ONE, 1.0, None, fh.T0 + 1 * DAY, 1, fh.T0 + 1 * DAY),
        (11, 2, ONE, 1.0, 1.0, fh.T0 + 2 * DAY, 4, fh.T0 + 2 * DAY + 60),
        (12, 1, ONE, 1.0, 2.0, fh.T0 + 3 * DAY, 4, fh.T0 + 3 * DAY + 90),
        (13, 2, TWO, 0.5, None, fh.T0 + 4 * DAY, 99, fh.T0 + 4 * DAY),
        (14, 2, GONE, 1.0, 1.0, fh.T0 + 5 * DAY, 4, fh.T0 + 5 * DAY),
    ]
    for data_id, origin, uuid, planned, taken, scheduled, status, logged \
            in events:
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, 273)",
                     (data_id, logged, logged))
        conn.execute("INSERT INTO medication_dose_event_samples VALUES "
                     "(?, ?, ?, ?, ?, ?, ?)", (data_id, origin, uuid,
                                               planned, taken, scheduled,
                                               status))
    conn.commit()


class MedicationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        build(self.conn)
        self.sets = {d.key: d for d in hm.datasets(self.conn)}

    def test_the_tables(self):
        self.assertEqual(list(self.sets), ["medications", "medication_doses"])

    def test_only_medications_are_listed(self):
        rows = self.sets["medications"].rows
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "Example tablets")

    def test_the_product_ingredients_and_form(self):
        first, second = self.sets["medications"].rows
        self.assertEqual((first["product"], first["ingredients"],
                          first["form"]),
                         ("Example tablets 10 mg Tablet",
                          "Examplol, Sampleine", "Tablet"))
        self.assertEqual((second["product"], second["form"]), ("", ""))
        self.assertEqual(second["ingredients"], "Only the ingredients")

    def test_a_medication_without_the_name_field_is_numbered(self):
        rows = self.sets["medications"].rows
        self.assertEqual(rows[1]["name"], "Medication 2")
        self.assertTrue(rows[1]["removed"])

    def test_counts_per_medication(self):
        first = self.sets["medications"].rows[0]
        self.assertEqual((first["taken"], first["logged"]), (2, 3))
        self.assertEqual(first["schedules"], 2)             # not the deleted
        self.assertEqual(first["last_taken"], first["last_taken"])
        self.assertGreater(first["last_taken"], first["added"])
        second = self.sets["medications"].rows[1]
        self.assertEqual((second["taken"], second["logged"],
                          second["last_taken"]), (0, 1, None))

    def test_the_details_list_every_string(self):
        text = self.sets["medications"].details(self.sets[
            "medications"].rows[0])
        for expected in ("Example tablets", "L160009: Examplol, Sampleine",
                         "P160000: A property"):
            self.assertIn(expected, text)
        self.assertNotIn("second spelling", text)

    def test_the_log(self):
        rows = self.sets["medication_doses"].rows
        self.assertEqual(len(rows), 5)
        by_status = {}
        for row in rows:
            by_status.setdefault(row["status"], []).append(row)
        self.assertEqual(len(by_status["Taken"]), 3)
        self.assertEqual(len(by_status["Not answered"]), 1)
        self.assertEqual(len(by_status["Status 99"]), 1)    # not guessed
        gone = [r for r in rows if r["medication"].startswith("(a medic")]
        self.assertEqual(len(gone), 1)

    def test_doses_are_shown_as_numbers(self):
        table = self.sets["medication_doses"]
        taken = next(r for r in table.rows if r["taken"] == 2.0)
        shown = {c.key: c.show(taken.get(c.key), taken) for c in table.columns}
        self.assertEqual((shown["planned"], shown["taken"]), ("1", "2"))
        pending = next(r for r in table.rows if r["status"] == "Not answered")
        self.assertEqual(table.columns[4].show(None, pending), "")

    def test_the_log_is_newest_first(self):
        table = self.sets["medication_doses"]
        ordered = table.sorted_rows(table.rows)
        self.assertEqual([r["scheduled"] for r in ordered],
                         sorted((r["scheduled"] for r in table.rows),
                                reverse=True))


class MissingTests(unittest.TestCase):
    def test_nothing_without_the_tables(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(hm.datasets(conn), [])

    def test_they_come_with_the_health_reader(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        fh.build_health(conn)
        conn.execute("DROP TABLE samples")          # (the medication tables
        build(conn)                                 #  bring their own)
        keys = [d.key for d in hl.datasets(conn, None, "")]
        self.assertIn("medications", keys)


if __name__ == "__main__":
    unittest.main()
