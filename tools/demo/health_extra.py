# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""More of the demo phone's Health database, for what version 2.2.0 added to
the Health tab: sleep per night, medications and their log, the contents of
health records (lab results, vaccines...) with two clinical documents whose
files are kept encrypted, hearing tests, events and symptoms, awards, sleep
schedules and friends' activity. Everything is invented.

The tables have the layout of the real database (the tests of each reader
build the same ones); ``extend`` adds them to the demo's database and
``document_files`` gives the encrypted files the documents point to.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from . import NOW, ago, cocoa

TIME_ZONE = "America/Chicago"        # (the invented town is in Illinois)

# the kind numbers of the events and symptoms (the same as Apple's)
STAND, MINDFUL, HEADACHE, FATIGUE, HANDWASHING = 70, 99, 160, 167, 237
AUDIOGRAM = 145
DOSE_EVENT = 273

# the two clinical documents: (record name, file id, type, title, content)
DOCUMENTS = [
    ("Visit summary", "5E1D7C20-0A4B-4F7E-9C11-2B6A3D8E4F01", "public.html",
     "Summary of the visit",
     b"<html><body><h2>Visit summary</h2><p>Seasonal allergies, stable. "
     b"Continue cetirizine 10 mg once a day. Return in a year, or sooner "
     b"if symptoms change.</p><p>This note is invented for the demo."
     b"</p></body></html>"),
    ("Allergy letter", "8B3F9A64-72C1-4D0E-A5B8-6C4E1F2D9A02",
     "public.rtf", "Letter about allergies",
     b"{\\rtf1\\ansi Dear Taylor, your allergy results are back: a "
     b"reaction to pollen and to penicillin. This letter is invented for "
     b"the demo.\\par}"),
]
FILES = "Health/Files"            # inside HealthDomain


def _record(kind, **fields):
    return json.dumps({"resourceType": kind, **fields})


def _fhir():
    """``{record name: (FHIR kind, its JSON)}`` for the demo's records."""
    def lab(name, when, **fields):
        return ("Observation", _record(
            "Observation", status="final",
            category=[{"coding": [{"code": "laboratory",
                                   "display": "Laboratory"}]}],
            code={"text": name}, effectiveDateTime=when,
            performer=[{"display": "Example Lab"}], **fields))

    def quantity(value, unit):
        return {"value": value, "unit": unit}

    def part(name, value, unit):
        return {"code": {"text": name}, "valueQuantity": quantity(value, unit)}

    return {
        "Hemoglobin A1c": lab(
            "Hemoglobin A1c", "2026-08-12T08:15:00Z",
            valueQuantity=quantity(5.3, "%"),
            referenceRange=[{"low": quantity(4, "%"),
                             "high": quantity(5.6, "%")}],
            interpretation=[{"coding": [{"code": "N",
                                         "display": "Normal"}]}]),
        "Complete blood count": lab(
            "Complete blood count", "2026-08-12T08:15:00Z", component=[
                part("Hemoglobin", 13.9, "g/dL"),
                part("White blood cells", 6.1, "10*3/uL"),
                part("Platelets", 251, "10*3/uL")]),
        "Lipid panel": lab(
            "Lipid panel", "2026-05-20T07:50:00Z", component=[
                part("LDL cholesterol", 92, "mg/dL"),
                part("HDL cholesterol", 58, "mg/dL"),
                part("Triglycerides", 104, "mg/dL")]),
        "Vitamin D, 25-hydroxy": lab(
            "Vitamin D, 25-hydroxy", "2026-02-03T09:05:00Z",
            valueQuantity=quantity(34, "ng/mL"),
            referenceRange=[{"low": quantity(30, "ng/mL"),
                             "high": quantity(100, "ng/mL")}]),
        "Influenza vaccine": ("Immunization", _record(
            "Immunization", status="completed",
            vaccineCode={"text": "Influenza vaccine"},
            occurrenceDateTime="2026-09-28", lotNumber="EXAMPLE-0042",
            manufacturer={"display": "Example Pharma"},
            site={"text": "Left arm"})),
        "Tetanus, diphtheria and pertussis vaccine": ("Immunization", _record(
            "Immunization", status="completed",
            vaccineCode={"text": "Tetanus, diphtheria and pertussis "
                                 "vaccine"},
            occurrenceDateTime="2025-04-14", manufacturer={
                "display": "Example Pharma"}, site={"text": "Right arm"})),
        "Cetirizine 10 mg tablet": ("MedicationRequest", _record(
            "MedicationRequest", status="active", intent="order",
            medicationCodeableConcept={"text": "Cetirizine 10 mg tablet"},
            authoredOn="2026-03-01T12:00:00Z",
            dosageInstruction=[{"text": "Take one tablet once a day"}],
            requester={"display": "Dr. Example"})),
        "Allergic rhinitis": ("Condition", _record(
            "Condition", code={"text": "Allergic rhinitis"},
            clinicalStatus={"coding": [{"code": "active",
                                        "display": "Active"}]},
            onsetDateTime="2019-04-02",
            category=[{"text": "Problem list item"}],
            recorder={"display": "Dr. Example"})),
    }


def _documents():
    """The FHIR resources of the clinical documents."""
    resources = {}
    dates = ["2026-09-02T10:30:00Z", "2026-07-20T14:10:00Z"]
    for (name, _ident, _uti, title, _content), when in zip(DOCUMENTS, dates):
        resources[name] = ("DocumentReference", _record(
            "DocumentReference", status="current",
            date=when, type={"text": name},
            author=[{"display": "Dr. Example"}],
            content=[{"attachment": {"contentType": "text/html",
                                     "title": title}}]))
    return resources


def key_blob():
    from tests import aea_builder as ab
    from tests.keyed_builder import archive
    return archive({"$class": "HKSymmetricKey", "sym_key": ab.KEY})


def document_files():
    """``[(path inside HealthDomain, encrypted bytes)]`` for the documents."""
    from tests import aea_builder as ab
    return [(f"{FILES}/{ident}", ab.build(content))
            for _name, ident, _uti, _title, content in DOCUMENTS]


def extend(conn, sample, rng):
    """Add everything to the demo's Health database *conn*. *sample* is the
    builder's function that adds a row of ``samples`` and ``objects`` and
    returns its id."""
    sleep_zones(conn)
    records(conn, sample)
    medications(conn)
    events(conn, sample, rng)
    hearing(conn, sample)
    awards(conn)
    schedules(conn)
    friends(conn)


def sleep_zones(conn):
    """The time zone each source recorded in, so that the nights can be
    placed on the day the person woke up."""
    conn.execute("ALTER TABLE data_provenances ADD COLUMN tz_name TEXT")
    conn.execute("UPDATE data_provenances SET tz_name = ?", (TIME_ZONE,))


def records(conn, sample):
    """The contents of the health records, as the phone keeps them (FHIR
    resources), and the files of two clinical documents."""
    conn.executescript("""
        CREATE TABLE original_fhir_resources (ROWID INTEGER PRIMARY KEY,
            type TEXT, raw_content BLOB);
        ALTER TABLE clinical_record_samples ADD COLUMN
            original_fhir_resource_rowid INTEGER;
        CREATE TABLE attachments (identifier BLOB, type TEXT,
            encryption_key BLOB);
        CREATE TABLE medical_downloadable_attachments (
            data_id INTEGER PRIMARY KEY, clinical_record_uuid BLOB,
            attachment_uuid BLOB, title TEXT);""")

    def resource(kind, raw):
        return conn.execute(
            "INSERT INTO original_fhir_resources (type, raw_content) VALUES "
            "(?, ?)", (kind, raw.encode("utf-8"))).lastrowid

    for name, (kind, raw) in _fhir().items():
        conn.execute(
            "UPDATE clinical_record_samples SET "
            "original_fhir_resource_rowid = ? WHERE display_name = ?",
            (resource(kind, raw), name))
    for number, (name, ident, uti, title, _content) in enumerate(DOCUMENTS, 1):
        kind, raw = _documents()[name]
        data_id = sample(119_000, ago(days=30 + number), provenance=1)
        record = bytes([60 + number]) * 16
        conn.execute("UPDATE objects SET uuid = ? WHERE data_id = ?",
                     (record, data_id))
        conn.execute("INSERT INTO clinical_record_samples (data_id, "
                     "display_name, fhir_resource_resource_type, "
                     "original_fhir_resource_rowid) VALUES (?, ?, ?, ?)",
                     (data_id, name, "DocumentReference",
                      resource(kind, raw)))
        attachment = uuid.UUID(ident).bytes
        conn.execute("INSERT INTO attachments VALUES (?, ?, ?)",
                     (attachment, uti, key_blob()))
        conn.execute("INSERT INTO medical_downloadable_attachments VALUES "
                     "(?, ?, ?, ?)", (number, record, attachment, title))


def medications(conn):
    """Two medications, their schedules and two weeks of doses."""
    conn.executescript("""
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
        CREATE TABLE medication_dose_event_samples (data_id INTEGER PRIMARY
            KEY, log_origin INTEGER, medication_uuid BLOB,
            scheduled_dose_quantity REAL, dose_quantity REAL,
            scheduled_date REAL, status INTEGER);""")
    cetirizine, vitamin = b"M" * 15 + b"1", b"M" * 15 + b"2"
    for number, (ident, name, ingredients, form, full) in enumerate((
            (cetirizine, "Cetirizine", "Cetirizine hydrochloride", "Tablet",
             "Cetirizine 10 mg Tablet"),
            (vitamin, "Vitamin D3", "Cholecalciferol", "Capsule",
             "Vitamin D3 1000 IU Capsule")), 1):
        conn.execute("INSERT INTO user_domain_concepts VALUES (?, ?, 0, ?)",
                     (number, ident, cocoa(ago(days=200))))
        conn.execute("INSERT INTO medication_user_domain_concepts VALUES (?)",
                     (number,))
        conn.executemany(
            "INSERT INTO user_domain_concept_localized_strings (udc_id, "
            "property_type, string_value) VALUES (?, ?, ?)", [
                (number, 160007, name), (number, 160009, ingredients),
                (number, 160010, form), (number, 160012, full)])
        conn.execute("INSERT INTO medication_schedules (medication_uuid, "
                     "deleted) VALUES (?, 0)", (ident,))
    data_id = 70_000
    for day in range(14, 0, -1):
        for ident, every, hour in ((cetirizine, 1, 8), (vitamin, 2, 9)):
            if day % every:
                continue
            due = ago(days=day, hours=0).replace(hour=hour, minute=0,
                                                 second=0, microsecond=0)
            taken = day % 6 != 0         # (a dose now and then went unlogged)
            data_id += 1
            logged = cocoa(due) + (240 if taken else 0)
            conn.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                         (data_id, logged, logged, DOSE_EVENT))
            conn.execute(
                "INSERT INTO medication_dose_event_samples VALUES "
                "(?, 2, ?, 1.0, ?, ?, ?)",
                (data_id, ident, 1.0 if taken else None, cocoa(due),
                 4 if taken else 1))


def events(conn, sample, rng):
    """Events the phone and watch logged, and symptoms that were entered."""
    # (two weeks of them, at hours of the day that a person is about; the
    # town is five hours behind UTC)
    for days in range(0, 14):
        for hour in (17, 21) if days % 2 == 0 else (17,):
            start = _at(days, hour)
            _category(conn, sample(STAND, start, start + timedelta(
                hours=1), provenance=2), 0)
    for days in range(0, 12):
        start = _at(days, 13, 20 + days)
        _category(conn, sample(HANDWASHING, start, start + timedelta(
            seconds=rng.randrange(20, 31)), provenance=2), 0)
    for days in (1, 4, 8, 12):
        start = _at(days, 11, 30)
        _category(conn, sample(MINDFUL, start, start + timedelta(
            minutes=rng.randrange(5, 15)), provenance=2), 0)
    for kind, days, severity in ((HEADACHE, 2, 2), (HEADACHE, 8, 3),
                                 (FATIGUE, 4, 2), (FATIGUE, 10, 3)):
        start = _at(days, 22)
        _category(conn, sample(kind, start, start + timedelta(hours=3),
                               provenance=1), severity)


def _at(days, hour, minute=0):
    """*hour*:*minute* UTC, *days* before the day of the backup."""
    day = NOW - timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, minute,
                    tzinfo=timezone.utc)


def _category(conn, data_id, value):
    conn.execute("INSERT INTO category_samples VALUES (?, ?)",
                 (data_id, value))


def hearing(conn, sample):
    """One hearing test (an audiogram)."""
    from tests.keyed_builder import archive

    def quantity(value, unit_class, unit):
        return {"$class": "HKQuantity", "ValueKey": value,
                "UnitKey": {"$class": unit_class, "HKUnitStringKey": unit}}

    points = [(250, 5, 10), (500, 5, 5), (1000, 10, 5), (2000, 10, 10),
              (4000, 15, 15), (8000, 25, 20)]
    payload = archive([
        {"$class": "HKAudiogramSensitivityPoint",
         "FrequencyKey": quantity(f, "HKFrequencyUnit", "Hz"),
         "LeftEarSensitivityKey": quantity(l, "HKDecibelHearingLevelUnit",
                                           "dBHL"),
         "RightEarSensitivityKey": quantity(r, "HKDecibelHearingLevelUnit",
                                            "dBHL")}
        for f, l, r in points])
    conn.execute("CREATE TABLE binary_samples (data_id INTEGER PRIMARY KEY, "
                 "payload BLOB)")
    data_id = sample(AUDIOGRAM, ago(days=75), provenance=1)
    conn.execute("INSERT INTO binary_samples VALUES (?, ?)",
                 (data_id, payload))


def _mjd(day):
    """The Modified Julian Date of *day* (how a one-day change names it)."""
    return (day - date(1858, 11, 17)).days


def awards(conn):
    conn.execute("""CREATE TABLE ACHAchievementsPlugin_earned_instances (
        ROWID INTEGER PRIMARY KEY, template_unique_name TEXT,
        created_date REAL, earned_date TEXT, value_in_canonical_unit REAL,
        value_canonical_unit TEXT)""")
    conn.executemany(
        "INSERT INTO ACHAchievementsPlugin_earned_instances (template_unique_"
        "name, created_date, earned_date, value_in_canonical_unit, "
        "value_canonical_unit) VALUES (?,?,?,?,?)", [
            ("NewMoveRecord", cocoa(ago(days=12)), "2026-09-27", 712.5,
             "kcal"),
            ("FirstWorkout-HKWorkoutActivityTypeHiking",
             cocoa(ago(days=60)), "2026-08-10", None, None),
            ("BestWorkoutDistance-HKWorkoutActivityTypeCycling",
             cocoa(ago(days=70)), "2026-07-31", 31400.0, "m"),
            ("MonthlyChallengeTypeTotalWorkouts_2026_08",
             cocoa(ago(days=40)), "2026-08-31", 22.0, "count"),
            ("100MoveGoals", cocoa(ago(days=90)), "2026-07-02", 100.0,
             "count"),
            ("PerfectMonth", cocoa(ago(days=100)), "2026-06-30", None,
             None)])


def schedules(conn):
    conn.execute("""CREATE TABLE sleep_schedule_samples (data_id INTEGER
        PRIMARY KEY, monday INTEGER, tuesday INTEGER, wednesday INTEGER,
        thursday INTEGER, friday INTEGER, saturday INTEGER, sunday INTEGER,
        wake_hour INTEGER, wake_minute INTEGER, bed_hour INTEGER,
        bed_minute INTEGER, override_day_index INTEGER)""")
    one_day = _mjd(date(2026, 10, 3))
    for data_id, days, (bed, wake), override, set_on in (
            (90_001, [1] * 7, ((22, 30), (6, 30)), None, 150),
            (90_002, [1, 1, 1, 1, 1, 0, 0], ((23, 0), (6, 15)), None, 90),
            (90_003, [0] * 7, ((0, 30), (8, 30)), one_day, 8)):
        when = cocoa(ago(days=set_on))
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, 0)",
                     (data_id, when, when))
        conn.execute(
            "INSERT INTO sleep_schedule_samples VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data_id, *days, wake[0], wake[1], bed[0], bed[1], override))


def friends(conn):
    """What two people in Activity sharing sent (the backup holds no names)."""
    conn.executescript("""
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
            friend_uuid BLOB);""")
    first, second = b"F" * 15 + b"1", b"F" * 15 + b"2"
    for data_id, days in ((90_010, 3), (90_011, 6), (90_012, 1), (90_013, 2),
                          (90_014, 4)):
        when = cocoa(ago(days=days))
        conn.execute("INSERT INTO samples VALUES (?, ?, ?, 0)",
                     (data_id, when, when))
    conn.execute("INSERT INTO fitness_friend_workouts VALUES "
                 "(90010, ?, 2400, 410.0, 6200, 37, 0)", (first,))
    conn.execute("INSERT INTO fitness_friend_workouts VALUES "
                 "(90011, ?, 1800, 220.0, NULL, 52, 1)", (second,))
    for data_id, friend, move, brisk, steps, days in (
            (90012, first, 520.0, 38.0, 9400.0, 1),
            (90013, second, 310.0, 22.0, 6100.0, 2)):
        conn.execute(
            "INSERT INTO fitness_friend_activity_snapshots VALUES "
            "(?, ?, ?, 600.0, ?, 30.0, 11.0, 12.0, ?, ?)",
            (data_id, friend, move, brisk, steps, cocoa(ago(days=days))))
    conn.execute("INSERT INTO fitness_friend_achievements VALUES (90014, ?)",
                 (first,))

