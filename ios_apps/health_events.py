# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Events, cycle tracking and symptoms from the Health database.

Most of what Health calls an *event* or a *symptom* is a **category sample**:
a start, an end and a small number. HealthKit's public documentation says what
each number means for each kind (a symptom's severity, a menstrual flow, an
ovulation test result), so these are shown in words. Only a kind that the
database itself names (see ``health.kind_names``) is read, and a value outside
the public list is shown as "Value N", not guessed.

Not here: sleep (its own tables), and the quantity kinds (heart rate...).
No GUI.
"""

from .common import apple_time
from .records import Column, Dataset, sqlite_rows

SEVERITY = {0: "Present", 1: "Not present", 2: "Mild", 3: "Moderate",
            4: "Severe"}
PRESENT = {0: ""}
TEST_RESULT = {1: "Negative", 2: "Positive", 3: "Indeterminate"}

# kind (without the HKCategoryTypeIdentifier prefix) -> values
VALUES = {
    "MenstrualFlow": {1: "Unspecified", 2: "Light", 3: "Medium", 4: "Heavy",
                      5: "None"},
    "OvulationTestResult": {1: "Negative", 2: "Luteinizing hormone surge",
                            3: "Indeterminate", 4: "Estrogen surge"},
    "CervicalMucusQuality": {1: "Dry", 2: "Sticky", 3: "Creamy",
                             4: "Watery", 5: "Egg white"},
    "Contraceptive": {1: "Unspecified", 2: "Implant", 3: "Injection",
                      4: "Intrauterine device", 5: "Intravaginal ring",
                      6: "Oral", 7: "Patch"},
    "PregnancyTestResult": TEST_RESULT,
    "ProgesteroneTestResult": TEST_RESULT,
    "AppleStandHour": {0: "Stood", 1: "Idle"},
    "AudioExposureEvent": {1: "Loud environment"},
    "HeadphoneAudioExposureEvent": {1: "Loud headphones"},
    "AppleWalkingSteadinessEvent": {1: "Low", 2: "Very low", 3: "Low again",
                                    4: "Very low again"},
    "LowCardioFitnessEvent": {1: "Low cardio fitness"},
}
# kinds whose value is only "this happened"
EVENTS = ("HandwashingEvent", "ToothbrushingEvent", "MindfulSession",
          "HighHeartRateEvent", "LowHeartRateEvent",
          "IrregularHeartRhythmEvent", "IntermenstrualBleeding",
          "SexualActivity", "Pregnancy", "Lactation",
          "InfrequentMenstrualCycles", "IrregularMenstrualCycles",
          "PersistentIntermenstrualBleeding", "ProlongedMenstrualPeriods")
# symptoms: the value is a severity
SYMPTOMS = (
    "AbdominalCramps", "Acne", "AppetiteChanges", "BladderIncontinence",
    "Bloating", "BreastPain", "ChestTightnessOrPain", "Chills",
    "Constipation", "Coughing", "Diarrhea", "Dizziness", "DrySkin", "Fainting",
    "Fatigue", "Fever", "GeneralizedBodyAche", "HairLoss", "Headache",
    "Heartburn", "HotFlashes", "LossOfSmell", "LossOfTaste", "LowerBackPain",
    "MemoryLapse", "MoodChanges", "Nausea", "NightSweats", "PelvicPain",
    "RapidPoundingOrFlutteringHeartbeat", "RunnyNose", "ShortnessOfBreath",
    "SinusCongestion", "SkippedHeartbeat", "SleepChanges", "SoreThroat",
    "VaginalDryness", "Vomiting", "Wheezing")

PREFIX = "HKCategoryTypeIdentifier"


def kind_text(identifier):
    """``Abdominal cramps`` for ``HKCategoryTypeIdentifierAbdominalCramps``."""
    from .health import words
    return words(identifier)


def kind_group(name):
    if name in SYMPTOMS:
        return "Symptom"
    if name in ("MenstrualFlow", "OvulationTestResult", "CervicalMucusQuality",
                "Contraceptive", "PregnancyTestResult",
                "ProgesteroneTestResult", "IntermenstrualBleeding",
                "SexualActivity", "Pregnancy", "Lactation",
                "InfrequentMenstrualCycles", "IrregularMenstrualCycles",
                "PersistentIntermenstrualBleeding",
                "ProlongedMenstrualPeriods"):
        return "Cycle tracking"
    return "Event"


def value_text(name, value):
    if name in SYMPTOMS:
        return SEVERITY.get(value, f"Value {value}")
    if name in EVENTS:
        return "" if value == 0 else f"Value {value}"
    return VALUES.get(name, {}).get(value, f"Value {value}")


def event_rows(conn, names, sources):
    """One row for each sample of the named event, cycle and symptom kinds."""
    wanted = {}
    for number, identifier in names.items():
        if not identifier.startswith(PREFIX):
            continue
        name = identifier[len(PREFIX):]
        if name == "SleepAnalysis":
            continue
        wanted[number] = name
    if not wanted:
        return []
    marks = ",".join("?" * len(wanted))
    provenance = dict(sqlite_rows(
        conn, "SELECT o.data_id, o.provenance FROM objects o JOIN samples s "
              f"ON s.data_id = o.data_id WHERE s.data_type IN ({marks})",
        tuple(wanted)))
    rows = []
    for data_id, start, end, kind, value in sqlite_rows(
            conn, "SELECT s.data_id, s.start_date, s.end_date, s.data_type, "
                  "c.value FROM samples s JOIN category_samples c ON "
                  f"c.data_id = s.data_id WHERE s.data_type IN ({marks}) "
                  "ORDER BY s.start_date", tuple(wanted)):
        name = wanted[kind]
        rows.append({
            "when": apple_time(start), "end": apple_time(end),
            "length": (end - start) if start is not None
            and end is not None and end > start else None,
            "kind": kind_text(PREFIX + name), "group": kind_group(name),
            "value": value_text(name, value),
            "source": sources.get(provenance.get(data_id), "")})
    return rows


def datasets(conn, names, sources):
    rows = event_rows(conn, names, sources)
    if not rows:
        return []
    return [Dataset(
        "events", "Events and symptoms", [
            Column("when", "When", 140, "date"),
            Column("group", "Group", 110),
            Column("kind", "What", 230),
            Column("value", "Value", 150),
            Column("length", "Length", 80, "duration", "e"),
            Column("source", "Recorded by", 200)],
        rows, sort=("when", True),
        note="Events the phone and watch logged (stand hours, hand washing, "
             "mindful sessions, loud audio...) and the symptoms and cycle "
             "tracking you entered. Values are shown with the words "
             "HealthKit documents for them.")]
