# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Awards, sleep schedules and friends' activity, from invented data."""

import sqlite3
import unittest
from datetime import datetime, timezone

from ios_apps import health as hl
from ios_apps import health_more as hm
from tests import fixture_health as fh

DAY = 86400


def build(conn):
    conn.executescript("""
        CREATE TABLE samples (data_id INTEGER PRIMARY KEY, start_date REAL,
            end_date REAL, data_type INTEGER);
        CREATE TABLE ACHAchievementsPlugin_earned_instances (
            ROWID INTEGER PRIMARY KEY, template_unique_name TEXT,
            created_date REAL, earned_date TEXT,
            value_in_canonical_unit REAL, value_canonical_unit TEXT);
        CREATE TABLE sleep_schedule_samples (data_id INTEGER PRIMARY KEY,
            monday INTEGER, tuesday INTEGER, wednesday INTEGER,
            thursday INTEGER, friday INTEGER, saturday INTEGER,
            sunday INTEGER, wake_hour INTEGER, wake_minute INTEGER,
            bed_hour INTEGER, bed_minute INTEGER, override_day_index INTEGER);
        CREATE TABLE fitness_friend_workouts (data_id INTEGER PRIMARY KEY,
            friend_uuid BLOB, duration REAL, total_energy_burned REAL,
            total_distance REAL, activity_type INTEGER,
            is_indoor_workout INTEGER);
        CREATE TABLE fitness_friend_activity_snapshots (
            data_id INTEGER PRIMARY KEY, friend_uuid BLOB,
            energy_burned REAL, energy_burned_goal REAL, brisk_minutes REAL,
            brisk_minutes_goal REAL, active_hours REAL,
            active_hours_goal REAL, steps REAL, uploaded_date REAL);
        CREATE TABLE fitness_friend_achievements (data_id INTEGER PRIMARY KEY,
            friend_uuid BLOB);
    """)
    conn.executemany(
        "INSERT INTO ACHAchievementsPlugin_earned_instances (template_unique_"
        "name, created_date, earned_date, value_in_canonical_unit, "
        "value_canonical_unit) VALUES (?,?,?,?,?)", [
            ("NewMoveRecord", fh.T0, "2025-06-02", 650.25, "kcal"),
            ("MonthlyChallengeTypeTotalWorkouts_2024_02", fh.T0 + 1,
             "2024-02-29", 22.0, "count"),
            ("FirstWorkout-HKWorkoutActivityTypeCycling", fh.T0 + 2,
             "2024-01-05", None, None),
            ("100MoveGoals", fh.T0 + 3, "bad date", 100.0, "count"),
            ("BestWorkoutDistance-HKWorkoutActivityTypeFunctionalStrength"
             "Training", fh.T0 + 4, "2025-01-01", 2257.08, "m"),
            (None, fh.T0 + 5, None, None, None)])
    # schedules
    def schedule(data_id, start, days, bed, wake, override=None):
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, 0)",
                     (data_id, start, start))
        conn.execute("INSERT INTO sleep_schedule_samples VALUES "
                     "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (data_id, *days, wake[0] if wake else None,
                      wake[1] if wake else None, bed[0] if bed else None,
                      bed[1] if bed else None, override))
    schedule(1, fh.T0, [1] * 7, (22, 30), (7, 0))
    schedule(2, fh.T0 + DAY, [1, 1, 1, 1, 1, 0, 0], (23, 5), (6, 45))
    schedule(3, fh.T0 + 2 * DAY, [0] * 7, (22, 30), (8, 0), 60180)
    schedule(4, fh.T0 + 3 * DAY, [0] * 7, None, None, 60181)       # skipped
    # friends
    friend_a, friend_b = b"A" * 16, b"B" * 16
    conn.executemany("INSERT INTO samples VALUES (?, ?, ?, 0)", [
        (10, fh.T0, fh.T0), (11, fh.T0 + 100, fh.T0 + 100)])
    conn.execute("INSERT INTO fitness_friend_workouts VALUES "
                 "(10, ?, 1800, 300.5, 5000, 37, 0)", (friend_b,))
    conn.execute("INSERT INTO fitness_friend_workouts VALUES "
                 "(11, ?, 600, 50, NULL, 9999, 1)", (friend_a,))
    conn.executemany(
        "INSERT INTO fitness_friend_activity_snapshots VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (20, friend_a, 450.0, 500.0, 30.0, 30.0, 10.0, 12.0, 8000.0,
             fh.T0 + 5),
            (21, friend_a, 10.0, None, None, None, None, None, None,
             fh.T0 + 6)])
    conn.execute("INSERT INTO fitness_friend_achievements VALUES (30, ?)",
                 (friend_b,))
    conn.commit()


class TextTests(unittest.TestCase):
    def test_internal_names_become_words(self):
        for name, shown in (
                ("NewMoveRecord", "New move record"),
                ("100MoveGoals", "100 move goals"),
                ("MonthlyChallengeTypeTotalWorkouts_2024_02",
                 "Monthly challenge type total workouts 2024 02"),
                ("PerfectMonth", "Perfect month"), ("", ""), (None, "")):
            self.assertEqual(hm.humanize(name), shown)

    def test_a_workout_type_in_a_name_is_looked_up(self):
        names = {v.lower().replace(" ", ""): v
                 for v in hl.WORKOUT_TYPES.values()}
        self.assertEqual(hm.award_name(
            "FirstWorkout-HKWorkoutActivityTypeCycling", names),
            "First workout (Cycling)")
        self.assertEqual(hm.award_name(
            "BestWorkout-HKWorkoutActivityTypeHighIntensityIntervalTraining",
            names), "Best workout (High intensity interval training)")
        self.assertEqual(hm.award_name(
            "HKWorkoutActivityTypeRunning", names), "Running")
        self.assertEqual(hm.award_name("x-HKWorkoutActivityTypeInvented",
                                       names), "X (Invented)")

    def test_values_with_their_units(self):
        self.assertEqual(hm._unit(650.25, "kcal"), "650 kcal")
        self.assertEqual(hm._unit(22.0, "count"), "22")
        self.assertEqual(hm._unit(5.5, "min"), "5.5 min")
        self.assertEqual(hm._unit(2257.08, "m"), "2,257 m")
        self.assertEqual(hm._unit(None, "m"), "")

    def test_a_modified_julian_date(self):
        day = hm.mjd_day(60180)
        self.assertEqual(datetime.fromtimestamp(day, timezone.utc).date()
                         .isoformat(), "2023-08-24")
        self.assertIsNone(hm.mjd_day(None))
        self.assertIsNone(hm.mjd_day("x"))
        self.assertIsNone(hm.mjd_day(10 ** 12))


class TableTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        build(self.conn)
        self.sets = {d.key: d for d in hm.datasets(self.conn, hl.WORKOUT_TYPES)}

    def test_the_tables(self):
        self.assertEqual(list(self.sets), [
            "awards", "sleep_schedules", "friend_workouts",
            "friend_activity"])

    def test_awards(self):
        rows = self.sets["awards"].rows
        self.assertEqual(len(rows), 6)
        by_internal = {r["internal"]: r for r in rows}
        record = by_internal["NewMoveRecord"]
        self.assertEqual((record["award"], record["value"]),
                         ("New move record", "650 kcal"))
        self.assertEqual(
            datetime.fromtimestamp(record["day"], timezone.utc).date()
            .isoformat(), "2025-06-02")
        # a date that cannot be read falls back to when it was created
        self.assertIsNotNone(by_internal["100MoveGoals"]["day"])
        self.assertIn("Internal name: NewMoveRecord",
                      self.sets["awards"].details(record))

    def test_sleep_schedules(self):
        rows = self.sets["sleep_schedules"].rows
        self.assertEqual([r["kind"] for r in rows], [
            "Schedule", "Schedule", "One-day change", "One-day change"])
        self.assertEqual((rows[0]["days"], rows[0]["bed"], rows[0]["wake"]),
                         ("Every day", "22:30", "07:00"))
        self.assertEqual(rows[1]["days"], "Mon, Tue, Wed, Thu, Fri")
        self.assertEqual((rows[2]["bed"], rows[2]["wake"]), ("22:30", "08:00"))
        self.assertEqual(datetime.fromtimestamp(rows[2]["for"], timezone.utc)
                         .date().isoformat(), "2023-08-24")
        self.assertEqual((rows[3]["bed"], rows[3]["wake"]),
                         ("(skipped)", "(skipped)"))

    def test_friends_are_numbered_in_order_of_appearance(self):
        workouts = self.sets["friend_workouts"].rows
        # (friend A has activity summaries, so is the first to appear)
        self.assertEqual([(w["friend"], w["kind"]) for w in workouts],
                         [("Friend 2", "Running"), ("Friend 1", "Type 9999")])
        self.assertTrue(workouts[1]["indoor"])
        activity = self.sets["friend_activity"].rows
        self.assertEqual({a["friend"] for a in activity}, {"Friend 1"})

    def test_friends_activity_shows_value_and_goal(self):
        table = self.sets["friend_activity"]
        row = table.sorted_rows(table.rows, "when", False)[0]
        shown = {c.key: c.show(row.get(c.key), row) for c in table.columns}
        self.assertEqual(shown["move"], "450 / 500 kcal")
        self.assertEqual(shown["exercise"], "30 / 30 min")
        self.assertEqual(shown["stand"], "10 / 12 h")
        self.assertEqual(shown["steps"], "8,000")


def audiogram_payload(points, extra_keys=None):
    """An NSKeyedArchiver archive of an audiogram's points (frequency in Hz,
    hearing levels in dB HL), as Health stores it."""
    from tests.keyed_builder import archive

    def quantity(value, unit_class, unit):
        return {"$class": "HKQuantity", "ValueKey": value,
                "UnitKey": {"$class": unit_class, "HKUnitStringKey": unit}}

    return archive([
        {"$class": "HKAudiogramSensitivityPoint",
         "FrequencyKey": quantity(f, "HKFrequencyUnit", "Hz"),
         "LeftEarSensitivityKey": quantity(l, "HKDecibelHearingLevelUnit",
                                           "dBHL") if l is not None else None,
         "RightEarSensitivityKey": quantity(r, "HKDecibelHearingLevelUnit",
                                            "dBHL"), **(extra_keys or {})}
        for f, l, r in points])


class AudiogramTests(unittest.TestCase):
    NAMES = {145: "HKDataTypeIdentifierAudiogram", 7: "HKQuantityTypeX"}

    def database(self, payloads):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE samples (data_id INTEGER PRIMARY KEY,
                start_date REAL, end_date REAL, data_type INTEGER);
            CREATE TABLE binary_samples (data_id INTEGER PRIMARY KEY,
                payload BLOB);""")
        for number, (kind, start, payload) in enumerate(payloads, 1):
            conn.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                         (number, start, start, kind))
            conn.execute("INSERT INTO binary_samples VALUES (?, ?)",
                         (number, payload))
        return conn

    def test_the_points_of_an_audiogram(self):
        conn = self.database([(145, fh.T0, audiogram_payload(
            [(250, 20.0, 25.5), (500, None, 30.1), (1000, 10, 12)]))])
        rows = hm.audiogram_rows(conn, self.NAMES)
        self.assertEqual([(r["frequency"], r["left"], r["right"])
                          for r in rows],
                         [(250, 20.0, 25.5), (500, None, 30.1), (1000, 10, 12)])
        self.assertEqual({r["level_unit"] for r in rows}, {"dBHL"})
        table, = hm.datasets(conn, hl.WORKOUT_TYPES, self.NAMES)
        shown = [{c.key: c.show(r.get(c.key), r) for c in table.columns}
                 for r in table.rows]
        self.assertEqual(shown[0]["frequency"], "250 Hz")
        self.assertEqual(shown[0]["left"], "20 dBHL")
        self.assertEqual(shown[1]["left"], "")
        self.assertIn("Lower levels mean better hearing", table.note)

    def test_only_audiograms_are_read(self):
        conn = self.database([(7, fh.T0, audiogram_payload([(250, 1, 1)]))])
        self.assertEqual(hm.audiogram_rows(conn, self.NAMES), [])
        self.assertEqual(hm.audiogram_rows(conn, {}), [])

    def test_damaged_payloads_are_skipped(self):
        conn = self.database([
            (145, fh.T0, b"not a plist"), (145, fh.T0 + 1, b"bplist00junk"),
            (145, fh.T0 + 2, audiogram_payload([(250, 1, 2)]))])
        self.assertEqual(len(hm.audiogram_rows(conn, self.NAMES)), 1)

    def test_a_point_without_a_frequency_is_skipped(self):
        payload = audiogram_payload([(250, 1, 2)])
        conn = self.database([(145, fh.T0, payload)])
        rows = hm.audiogram_rows(conn, self.NAMES)
        self.assertEqual(len(rows), 1)

    def test_no_table_in_the_database(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(hm.audiogram_rows(conn, self.NAMES), [])


class MissingTests(unittest.TestCase):
    def test_nothing_without_the_tables(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(hm.datasets(conn, hl.WORKOUT_TYPES), [])

    def test_empty_tables_make_no_tables(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        build(conn)
        for table in ("ACHAchievementsPlugin_earned_instances",
                      "sleep_schedule_samples", "fitness_friend_workouts",
                      "fitness_friend_activity_snapshots"):
            conn.execute(f"DELETE FROM {table}")
        self.assertEqual(hm.datasets(conn, hl.WORKOUT_TYPES), [])


class ReaderTests(unittest.TestCase):
    def test_they_come_with_the_health_reader(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        fh.build_health(conn)
        for sql in ("DELETE FROM samples WHERE 0",):
            conn.execute(sql)
        conn.execute("CREATE TABLE ACHAchievementsPlugin_earned_instances ("
                     "ROWID INTEGER PRIMARY KEY, template_unique_name TEXT, "
                     "created_date REAL, earned_date TEXT, "
                     "value_in_canonical_unit REAL, value_canonical_unit "
                     "TEXT)")
        conn.execute("INSERT INTO ACHAchievementsPlugin_earned_instances "
                     "(template_unique_name, created_date, earned_date) "
                     "VALUES ('NewMoveGoalAchieved', 1, '2025-01-01')")
        keys = [d.key for d in hl.datasets(conn, None, "")]
        self.assertIn("awards", keys)


if __name__ == "__main__":
    unittest.main()
