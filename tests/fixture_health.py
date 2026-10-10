# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake Health database, its sources and a Medical ID, for tests. Every
value is invented; the tables follow the layout iOS uses, trimmed."""

from datetime import datetime

from tests.fixture_apps import T0, database_bytes
from tests.keyed_builder import archive

HEALTH = "Health/healthdb_secure.sqlite"
SOURCES = "Health/healthdb.sqlite"
MEDICAL_ID = "MedicalID/MedicalIDData.archive"
DAY = 86400
D0 = T0 - T0 % DAY

# the numbers this fixture's samples use for each kind
BODY_MASS, BMI, BODY_FAT, HEIGHT = 3, 0, 1, 2
HEART_RATE, STEPS, ACTIVE_ENERGY = 5, 7, 10
OXYGEN, RESPIRATORY, RESTING_HR = 14, 61, 118
SLEEP, WORKOUT, ROUTE, UNKNOWN, TWINS = 63, 79, 102, 999, 500


def summary_name(identifier, what="CurrentValue"):
    return f"Summaries_[{identifier}]_{what}_Audience_primary_Summary"


def build_health(conn):
    conn.executescript("""
        CREATE TABLE shared_summaries (ROWID INTEGER PRIMARY KEY, uuid BLOB,
            package TEXT, name TEXT);
        CREATE TABLE shared_summary_object_types (ROWID INTEGER PRIMARY KEY,
            summary_id INTEGER, object_type INTEGER);
        CREATE TABLE samples (data_id INTEGER PRIMARY KEY, start_date REAL,
            end_date REAL, data_type INTEGER);
        CREATE TABLE objects (data_id INTEGER PRIMARY KEY, uuid BLOB,
            provenance INTEGER, type INTEGER, creation_date REAL);
        CREATE TABLE quantity_samples (data_id INTEGER PRIMARY KEY,
            quantity REAL, original_quantity REAL, original_unit INTEGER);
        CREATE TABLE category_samples (data_id INTEGER PRIMARY KEY,
            value INTEGER);
        CREATE TABLE data_provenances (ROWID INTEGER PRIMARY KEY,
            source_id INTEGER);
        CREATE TABLE activity_caches (data_id INTEGER, cache_index INTEGER,
            energy_burned REAL, energy_burned_goal REAL,
            brisk_minutes REAL, brisk_minutes_goal REAL, active_hours REAL,
            active_hours_goal REAL, steps REAL, walk_distance REAL,
            flights REAL);
        CREATE TABLE workouts (data_id INTEGER PRIMARY KEY,
            total_distance REAL);
        CREATE TABLE workout_activities (ROWID INTEGER PRIMARY KEY,
            owner_id INTEGER, is_primary_activity INTEGER,
            activity_type INTEGER, start_date REAL, end_date REAL,
            duration REAL);
        CREATE TABLE workout_statistics (ROWID INTEGER PRIMARY KEY,
            workout_activity_id INTEGER, data_type INTEGER, quantity REAL,
            min REAL, max REAL);
        CREATE TABLE associations (ROWID INTEGER PRIMARY KEY,
            parent_id INTEGER, child_id INTEGER);
        CREATE TABLE data_series (data_id INTEGER PRIMARY KEY, frozen INTEGER,
            count INTEGER, insertion_era INTEGER, hfd_key INTEGER,
            series_location INTEGER);
        CREATE TABLE location_series_data (series_identifier INTEGER,
            timestamp REAL, latitude REAL, longitude REAL, altitude REAL,
            speed REAL, course REAL, horizontal_accuracy REAL);
        CREATE TABLE clinical_record_samples (data_id INTEGER PRIMARY KEY,
            display_name TEXT, fhir_resource_resource_type TEXT);
    """)
    summaries = [
        (BODY_MASS, "HKQuantityTypeIdentifierBodyMass"),
        (BMI, "HKQuantityTypeIdentifierBodyMassIndex"),
        (BODY_FAT, "HKQuantityTypeIdentifierBodyFatPercentage"),
        (HEIGHT, "HKQuantityTypeIdentifierHeight"),
        (HEART_RATE, "HKQuantityTypeIdentifierHeartRate"),
        (STEPS, "HKQuantityTypeIdentifierStepCount"),
        (ACTIVE_ENERGY, "HKQuantityTypeIdentifierActiveEnergyBurned"),
        (OXYGEN, "HKQuantityTypeIdentifierOxygenSaturation"),
        (RESPIRATORY, "HKQuantityTypeIdentifierRespiratoryRate"),
        (RESTING_HR, "HKQuantityTypeIdentifierRestingHeartRate"),
        (SLEEP, "HKCategoryTypeIdentifierSleepAnalysis"),
        (WORKOUT, "HKWorkoutTypeIdentifier")]
    row = 0
    for number, identifier in summaries:
        for what in ("CurrentValue", "ChartModel"):       # more than one each
            row += 1
            conn.execute("INSERT INTO shared_summaries (ROWID, name) "
                         "VALUES (?, ?)", (row, summary_name(identifier,
                                                             what)))
            conn.execute("INSERT INTO shared_summary_object_types "
                         "(summary_id, object_type) VALUES (?, ?)",
                         (row, number))
    # one number tied to two different names is not named
    for identifier in ("HKQuantityTypeIdentifierDietaryProtein",
                       "HKQuantityTypeIdentifierDietaryFiber"):
        row += 1
        conn.execute("INSERT INTO shared_summaries (ROWID, name) VALUES "
                     "(?, ?)", (row, summary_name(identifier)))
        conn.execute("INSERT INTO shared_summary_object_types "
                     "(summary_id, object_type) VALUES (?, ?)", (row, TWINS))
    # a summary with no kind in its name
    row += 1
    conn.execute("INSERT INTO shared_summaries (ROWID, name) VALUES (?, ?)",
                 (row, "SomethingElse"))
    conn.execute("INSERT INTO shared_summary_object_types (summary_id, "
                 "object_type) VALUES (?, ?)", (row, UNKNOWN))

    conn.executemany("INSERT INTO data_provenances VALUES (?, ?)",
                     [(1, 10), (2, 20), (3, 99)])      # (99: no such source)
    next_id = [1000]

    def sample(kind, start, end=None, provenance=1, data_id=None):
        data_id = data_id or next_id[0]
        next_id[0] = max(next_id[0], data_id) + 1
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                     (data_id, start, end if end is not None else start,
                      kind))
        conn.execute("INSERT INTO objects VALUES (?, NULL, ?, 1, ?)",
                     (data_id, provenance, start))
        return data_id

    def quantity(kind, start, value, provenance=1):
        data_id = sample(kind, start, provenance=provenance)
        conn.execute("INSERT INTO quantity_samples VALUES (?, ?, NULL, NULL)",
                     (data_id, value))

    # body and vitals (stored in the units the phone stores them in)
    quantity(BODY_MASS, T0, 100.0)                  # kg
    quantity(BODY_MASS, T0 + DAY, 99.5, provenance=2)
    quantity(BMI, T0, 30.5)
    quantity(BODY_FAT, T0, 0.25)                    # a fraction
    quantity(HEIGHT, T0, 1.905)                     # metres
    quantity(OXYGEN, T0, 0.97)
    quantity(RESPIRATORY, T0, 0.25)                 # breaths per second
    quantity(RESTING_HR, T0, 60.0)                  # already per minute
    quantity(RESTING_HR, T0 + 5, None)              # nothing stored: skipped
    quantity(HEART_RATE, T0, 1.5)                   # (many; not listed)
    quantity(STEPS, T0, 100)
    quantity(UNKNOWN, T0, 1)
    quantity(UNKNOWN, T0 + 1, 2, provenance=3)

    # sleep
    for offset, stage in ((0, 0), (600, 3), (1200, 4), (1800, 5), (2400, 2),
                          (2700, 1), (3000, 9)):
        data_id = sample(SLEEP, T0 + offset, T0 + offset + 600
                         if stage != 2 else T0 + offset + 120)
        conn.execute("INSERT INTO category_samples VALUES (?, ?)",
                     (data_id, stage))

    # daily activity
    conn.executemany(
        "INSERT INTO activity_caches (cache_index, energy_burned, "
        "energy_burned_goal, brisk_minutes, brisk_minutes_goal, "
        "active_hours, active_hours_goal, steps, walk_distance, flights) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (D0, 450.4, 500.0, 29.6, 30.0, 11.0, 12.0, 8000.0, 6123.4, 9.0),
            (D0 + DAY, 0.0, 500.0, 0.0, 30.0, 0.0, 12.0, 0.0, 0.0, 0.0),
            (D0 - DAY, 100.0, None, 5.0, None, 2.0, None, 1500.0, None,
             None)])

    # two workouts, one with a route
    run = sample(WORKOUT, T0 + 100, T0 + 1900, data_id=100)
    walk = sample(WORKOUT, T0 + DAY, T0 + DAY + 600, data_id=101,
                  provenance=2)
    conn.execute("INSERT INTO workouts VALUES (?, ?)", (run, None))
    conn.execute("INSERT INTO workouts VALUES (?, ?)", (walk, 1.2))
    conn.execute("INSERT INTO workout_activities VALUES (1, ?, 1, 37, ?, ?, "
                 "1800.0)", (run, T0 + 100, T0 + 1900))
    conn.execute("INSERT INTO workout_activities VALUES (2, ?, 1, 52, ?, ?, "
                 "NULL)", (walk, T0 + DAY, T0 + DAY + 600))
    conn.executemany("INSERT INTO workout_statistics (workout_activity_id, "
                     "data_type, quantity, min, max) VALUES (?,?,?,?,?)", [
        (1, ACTIVE_ENERGY, 400.4, None, None),
        (1, 8, 5000.0, None, None),
        (1, HEART_RATE, 2.5, 2.0, 3.0)])      # count per second
    route = sample(ROUTE, T0 + 100, T0 + 1900, data_id=200)
    conn.execute("INSERT INTO associations (parent_id, child_id) "
                 "VALUES (?, ?)", (run, route))
    conn.execute("INSERT INTO data_series VALUES (?, 1, 3, 1, 1, 2)",
                 (route,))
    conn.executemany("INSERT INTO location_series_data VALUES "
                     "(1, ?, ?, ?, ?, ?, ?, ?)", [
        (T0 + 100, 12.5, -45.25, 10.0, 2.5, 90.0, 5.0),
        (T0 + 101, 12.50001, -45.25001, 10.5, 2.6, 91.0, 5.0),
        (T0 + 102, 12.50002, -45.25002, None, None, None, None),
        (T0 + 103, None, None, None, None, None, None)])   # (no position)
    conn.execute("INSERT INTO location_series_data VALUES (2, ?, 1, 1, 1, "
                 "1, 1, 1)", (T0,))                 # (no such route)

    # health records
    for name, kind in (("Blood test <A>", "Observation"), ("", None),
                       ("Flu shot", "Immunization")):
        data_id = sample(UNKNOWN + 1, T0 + 50)
        conn.execute("INSERT INTO clinical_record_samples VALUES (?, ?, ?)",
                     (data_id, name, kind))
    conn.commit()


def build_sources(conn):
    conn.execute("CREATE TABLE sources (ROWID INTEGER PRIMARY KEY, uuid BLOB,"
                 " name TEXT)")
    conn.executemany("INSERT INTO sources (ROWID, name) VALUES (?, ?)",
                     [(10, "Sam's iPhone"), (20, " Smart Scale ")])
    conn.commit()


def medical_id():
    return archive({
        "$class": "HKMedicalIDData",
        "HKMedicalIDDataNameKey": "Sam Example",
        "HKMedicalIDDataGregorianBirthdateKey": {
            "$class": "NSDateComponents", "NS.year": 1980, "NS.month": 2,
            "NS.day": 9},
        "HKMedicalIDDataHeightKey": {
            "$class": "HKQuantity", "ValueKey": 190.5,
            "UnitKey": {"$class": "HKUnit", "HKUnitStringKey": "cm"}},
        "HKMedicalIDDataMedicalConditionsKey": "Condition A; condition B",
        "HKMedicalIDDataMedicalNotesKey": "  ",
        "HKMedicalIDDataIsOrganDonorKey": True,
        "HKMedicalIDDataPictureDataKey": b"\x89PNG not shown",
        "HKMedicalIDDataNameModifiedDateKey": datetime(2025, 1, 1),
        "HKMedicalIDDataEmergencyContactsKey": [
            {"$class": "HKEmergencyContact",
             "HKEmergencyContactNameKey": "Alex Example",
             "HKEmergencyContactRelationshipKey": "_$!<Friend>!$_",
             "HKEmergencyContactPhoneNumberKey": "555 010 7777"},
            {"$class": "HKEmergencyContact",
             "HKEmergencyContactNameKey": "Pat Sample",
             "HKEmergencyContactRelationshipKey": None,
             "HKEmergencyContactPhoneNumberKey": None},
            "junk"]})


def backup_files(sources=True, medical=True, health=True):
    files = []
    if health:
        files.append(("HealthDomain", HEALTH, database_bytes(build_health)))
    if sources:
        files.append(("HealthDomain", SOURCES, database_bytes(build_sources)))
    if medical:
        files.append(("HealthDomain", MEDICAL_ID, medical_id()))
    return files
