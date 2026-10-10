# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Health: names read from the database itself, activity, workouts and
their routes, body measurements, sleep, records, Medical ID, and the tab in
the window."""

import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from file_index import FileIndex
from ios_apps import health as hl
from ios_apps import records_export as rx
from ios_apps import records_view as rv
from ios_apps.common import APPLE_EPOCH
from tests import fixture_health as fh
from tests.fixture_apps import T0
from tests.gui_apps import AppGuiCase

DAY = fh.DAY


def make_index(files):
    rows = [(f"id{n}", d, p, 1, len(data), 0, 0)
            for n, (d, p, data) in enumerate(files)]
    return FileIndex(rows)


class ReaderCase(unittest.TestCase):
    def setUp(self, **kw):
        self.tmp = tempfile.mkdtemp(prefix="ibe-health-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for _d, path, data in fh.backup_files(**kw):
            with open(os.path.join(self.tmp, os.path.basename(path)),
                      "wb") as handle:
                handle.write(data)
        main = os.path.join(self.tmp, "healthdb_secure.sqlite")
        self.conn = sqlite3.connect(main if os.path.exists(main)
                                    else os.path.join(self.tmp, "x"))
        self.addCleanup(self.conn.close)
        self.data = {}
        if os.path.exists(main):
            reader = hl.HealthReader(self.conn)
            self.data = {d.key: d for d in reader.datasets()}

    def rows(self, key):
        return self.data[key].rows


class NameTests(ReaderCase):
    def test_the_database_names_its_kinds(self):
        names = hl.kind_names(self.conn)
        self.assertEqual(names[fh.STEPS], "HKQuantityTypeIdentifierStepCount")
        self.assertEqual(names[fh.SLEEP],
                         "HKCategoryTypeIdentifierSleepAnalysis")
        self.assertEqual(names[fh.WORKOUT], "HKWorkoutTypeIdentifier")
        self.assertEqual(len(names), 12)

    def test_a_number_with_two_names_or_none_is_not_named(self):
        names = hl.kind_names(self.conn)
        self.assertNotIn(fh.TWINS, names)          # two different names
        self.assertNotIn(fh.UNKNOWN, names)        # no name at all
        self.assertEqual(hl.kind_label(fh.TWINS, names), f"Type {fh.TWINS}")

    def test_readable_labels(self):
        for identifier, label in (
                ("HKQuantityTypeIdentifierStepCount", "Step count"),
                ("HKQuantityTypeIdentifierVO2Max", "VO2 max"),
                ("HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
                 "Heart rate variability SDNN"),
                ("HKWorkoutTypeIdentifier", "Workout"),
                ("HKActivitySummaryTypeIdentifier", "Activity summary"),
                ("HKCorrelationTypeIdentifierBloodPressure",
                 "Blood pressure"),
                ("Unrecognised", "Unrecognised")):
            self.assertEqual(hl.words(identifier), label)

    def test_a_database_without_summaries(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(hl.kind_names(conn), {})


class OverviewTests(ReaderCase):
    def test_every_kind_is_counted(self):
        rows = {r["number"]: r for r in self.rows("types")}
        self.assertEqual(rows[fh.BODY_MASS]["type"], "Body mass")
        self.assertEqual(rows[fh.BODY_MASS]["count"], 2)
        self.assertEqual(rows[fh.SLEEP]["count"], 7)
        self.assertEqual(rows[fh.UNKNOWN]["type"], f"Type {fh.UNKNOWN}")
        self.assertEqual(rows[fh.UNKNOWN]["kind"], "")
        self.assertEqual(rows[fh.STEPS]["kind"], "Measurement")
        self.assertEqual(rows[fh.SLEEP]["kind"], "Event or state")
        self.assertEqual(rows[fh.WORKOUT]["kind"], "Workout")
        self.assertEqual(rows[fh.BODY_MASS]["first"], T0 + APPLE_EPOCH)
        self.assertEqual(rows[fh.BODY_MASS]["last"],
                         T0 + DAY + APPLE_EPOCH)

    def test_ordered_by_how_many(self):
        data = self.data["types"]
        counts = [r["count"] for r in data.sorted_rows(data.rows)]
        self.assertEqual(counts, sorted(counts, reverse=True))


class ActivityTests(ReaderCase):
    def test_days(self):
        rows = {r["day"]: r for r in self.rows("activity")}
        self.assertEqual(len(rows), 3)
        day = rows[hl.utc_datetime(fh.D0 + APPLE_EPOCH).strftime("%Y-%m-%d")]
        self.assertEqual((day["steps"], day["energy"], day["exercise"],
                          day["stand"], day["flights"], day["distance"]),
                         (8000, 450, 30, 11, 9, 6123))
        self.assertEqual((day["move_goal"], day["exercise_goal"],
                          day["stand_goal"]), (500.0, 30.0, 12.0))

    def test_days_with_nothing_or_missing_numbers(self):
        rows = sorted(self.rows("activity"), key=lambda r: r["day"])
        self.assertEqual(rows[0]["flights"], 0)         # (None stored)
        self.assertEqual(rows[0]["distance"], 0)
        self.assertEqual(rows[2]["steps"], 0)

    def test_the_details(self):
        text = self.data["activity"].details(
            next(r for r in self.rows("activity") if r["steps"] == 8000))
        for expected in ("Steps: 8,000", "Active energy: 450 kcal (goal 500)",
                         "Exercise: 30 min (goal 30)", "Stand: 11 h (goal 12)",
                         "Flights climbed: 9", "6.12 km"):
            self.assertIn(expected, text)


class WorkoutTests(ReaderCase):
    def setUp(self):
        super().setUp()
        self.by = {r["type"]: r for r in self.rows("workouts")}

    def test_the_activity_names(self):
        self.assertEqual(sorted(self.by), ["Running", "Walking"])
        self.assertEqual(hl.WORKOUT_TYPES[80], "Cooldown")
        self.assertEqual(hl.WORKOUT_TYPES[3000], "Other")

    def test_a_run(self):
        run = self.by["Running"]
        self.assertEqual((run["duration"], run["distance"], run["energy"],
                          run["heart_avg"], run["heart_max"], run["route"]),
                         (1800, 5000, 400, 150, 180, "yes"))
        self.assertEqual(run["when"], T0 + 100 + APPLE_EPOCH)
        self.assertEqual(run["source"], "Sam's iPhone")

    def test_a_walk_with_only_what_the_workout_row_says(self):
        walk = self.by["Walking"]
        self.assertEqual(walk["duration"], 600)         # from its dates
        self.assertEqual(walk["distance"], 1200)        # kilometres -> metres
        self.assertIsNone(walk["energy"])
        self.assertIsNone(walk["heart_avg"])
        self.assertEqual((walk["route"], walk["points"]), ("", []))
        self.assertEqual(walk["source"], "Smart Scale")

    def test_the_route(self):
        points = self.by["Running"]["points"]
        self.assertEqual(len(points), 3)
        self.assertEqual((points[0]["lat"], points[0]["lon"],
                          points[0]["altitude"]), (12.5, -45.25, 10.0))
        self.assertEqual(points[0]["time"], T0 + 100 + APPLE_EPOCH)
        self.assertIsNone(points[2]["altitude"])
        self.assertEqual(points, sorted(points, key=lambda p: p["time"]))

    def test_the_details(self):
        text = self.data["workouts"].details(self.by["Running"])
        for expected in ("Running", "Distance: 5.00 km",
                         "Active energy: 400 kcal",
                         "Heart rate: average 150, highest 180 bpm",
                         "Route: 3 points", "Recorded by: Sam's iPhone"):
            self.assertIn(expected, text)

    def test_the_route_file(self):
        out = os.path.join(self.tmp, "out")
        (path,) = rx.export(self.data["workouts"], self.rows("workouts"),
                            "gpx", out)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text.count("<trk>"), 1)       # only the run
        self.assertEqual(text.count("<trkpt "), 3)
        self.assertIn('<trkpt lat="12.5000000" lon="-45.2500000">', text)
        self.assertIn("<ele>10.00</ele>", text)
        self.assertEqual(text.count("<ele>"), 2)       # (one has none)
        stamp = hl.utc_datetime(T0 + 100 + APPLE_EPOCH)
        self.assertIn(stamp.strftime("<time>%Y-%m-%dT%H:%M:%SZ</time>"), text)
        self.assertTrue(text.startswith('<?xml version="1.0"'))
        self.assertTrue(text.rstrip().endswith("</gpx>"))

    def test_route_names_are_escaped(self):
        row = dict(self.by["Running"], type="A & <B>")
        path = os.path.join(self.tmp, "x")
        (written,) = hl.write_gpx(path, [row])
        with open(written, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("A &amp; &lt;B&gt;", text)
        self.assertNotIn("<B>", text)

    def test_the_formats_offered(self):
        self.assertEqual(list(rx.formats_for(self.data["workouts"]))[-1],
                         "gpx")


class MeasurementTests(ReaderCase):
    def setUp(self):
        super().setUp()
        self.by = {}
        for row in self.rows("measurements"):
            self.by.setdefault(row["measurement"], []).append(row)

    def test_only_checked_kinds_are_listed(self):
        self.assertEqual(sorted(self.by), sorted([
            "Weight", "BMI", "Body fat", "Height", "Blood oxygen",
            "Respiratory rate", "Resting heart rate"]))
        self.assertEqual(len(self.rows("measurements")), 8)

    def test_values_in_their_units(self):
        value = lambda name, i=0: (self.by[name][i]["value"],
                                   self.by[name][i]["unit"])
        self.assertEqual(value("Weight"), (100.0, "kg"))
        self.assertEqual(value("Body fat"), (25.0, "%"))
        self.assertEqual(value("Height"), (190.5, "cm"))
        self.assertEqual(value("Blood oxygen"), (97.0, "%"))
        self.assertEqual(value("Respiratory rate"), (15.0, "breaths/min"))
        self.assertEqual(value("Resting heart rate"), (60.0, "bpm"))
        self.assertEqual(value("BMI"), (30.5, "kg/m²"))

    def test_an_empty_value_is_skipped(self):
        self.assertEqual(len(self.by["Resting heart rate"]), 1)

    def test_who_recorded_it(self):
        self.assertEqual([r["source"] for r in self.by["Weight"]],
                         ["Sam's iPhone", "Smart Scale"])

    def test_the_text_of_a_value(self):
        self.assertEqual(hl._value_text(self.by["Weight"][0]), "100.0")
        self.assertEqual(hl._value_text(self.by["Blood oxygen"][0]), "97")

    def test_without_the_sources_database(self):
        ReaderCase.setUp(self, sources=False)
        rows = self.rows("measurements")
        self.assertEqual({r["source"] for r in rows}, {""})


class SleepAndRecordTests(ReaderCase):
    def test_the_stages(self):
        rows = sorted(self.rows("sleep"), key=lambda r: r["when"])
        self.assertEqual([r["stage"] for r in rows], [
            "In bed", "Asleep (core)", "Asleep (deep)", "Asleep (REM)",
            "Awake", "Asleep", "Value 9"])
        self.assertEqual([r["length"] for r in rows],
                         [600, 600, 600, 600, 120, 600, 600])
        self.assertEqual(rows[0]["when"], T0 + APPLE_EPOCH)
        self.assertEqual(rows[0]["end"], T0 + 600 + APPLE_EPOCH)

    def test_the_health_records(self):
        rows = self.rows("records")
        self.assertEqual([(r["type"], r["name"]) for r in rows], [
            ("Observation", "Blood test <A>"), ("", ""),
            ("Immunization", "Flu shot")])
        self.assertEqual(rows[0]["when"], T0 + 50 + APPLE_EPOCH)


class MedicalIdTests(ReaderCase):
    def test_what_the_card_says(self):
        rows = [(r["item"], r["value"]) for r in self.rows("medical_id")]
        self.assertEqual(rows, [
            ("Name", "Sam Example"), ("Date of birth", "1980-02-09"),
            ("Height", "190.5 cm"),
            ("Medical conditions", "Condition A; condition B"),
            ("Organ donor", "yes"),
            ("Emergency contact", "Alex Example, Friend, 555 010 7777"),
            ("Emergency contact", "Pat Sample")])

    def test_the_picture_and_dates_are_not_shown(self):
        text = " ".join(f"{r['item']} {r['value']}"
                        for r in self.rows("medical_id"))
        self.assertNotIn("PNG", text)
        self.assertNotIn("2025", text)

    def test_a_birth_date_as_a_date(self):
        from datetime import datetime
        self.assertEqual(hl._birthdate(datetime(1975, 3, 4)), "1975-03-04")
        self.assertEqual(hl._birthdate(None), "")
        self.assertEqual(hl._birthdate({"NS.year": 1}), "")

    def test_a_damaged_archive(self):
        path = os.path.join(self.tmp, "MedicalIDData.archive")
        for data in (b"", b"junk", b"bplist00 NSKeyedArchiver"):
            with open(path, "wb") as handle:
                handle.write(data)
            self.assertEqual(hl.medical_id_rows(path), [])
        self.assertEqual(hl.medical_id_rows(os.path.join(self.tmp, "no")), [])

    def test_only_a_medical_id(self):
        ReaderCase.setUp(self, health=False, sources=False)
        folder = self.tmp
        self.assertEqual([d.key for d in hl.medical_only(folder)],
                         ["medical_id"])


class FilesTests(unittest.TestCase):
    def test_what_a_tab_copies(self):
        index = make_index(fh.backup_files())
        self.assertEqual(hl.discover(index), [
            hl.HEALTH, hl.SOURCES, hl.MEDICAL_ID])
        only = make_index(fh.backup_files(health=False, sources=False))
        self.assertEqual(hl.discover(only), [hl.MEDICAL_ID])
        self.assertEqual(hl.discover(make_index([])), [])
        self.assertEqual(hl.discover(None), [])


class HealthGuiCase(AppGuiCase):
    def open_health(self, encrypted=False, **kw):
        self.open_files(fh.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Health")

    def show(self):
        tab = self.show_tab("Health")
        self.wait_for(lambda: tab.datasets, "the health tables")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]

    def choose(self, title):
        self.tab.dataset_var.set(title)
        self.tab.choose_dataset()


class WindowTests(HealthGuiCase):
    def test_the_tab_appears_only_with_health_data(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertNotIn("Health", self.tab_titles())
        self.open_health()
        self.assertIn("Health", self.tab_titles())

    def test_the_tables(self):
        self.open_health()
        tab = self.show()
        self.assertEqual(list(tab.datasets), [
            "medical_id", "activity", "workouts", "measurements", "sleep",
            "records", "types"])
        self.assertIn("Sam Example", self.column("value"))
        self.choose("Workouts")
        self.assertEqual(self.column("type"), ["Walking", "Running"])
        self.assertEqual(self.column("route"), ["", "yes"])
        self.choose("Body and vitals")
        self.assertIn("100.0", self.column("value"))
        self.assertEqual(tab.state_var.get(), "8 rows")
        self.choose("Data types")
        self.assertEqual(self.column("count")[0], "7")

    def test_search_across_a_table(self):
        self.open_health()
        tab = self.show()
        self.choose("Body and vitals")
        tab.search_var.set("scale")
        tab.refresh()
        self.assertEqual(self.column("measurement"), ["Weight"])

    def test_export_the_routes(self):
        self.open_health()
        tab = self.show()
        self.choose("Workouts")
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(rv, "ask_export",
                               return_value=("gpx", "all", out)):
            tab.export()
            self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        with open(os.path.join(out, "workouts.gpx"), encoding="utf-8") as f:
            self.assertEqual(len(re.findall("<trkpt ", f.read())), 3)

    def test_original_files(self):
        self.open_health()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        wanted = {self.ids[(d, p)] for d, p, _ in fh.backup_files()}
        self.assertEqual(set(ids), wanted)

    def test_an_encrypted_backup(self):
        self.open_health(encrypted=True)
        tab = self.show()
        self.assertEqual(len(tab.datasets["sleep"].rows), 7)

    def test_only_a_medical_id(self):
        self.open_health(health=False, sources=False)
        tab = self.show()
        self.assertEqual(list(tab.datasets), ["medical_id"])


if __name__ == "__main__":
    unittest.main()
