# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Events, cycle tracking and symptoms, from invented samples."""

import sqlite3
import unittest

from ios_apps import health as hl
from ios_apps import health_events as he
from tests import fixture_health as fh

P = "HKCategoryTypeIdentifier"
NAMES = {501: P + "Headache", 502: P + "MenstrualFlow",
         503: P + "OvulationTestResult", 504: P + "Contraceptive",
         505: P + "HandwashingEvent", 506: P + "AppleStandHour",
         507: P + "SleepAnalysis", 508: "HKQuantityTypeIdentifierStepCount",
         509: P + "PregnancyTestResult", 510: P + "CervicalMucusQuality",
         511: P + "SexualActivity", 512: P + "AudioExposureEvent"}
SOURCES = {1: "Phone", 2: "Watch"}


def build(samples):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE samples (data_id INTEGER PRIMARY KEY, start_date REAL,
            end_date REAL, data_type INTEGER);
        CREATE TABLE objects (data_id INTEGER PRIMARY KEY, provenance INTEGER);
        CREATE TABLE category_samples (data_id INTEGER PRIMARY KEY,
            value INTEGER);
    """)
    for data_id, (kind, start, end, value, provenance) in enumerate(samples,
                                                                    1):
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                     (data_id, start, end, kind))
        conn.execute("INSERT INTO objects VALUES (?, ?)", (data_id,
                                                           provenance))
        conn.execute("INSERT INTO category_samples VALUES (?, ?)",
                     (data_id, value))
    conn.commit()
    return conn


T = fh.T0
SAMPLES = [
    (501, T, T + 3600, 3, 1), (501, T + 10, T + 10, 2, 2),
    (501, T + 20, T + 20, 4, 1), (501, T + 30, T + 30, 9, 1),
    (502, T + 40, T + 40, 4, 1), (502, T + 41, T + 41, 5, 1),
    (503, T + 50, T + 50, 2, 1), (503, T + 51, T + 51, 4, 1),
    (504, T + 60, T + 60, 6, 1), (504, T + 61, T + 61, 7, 1),
    (505, T + 70, T + 95, 0, 2), (506, T + 80, T + 3680, 0, 2),
    (506, T + 3680, T + 7280, 1, 2), (507, T + 90, T + 190, 3, 1),
    (508, T + 100, T + 100, 5, 1), (509, T + 110, T + 110, 2, 1),
    (510, T + 120, T + 120, 5, 1), (511, T + 130, T + 130, 0, 1),
    (512, T + 140, T + 160, 1, 2)]


class RowTests(unittest.TestCase):
    def setUp(self):
        self.conn = build(SAMPLES)
        self.addCleanup(self.conn.close)
        self.rows = he.event_rows(self.conn, NAMES, SOURCES)

    def find(self, kind, value=None):
        return [r for r in self.rows if r["kind"] == kind
                and (value is None or r["value"] == value)]

    def test_sleep_and_quantities_are_not_here(self):
        kinds = {r["kind"] for r in self.rows}
        self.assertNotIn("Sleep analysis", kinds)
        self.assertNotIn("Step count", kinds)
        self.assertEqual(len(self.rows), len(SAMPLES) - 2)

    def test_a_symptoms_severity_in_words(self):
        values = sorted(r["value"] for r in self.find("Headache"))
        self.assertEqual(values, ["Mild", "Moderate", "Severe", "Value 9"])
        self.assertTrue(all(r["group"] == "Symptom"
                            for r in self.find("Headache")))

    def test_cycle_tracking_in_words(self):
        self.assertEqual(self.find("Menstrual flow", "Heavy")[0]["group"],
                         "Cycle tracking")
        self.assertEqual(len(self.find("Menstrual flow", "None")), 1)
        self.assertEqual(len(self.find("Ovulation test result",
                                       "Luteinizing hormone surge")), 1)
        self.assertEqual(len(self.find("Ovulation test result",
                                       "Estrogen surge")), 1)
        self.assertEqual(len(self.find("Contraceptive", "Oral")), 1)
        self.assertEqual(len(self.find("Contraceptive", "Patch")), 1)
        self.assertEqual(len(self.find("Pregnancy test result", "Positive")),
                         1)
        self.assertEqual(len(self.find("Cervical mucus quality",
                                       "Egg white")), 1)

    def test_events_that_only_happened(self):
        wash = self.find("Handwashing event")[0]
        self.assertEqual((wash["value"], wash["group"]), ("", "Event"))
        self.assertEqual(wash["length"], 25)
        self.assertEqual(self.find("Sexual activity")[0]["value"], "")
        self.assertEqual(self.find("Sexual activity")[0]["group"],
                         "Cycle tracking")

    def test_stand_hours_and_loud_audio(self):
        stands = sorted(r["value"] for r in self.find("Apple stand hour"))
        self.assertEqual(stands, ["Idle", "Stood"])
        self.assertEqual(self.find("Audio exposure event")[0]["value"],
                         "Loud environment")

    def test_the_source_and_the_length(self):
        first = self.find("Headache", "Moderate")[0]
        self.assertEqual((first["source"], first["length"]), ("Phone", 3600))
        watch = self.find("Headache", "Mild")[0]
        self.assertEqual((watch["source"], watch["length"]), ("Watch", None))

    def test_a_value_outside_the_public_list_is_not_guessed(self):
        self.assertEqual(len(self.find("Headache", "Value 9")), 1)

    def test_nothing_without_named_kinds(self):
        self.assertEqual(he.event_rows(self.conn, {}, SOURCES), [])
        self.assertEqual(he.event_rows(
            self.conn, {508: "HKQuantityTypeIdentifierStepCount"}, {}), [])
        self.assertEqual(he.datasets(self.conn, {}, {}), [])


class TableTests(unittest.TestCase):
    def test_the_table(self):
        conn = build(SAMPLES)
        self.addCleanup(conn.close)
        table, = he.datasets(conn, NAMES, SOURCES)
        self.assertEqual(table.key, "events")
        self.assertEqual(len(table.rows), len(SAMPLES) - 2)
        ordered = table.sorted_rows(table.rows)
        self.assertEqual([r["when"] for r in ordered],
                         sorted((r["when"] for r in table.rows),
                                reverse=True))
        self.assertIn("HealthKit documents", table.note)

    def test_it_comes_with_the_health_reader(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        fh.build_health(conn)
        data_id = 9000
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                     (data_id, fh.T0, fh.T0, fh.SLEEP + 1))
        keys = [d.key for d in hl.datasets(conn, None, "")]
        self.assertNotIn("events", keys)      # (no event kind is named there)


if __name__ == "__main__":
    unittest.main()
