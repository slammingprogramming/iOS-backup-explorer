# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The demo phone's Health data: activity, workouts with routes, body
measurements, sleep, records and Medical ID."""

import math
import random
from datetime import datetime, timedelta, timezone

from . import NOW, ago, clone_schema, cocoa

DOMAIN = "HealthDomain"

TYPES = {
    0: "HKQuantityTypeIdentifierBodyMassIndex",
    1: "HKQuantityTypeIdentifierBodyFatPercentage",
    2: "HKQuantityTypeIdentifierHeight",
    3: "HKQuantityTypeIdentifierBodyMass",
    5: "HKQuantityTypeIdentifierHeartRate",
    7: "HKQuantityTypeIdentifierStepCount",
    8: "HKQuantityTypeIdentifierDistanceWalkingRunning",
    9: "HKQuantityTypeIdentifierBasalEnergyBurned",
    10: "HKQuantityTypeIdentifierActiveEnergyBurned",
    12: "HKQuantityTypeIdentifierFlightsClimbed",
    14: "HKQuantityTypeIdentifierOxygenSaturation",
    61: "HKQuantityTypeIdentifierRespiratoryRate",
    63: "HKCategoryTypeIdentifierSleepAnalysis",
    70: "HKCategoryTypeIdentifierAppleStandHour",
    75: "HKQuantityTypeIdentifierAppleExerciseTime",
    79: "HKWorkoutTypeIdentifier",
    118: "HKQuantityTypeIdentifierRestingHeartRate",
    124: "HKQuantityTypeIdentifierVO2Max",
    137: "HKQuantityTypeIdentifierWalkingHeartRateAverage",
    139: "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    186: "HKQuantityTypeIdentifierAppleStandTime",
    187: "HKQuantityTypeIdentifierWalkingSpeed",
    188: "HKQuantityTypeIdentifierWalkingStepLength",
}
ROUTE_TYPE, RECORD_TYPE = 102, 119_000
CENTRE = (39.7990, -89.6440)         # (the middle of an invented town)


def _utc_day(days):
    day = NOW - timedelta(days=days)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def health(writer):
    from tests import fixture_health as fh
    rng = random.Random(21)

    def build(conn):
        clone_schema(fh.build_health, conn)
        row = 0
        for number, identifier in TYPES.items():
            for what in ("CurrentValue", "ChartModel"):
                row += 1
                conn.execute("INSERT INTO shared_summaries (ROWID, name) "
                             "VALUES (?, ?)",
                             (row, fh.summary_name(identifier, what)))
                conn.execute("INSERT INTO shared_summary_object_types "
                             "(summary_id, object_type) VALUES (?, ?)",
                             (row, number))
        conn.executemany("INSERT INTO data_provenances VALUES (?, ?)",
                         [(1, 10), (2, 20), (3, 30)])
        ids = [1000]

        def sample(kind, start, end=None, provenance=1, data_id=None):
            data_id = data_id or ids[0]
            ids[0] = max(ids[0], data_id) + 1
            start = cocoa(start) if isinstance(start, datetime) else start
            end = start if end is None else (
                cocoa(end) if isinstance(end, datetime) else end)
            conn.execute("INSERT INTO samples VALUES (?,?,?,?)",
                         (data_id, start, end, kind))
            conn.execute("INSERT INTO objects VALUES (?, NULL, ?, 1, ?)",
                         (data_id, provenance, start))
            return data_id

        def quantity(kind, start, value, end=None, provenance=1):
            data_id = sample(kind, start, end, provenance)
            conn.execute("INSERT INTO quantity_samples VALUES "
                         "(?,?,NULL,NULL)", (data_id, value))

        # activity, the phone's own daily summaries
        for days in range(0, 90):
            day = _utc_day(days)
            weekday = day.weekday()
            steps = max(1500, int(rng.gauss(8200 if weekday < 5 else 9600,
                                            2600)))
            energy = max(80.0, rng.gauss(520, 160))
            exercise = max(0, int(rng.gauss(33, 15)))
            conn.execute(
                "INSERT INTO activity_caches (cache_index, energy_burned, "
                "energy_burned_goal, brisk_minutes, brisk_minutes_goal, "
                "active_hours, active_hours_goal, steps, walk_distance, "
                "flights) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cocoa(day), energy, 600.0, exercise, 30.0,
                 min(14, max(3, int(rng.gauss(10, 3)))), 12.0, float(steps),
                 steps * 0.76, float(rng.randrange(1, 18))))
        # the samples behind some of it (a month of them)
        for days in range(0, 30):
            day = _utc_day(days)
            for hour in range(7, 22, 2):
                moment = day + timedelta(hours=hour)
                bpm = rng.gauss(74, 9)
                quantity(5, moment, bpm / 60, provenance=2)
                quantity(7, moment, rng.randrange(80, 900),
                         end=moment + timedelta(minutes=30))
                quantity(10, moment, rng.uniform(5, 60),
                         end=moment + timedelta(minutes=30), provenance=2)
                quantity(9, moment, rng.uniform(40, 70),
                         end=moment + timedelta(minutes=30))
                quantity(8, moment, rng.uniform(100, 700),
                         end=moment + timedelta(minutes=30))
            quantity(12, day + timedelta(hours=15), rng.randrange(1, 12))
        # body and vitals
        for week in range(0, 26):
            moment = ago(days=week * 7 + 2, hours=7)
            weight = 78.5 - week * 0.12 + rng.gauss(0, .4)
            quantity(3, moment, weight, provenance=3)
            quantity(0, moment, weight / 1.75 ** 2, provenance=3)
            quantity(1, moment, 0.21 + week * .0004 + rng.gauss(0, .003),
                     provenance=3)
        quantity(2, ago(days=300), 1.75)
        for days in range(0, 60):
            moment = ago(days=days, hours=8)
            quantity(118, moment, rng.gauss(58, 3), provenance=2)
            quantity(137, moment, rng.gauss(96, 6), provenance=2)
            quantity(139, moment, rng.gauss(55, 14), provenance=2)
            quantity(61, moment, rng.gauss(15, 1.3) / 60, provenance=2)
            if days % 3 == 0:
                quantity(14, moment, min(1.0, rng.gauss(.97, .01)),
                         provenance=2)
        for days in (4, 40, 110, 200):
            quantity(124, ago(days=days), rng.gauss(43, 1), provenance=2)
        # sleep: a night is a run of stages
        for night in range(0, 21):
            start = _utc_day(night) - timedelta(hours=1, minutes=rng.randrange(
                0, 90))
            stages = []
            moment = start
            while moment < start + timedelta(hours=7, minutes=20):
                stage = rng.choice((3, 3, 3, 4, 5, 5, 2))
                length = timedelta(minutes=rng.randrange(
                    8 if stage == 2 else 20, 25 if stage == 2 else 75))
                stages.append((stage, moment, moment + length))
                moment += length
            for stage, first, last in stages:
                data_id = sample(63, first, last, provenance=2)
                conn.execute("INSERT INTO category_samples VALUES (?, ?)",
                             (data_id, stage))
        # workouts
        plan = [(37, 1, 38, True), (52, 2, 31, False), (37, 4, 44, True),
                (13, 6, 62, False), (57, 7, 40, False), (24, 9, 128, True),
                (52, 11, 36, False), (37, 13, 41, False), (13, 16, 55, False),
                (16, 19, 30, False), (37, 21, 47, False), (20, 24, 45, False)]
        route_key = 0
        for number, (kind, days, minutes, with_route) in enumerate(plan, 1):
            start = ago(days=days, hours=3 + number % 4)
            end = start + timedelta(minutes=minutes)
            workout = sample(79, start, end, provenance=2, data_id=500 + number)
            speed = {37: 2.9, 52: 1.4, 13: 6.5, 24: 1.3}.get(kind, 0)
            distance = speed * minutes * 60
            conn.execute("INSERT INTO workouts VALUES (?, NULL)", (workout,))
            conn.execute(
                "INSERT INTO workout_activities (ROWID, owner_id, "
                "is_primary_activity, activity_type, start_date, end_date, "
                "duration) VALUES (?,?,1,?,?,?,?)",
                (number, workout, kind, cocoa(start), cocoa(end),
                 minutes * 60.0))
            stats = [(10, minutes * rng.uniform(6, 10), None, None),
                     (5, rng.uniform(1.9, 2.4), 1.5, 2.8)]
            if distance:
                stats.append((8, distance, None, None))
            for data_type, value, low, high in stats:
                conn.execute(
                    "INSERT INTO workout_statistics (workout_activity_id, "
                    "data_type, quantity, min, max) VALUES (?,?,?,?,?)",
                    (number, data_type, value, low, high))
            if with_route:
                route_key += 1
                route = sample(ROUTE_TYPE, start, end, provenance=2,
                               data_id=800 + number)
                conn.execute("INSERT INTO associations (parent_id, "
                             "child_id) VALUES (?, ?)", (workout, route))
                points = max(60, minutes * 6)
                conn.execute("INSERT INTO data_series VALUES "
                             "(?, 1, ?, 1, ?, 2)",
                             (route, points, route_key))
                radius = .004 + number * .0006
                tilt = number * .7
                for step in range(points):
                    angle = step / points * 2 * math.pi
                    lat = CENTRE[0] + radius * math.sin(angle) \
                        + 0.0008 * math.sin(angle * 3 + tilt)
                    lon = CENTRE[1] + radius * 1.3 * math.cos(angle) \
                        + 0.0006 * math.cos(angle * 2)
                    conn.execute(
                        "INSERT INTO location_series_data VALUES "
                        "(?,?,?,?,?,?,?,?)",
                        (route_key, cocoa(start) + step * minutes * 60
                         / points, lat, lon, 190 + 6 * math.sin(angle * 2),
                         speed or 1.3, math.degrees(angle) % 360, 5.0))
        # records from care providers
        for name, kind in (
                ("Hemoglobin A1c", "Observation"),
                ("Complete blood count", "Observation"),
                ("Lipid panel", "Observation"),
                ("Vitamin D, 25-hydroxy", "Observation"),
                ("Influenza vaccine", "Immunization"),
                ("Tetanus, diphtheria and pertussis vaccine",
                 "Immunization"),
                ("Cetirizine 10 mg tablet", "MedicationRequest"),
                ("Allergic rhinitis", "Condition")):
            data_id = sample(RECORD_TYPE, ago(days=rng.randrange(20, 400)))
            conn.execute("INSERT INTO clinical_record_samples VALUES "
                         "(?, ?, ?)", (data_id, name, kind))

    def sources(conn):
        clone_schema(fh.build_sources, conn)
        conn.executemany("INSERT INTO sources (ROWID, name) VALUES (?, ?)", [
            (10, "Taylor's iPhone"), (20, "Taylor's Apple Watch"),
            (30, "Smart Scale")])

    writer.database(DOMAIN, fh.HEALTH, build)
    writer.database(DOMAIN, fh.SOURCES, sources)
    writer.file(DOMAIN, fh.MEDICAL_ID, medical_id())


def medical_id():
    from tests.keyed_builder import archive
    return archive({
        "$class": "HKMedicalIDData",
        "HKMedicalIDDataNameKey": "Taylor Morgan",
        "HKMedicalIDDataGregorianBirthdateKey": {
            "$class": "NSDateComponents", "NS.year": 1992, "NS.month": 6,
            "NS.day": 17},
        "HKMedicalIDDataHeightKey": {
            "$class": "HKQuantity", "ValueKey": 175.0,
            "UnitKey": {"$class": "HKUnit", "HKUnitStringKey": "cm"}},
        "HKMedicalIDDataWeightKey": {
            "$class": "HKQuantity", "ValueKey": 72.0,
            "UnitKey": {"$class": "HKUnit", "HKUnitStringKey": "kg"}},
        "HKMedicalIDDataMedicalConditionsKey": "Seasonal allergies",
        "HKMedicalIDDataAllergyInfoKey": "Penicillin",
        "HKMedicalIDDataMedicationInfoKey": "Cetirizine 10 mg, once a day",
        "HKMedicalIDDataMedicalNotesKey":
            "Wears glasses. Please contact my emergency contacts.",
        "HKMedicalIDDataPrimaryLanguageCodeKey": "en",
        "HKMedicalIDDataIsOrganDonorKey": True,
        "HKMedicalIDDataEmergencyContactsKey": [
            {"$class": "HKEmergencyContact",
             "HKEmergencyContactNameKey": "Dana Morgan",
             "HKEmergencyContactRelationshipKey": "_$!<Mother>!$_",
             "HKEmergencyContactPhoneNumberKey": "(555) 010-0112"},
            {"$class": "HKEmergencyContact",
             "HKEmergencyContactNameKey": "Alex Rivera",
             "HKEmergencyContactRelationshipKey": "_$!<Friend>!$_",
             "HKEmergencyContactPhoneNumberKey": "(555) 010-0101"}]})
