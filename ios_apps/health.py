# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Health reader
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Reads the Health database (``healthdb_secure.sqlite``).

What is read, and what each reading rests on:

* **The names of the kinds of data.** Every sample carries a number for its
  kind. The database itself says which number is which: its shared
  summaries are named after a kind (``Summaries_[HKQuantityTypeIdentifier
  StepCount]_...``) and list the numbers they cover. Only a number that is
  tied to exactly one name this way is named; the others are shown as
  "Type N".
* **The daily activity** (steps, active energy, exercise minutes, stand
  hours, flights, walking distance) is read from the activity summaries the
  phone keeps itself, which already count each thing once.
* **Workouts** are named with the activity types of HealthKit's public
  list; their numbers are the phone's own statistics.
* **Body and vital measurements** are shown for the kinds whose unit was
  checked against the values stored in the database. Other kinds are
  counted and named in "Data types", but their values are not interpreted.
* **Sleep** uses HealthKit's public sleep stages.

No GUI.
"""

import os
import re
from datetime import datetime

from . import keyed_archive
from .common import apple_time, format_datetime, utc_datetime
from .export_util import describe_duration, write_text_file
from .records import Column, Dataset, open_copies, sqlite_rows

HEALTH = "HealthDomain/Health/healthdb_secure.sqlite"
SOURCES = "HealthDomain/Health/healthdb.sqlite"
MEDICAL_ID = "HealthDomain/MedicalID/MedicalIDData.archive"
FILES = (HEALTH, SOURCES, MEDICAL_ID)

_IDENTIFIER = re.compile(
    r"HK(?:Quantity|Category|Correlation|Workout|ActivitySummary|Data|"
    r"Document|Audiogram|Electrocardiogram|Scored|Clinical|Series|StateOf)"
    r"\w*?Identifier\w*")

WORKOUT_TYPES = {
    1: "American football", 2: "Archery", 3: "Australian football",
    4: "Badminton", 5: "Baseball", 6: "Basketball", 7: "Bowling",
    8: "Boxing", 9: "Climbing", 10: "Cricket", 11: "Cross training",
    12: "Curling", 13: "Cycling", 14: "Dance", 15: "Dance inspired training",
    16: "Elliptical", 17: "Equestrian sports", 18: "Fencing", 19: "Fishing",
    20: "Functional strength training", 21: "Golf", 22: "Gymnastics",
    23: "Handball", 24: "Hiking", 25: "Hockey", 26: "Hunting",
    27: "Lacrosse", 28: "Martial arts", 29: "Mind and body",
    30: "Mixed metabolic cardio training", 31: "Paddle sports", 32: "Play",
    33: "Preparation and recovery", 34: "Racquetball", 35: "Rowing",
    36: "Rugby", 37: "Running", 38: "Sailing", 39: "Skating sports",
    40: "Snow sports", 41: "Soccer", 42: "Softball", 43: "Squash",
    44: "Stair climbing", 45: "Surfing sports", 46: "Swimming",
    47: "Table tennis", 48: "Tennis", 49: "Track and field",
    50: "Traditional strength training", 51: "Volleyball", 52: "Walking",
    53: "Water fitness", 54: "Water polo", 55: "Water sports",
    56: "Wrestling", 57: "Yoga", 58: "Barre", 59: "Core training",
    60: "Cross country skiing", 61: "Downhill skiing", 62: "Flexibility",
    63: "High intensity interval training", 64: "Jump rope",
    65: "Kickboxing", 66: "Pilates", 67: "Snowboarding", 68: "Stairs",
    69: "Step training", 70: "Wheelchair walk pace",
    71: "Wheelchair run pace", 72: "Tai chi", 73: "Mixed cardio",
    74: "Hand cycling", 75: "Disc sports", 76: "Fitness gaming",
    77: "Cardio dance", 78: "Social dance", 79: "Pickleball", 80: "Cooldown",
    82: "Swim bike run", 83: "Transition", 84: "Underwater diving",
    3000: "Other"}

SLEEP_STAGES = {0: "In bed", 1: "Asleep", 2: "Awake", 3: "Asleep (core)",
                4: "Asleep (deep)", 5: "Asleep (REM)"}

# kind -> (label, unit, factor from the stored value, decimals). The stored
# values were checked against the units the phone recorded them in.
MEASUREMENTS = {
    "HKQuantityTypeIdentifierBodyMass": ("Weight", "kg", 1, 1),
    "HKQuantityTypeIdentifierBodyMassIndex": ("BMI", "kg/m²", 1, 1),
    "HKQuantityTypeIdentifierBodyFatPercentage": ("Body fat", "%", 100, 1),
    "HKQuantityTypeIdentifierLeanBodyMass": ("Lean body mass", "kg", 1, 1),
    "HKQuantityTypeIdentifierHeight": ("Height", "cm", 100, 1),
    "HKQuantityTypeIdentifierRestingHeartRate": (
        "Resting heart rate", "bpm", 1, 0),
    "HKQuantityTypeIdentifierWalkingHeartRateAverage": (
        "Walking heart rate", "bpm", 1, 0),
    "HKQuantityTypeIdentifierOxygenSaturation": ("Blood oxygen", "%", 100, 0),
    "HKQuantityTypeIdentifierVO2Max": ("VO2 max", "mL/(kg·min)", 1, 1),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": (
        "Heart rate variability", "ms", 1, 0),
    "HKQuantityTypeIdentifierRespiratoryRate": (
        "Respiratory rate", "breaths/min", 60, 1),
}

MEDICAL_ID_ITEMS = (
    ("Name", "HKMedicalIDDataNameKey"),
    ("Medical conditions", "HKMedicalIDDataMedicalConditionsKey"),
    ("Medical notes", "HKMedicalIDDataMedicalNotesKey"),
    ("Allergies and reactions", "HKMedicalIDDataAllergyInfoKey"),
    ("Medications", "HKMedicalIDDataMedicationInfoKey"),
    ("Blood type", "HKMedicalIDDataBloodTypeKey"),
    ("Language", "HKMedicalIDDataPrimaryLanguageCodeKey"))


def discover(index):
    """The files this tab copies, the Health database first."""
    found = []
    for path in FILES:
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            found.append(path)
    return found


# ── Names ────────────────────────────────────────────────────

def words(identifier):
    """``HKQuantityTypeIdentifierStepCount`` -> ``Step count``;
    ``HKWorkoutTypeIdentifier`` -> ``Workout``."""
    found = re.match(
        r"HK(?:Quantity|Category|Correlation)?(\w*?)TypeIdentifier(\w*)$",
        identifier)
    base = (found.group(2) or found.group(1)) if found else ""
    pieces = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ",
                    base).split()
    if not pieces:
        return identifier
    pieces = [w if w.isupper() or any(c.isdigit() for c in w) else w.lower()
              for w in pieces]
    pieces[0] = pieces[0][:1].upper() + pieces[0][1:]
    return " ".join(pieces)


def kind_names(conn):
    """``{number: identifier}`` for the kinds the database names: those
    that exactly one name is tied to."""
    found = {}
    for name, number in sqlite_rows(
            conn, "SELECT s.name, o.object_type FROM shared_summaries s "
                  "JOIN shared_summary_object_types o "
                  "ON o.summary_id = s.ROWID"):
        for identifier in _IDENTIFIER.findall(name or ""):
            found.setdefault(number, set()).add(identifier)
    return {n: next(iter(i)) for n, i in found.items() if len(i) == 1}


def kind_label(number, names):
    identifier = names.get(number)
    if identifier is None:
        return f"Type {number}"
    return words(identifier)


def kind_class(identifier):
    for prefix, label in (("HKQuantity", "Measurement"),
                          ("HKCategory", "Event or state"),
                          ("HKWorkout", "Workout"),
                          ("HKCorrelation", "Combined"),
                          ("HKActivitySummary", "Activity summary")):
        if identifier and identifier.startswith(prefix):
            return label
    return ""


# ── Sources ──────────────────────────────────────────────────

def source_names(conn, sources_conn):
    """``{provenance id: source name}`` (the app or device that wrote the
    samples), or empty if the sources database is not there."""
    if sources_conn is None:
        return {}
    names = {pk: (name or "").strip()
             for pk, name in sqlite_rows(sources_conn,
                                         "SELECT ROWID, name FROM sources")}
    return {pk: names.get(source, "")
            for pk, source in sqlite_rows(
                conn, "SELECT ROWID, source_id FROM data_provenances")}


# ── The tables ───────────────────────────────────────────────

def overview_rows(conn, names):
    rows = []
    for number, count, first, last in sqlite_rows(
            conn, "SELECT data_type, COUNT(*), MIN(start_date), "
                  "MAX(end_date) FROM samples GROUP BY data_type"):
        identifier = names.get(number)
        rows.append({
            "type": kind_label(number, names), "number": number,
            "kind": kind_class(identifier), "count": count,
            "first": apple_time(first) if first else None,
            "last": apple_time(last) if last else None,
            "identifier": identifier or ""})
    return rows


def activity_rows(conn):
    rows = []
    for (index, steps, energy, exercise, stand, flights, distance,
         move_goal, exercise_goal, stand_goal) in sqlite_rows(
            conn, "SELECT cache_index, steps, energy_burned, brisk_minutes, "
                  "active_hours, flights, walk_distance, "
                  "energy_burned_goal, brisk_minutes_goal, "
                  "active_hours_goal FROM activity_caches "
                  "ORDER BY cache_index"):
        if index is None:
            continue
        rows.append({
            "day": utc_datetime(apple_time(index)).strftime("%Y-%m-%d"),
            "steps": int(steps) if steps else 0,
            "energy": int(round(energy)) if energy else 0,
            "exercise": int(round(exercise)) if exercise else 0,
            "stand": int(stand) if stand else 0,
            "flights": int(flights) if flights else 0,
            "distance": int(round(distance)) if distance else 0,
            "move_goal": move_goal, "exercise_goal": exercise_goal,
            "stand_goal": stand_goal})
    return rows


def _activity_details(row):
    lines = [row["day"],
             f"Steps: {row['steps']:,}",
             f"Active energy: {row['energy']:,} kcal"
             + (f" (goal {row['move_goal']:,.0f})" if row["move_goal"] else ""),
             f"Exercise: {row['exercise']} min"
             + (f" (goal {row['exercise_goal']:.0f})"
                if row["exercise_goal"] else ""),
             f"Stand: {row['stand']} h"
             + (f" (goal {row['stand_goal']:.0f})"
                if row["stand_goal"] else ""),
             f"Flights climbed: {row['flights']}",
             f"Walking and running: {row['distance'] / 1000:,.2f} km"]
    return "\n".join(lines)


def route_points(conn):
    """``{route sample id: [point, ...]}`` of the workout routes."""
    routes = {}
    for sample_id, key in sqlite_rows(
            conn, "SELECT data_id, hfd_key FROM data_series"):
        routes[key] = sample_id
    points = {}
    for (key, when, lat, lon, alt, speed, course, accuracy) in sqlite_rows(
            conn, "SELECT series_identifier, timestamp, latitude, longitude, "
                  "altitude, speed, course, horizontal_accuracy "
                  "FROM location_series_data ORDER BY series_identifier, "
                  "timestamp"):
        sample = routes.get(key)
        if sample is not None and lat is not None and lon is not None:
            points.setdefault(sample, []).append({
                "time": apple_time(when), "lat": lat, "lon": lon,
                "altitude": alt, "speed": speed, "course": course,
                "accuracy": accuracy})
    return points


def workout_rows(conn, names, sources):
    routes = route_points(conn)
    route_of = {}
    for parent, child in sqlite_rows(
            conn, "SELECT parent_id, child_id FROM associations"):
        if child in routes:
            route_of[parent] = child
    stats = {}
    for activity, kind, quantity, low, high in sqlite_rows(
            conn, "SELECT workout_activity_id, data_type, quantity, min, "
                  "max FROM workout_statistics"):
        stats[(activity, kind)] = (quantity, low, high)
    provenance = dict(sqlite_rows(
        conn, "SELECT data_id, provenance FROM objects "
              "WHERE data_id IN (SELECT data_id FROM workouts)"))
    rows = []
    for (data_id, activity_id, kind, duration, start, end,
         total_distance) in sqlite_rows(
            conn, "SELECT w.data_id, a.ROWID, a.activity_type, a.duration, "
                  "s.start_date, s.end_date, w.total_distance "
                  "FROM workouts w JOIN samples s ON s.data_id = w.data_id "
                  "LEFT JOIN workout_activities a ON a.owner_id = w.data_id "
                  "AND a.is_primary_activity = 1 ORDER BY s.start_date"):
        energy = stats.get((activity_id, 10), (None,))[0]
        meters = stats.get((activity_id, 8), (None,))[0]
        if meters is None and total_distance:
            meters = total_distance * 1000      # (kilometres in this table)
        heart = stats.get((activity_id, 5), (None, None, None))
        route = routes.get(route_of.get(data_id), [])
        rows.append({
            "id": data_id,
            "when": apple_time(start) if start else None,
            "end": apple_time(end) if end else None,
            "type": WORKOUT_TYPES.get(kind, f"Activity {kind}")
            if kind is not None else "Workout",
            "duration": duration if duration else (
                end - start if start and end else None),
            "distance": int(round(meters)) if meters else None,
            "energy": int(round(energy)) if energy else None,
            "heart_avg": int(round(heart[0] * 60)) if heart[0] else None,
            "heart_max": int(round(heart[2] * 60)) if heart[2] else None,
            "route": "yes" if route else "",
            "points": route,
            "source": sources.get(provenance.get(data_id), "")})
    return rows


def _workout_details(row):
    lines = [f"{row['type']}, {format_datetime(row['when'])}"]
    if row["duration"]:
        lines.append(f"Duration: {describe_duration(row['duration'])}")
    if row["distance"]:
        lines.append(f"Distance: {row['distance'] / 1000:,.2f} km")
    if row["energy"]:
        lines.append(f"Active energy: {row['energy']:,.0f} kcal")
    if row["heart_avg"]:
        lines.append(f"Heart rate: average {row['heart_avg']:.0f}"
                     + (f", highest {row['heart_max']:.0f}"
                        if row["heart_max"] else "") + " bpm")
    if row["points"]:
        lines.append(f"Route: {len(row['points']):,} points")
    if row["source"]:
        lines.append(f"Recorded by: {row['source']}")
    return "\n".join(lines)


def _gpx_time(stamp):
    return utc_datetime(stamp).strftime("%Y-%m-%dT%H:%M:%SZ")


def _xml(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def write_gpx(base, rows):
    """A GPX file with the route of each workout that has one (the format
    mapping programs import)."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="iOS Backup Explorer" '
             'xmlns="http://www.topografix.com/GPX/1/1">']
    for row in rows:
        if not row["points"]:
            continue
        lines.append("<trk>")
        lines.append(f"<name>{_xml(row['type'])} "
                     f"{_xml(format_datetime(row['when']))}</name>")
        lines.append("<trkseg>")
        for point in row["points"]:
            parts = [f'<trkpt lat="{point["lat"]:.7f}" '
                     f'lon="{point["lon"]:.7f}">']
            if point["altitude"] is not None:
                parts.append(f"<ele>{point['altitude']:.2f}</ele>")
            if point["time"] is not None:
                parts.append(f"<time>{_gpx_time(point['time'])}</time>")
            parts.append("</trkpt>")
            lines.append("".join(parts))
        lines.append("</trkseg>")
        lines.append("</trk>")
    lines.append("</gpx>")
    path = base + ".gpx"
    write_text_file(path, "\n".join(lines) + "\n")
    return [path]


def measurement_rows(conn, names, sources):
    wanted = {number: MEASUREMENTS[identifier]
              for number, identifier in names.items()
              if identifier in MEASUREMENTS}
    if not wanted:
        return []
    marks = ",".join("?" * len(wanted))
    provenance = {}
    rows = []
    for data_id, number, start, quantity in sqlite_rows(
            conn, "SELECT s.data_id, s.data_type, s.start_date, q.quantity "
                  "FROM samples s JOIN quantity_samples q "
                  f"ON q.data_id = s.data_id WHERE s.data_type IN ({marks}) "
                  "ORDER BY s.start_date", tuple(wanted)):
        if quantity is None:
            continue
        label, unit, factor, places = wanted[number]
        value = quantity * factor
        rows.append({"id": data_id, "when": apple_time(start),
                     "measurement": label, "value": round(value, places + 2),
                     "unit": unit, "places": places, "source": ""})
    if sources and rows:
        for data_id, prov in sqlite_rows(
                conn, "SELECT data_id, provenance FROM objects WHERE "
                      f"data_id IN (SELECT s.data_id FROM samples s WHERE "
                      f"s.data_type IN ({marks}))", tuple(wanted)):
            provenance[data_id] = prov
        for row in rows:
            row["source"] = sources.get(provenance.get(row["id"]), "")
    return rows


def _value_text(row):
    return f"{row['value']:,.{row['places']}f}"


def sleep_rows(conn, sources, names):
    numbers = [n for n, i in names.items()
               if i == "HKCategoryTypeIdentifierSleepAnalysis"]
    if not numbers:
        return []
    provenance = dict(sqlite_rows(
        conn, "SELECT data_id, provenance FROM objects WHERE data_id IN "
              "(SELECT data_id FROM samples WHERE data_type = ?)",
        (numbers[0],))) if sources else {}
    rows = []
    for data_id, start, end, value in sqlite_rows(
            conn, "SELECT s.data_id, s.start_date, s.end_date, c.value "
                  "FROM samples s JOIN category_samples c "
                  "ON c.data_id = s.data_id WHERE s.data_type = ? "
                  "ORDER BY s.start_date", (numbers[0],)):
        rows.append({
            "when": apple_time(start), "end": apple_time(end),
            "length": (end - start) if start is not None
            and end is not None else None,
            "stage": SLEEP_STAGES.get(value, f"Value {value}"),
            "source": sources.get(provenance.get(data_id), "")})
    return rows


def record_rows(conn):
    rows = []
    for name, kind, start in sqlite_rows(
            conn, "SELECT c.display_name, c.fhir_resource_resource_type, "
                  "s.start_date FROM clinical_record_samples c "
                  "JOIN samples s ON s.data_id = c.data_id "
                  "ORDER BY s.start_date"):
        rows.append({"when": apple_time(start) if start else None,
                     "type": kind or "", "name": (name or "").strip()})
    return rows


# ── Medical ID ───────────────────────────────────────────────

def _label(text):
    """Apple stores the labels it supplies as ``_$!<Friend>!$_``."""
    return re.sub(r"_\$!<(.*?)>!\$_", r"\1", text)


def _birthdate(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        year, month, day = (value.get(k) for k in
                            ("NS.year", "NS.month", "NS.day"))
        if all(isinstance(v, int) for v in (year, month, day)):
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def medical_id_rows(path):
    """Key and value rows of the Medical ID, from its archive."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        value = keyed_archive.load(data)
    except (OSError, ValueError):
        return []
    if not isinstance(value, dict):
        return []
    rows = []

    def add(label, text):
        if isinstance(text, str) and text.strip():
            rows.append({"item": label, "value": _label(text.strip())})

    for label, key in MEDICAL_ID_ITEMS[:1]:
        add(label, value.get(key))
    birth = _birthdate(value.get("HKMedicalIDDataGregorianBirthdateKey")) \
        or _birthdate(value.get("HKMedicalIDDataBirthdateKey"))
    add("Date of birth", birth)
    for label, key in (("Height", "HKMedicalIDDataHeightKey"),
                       ("Weight", "HKMedicalIDDataWeightKey")):
        quantity = value.get(key)
        if isinstance(quantity, dict) and isinstance(
                quantity.get("ValueKey"), (int, float)):
            unit = quantity.get("UnitKey")
            unit = unit.get("HKUnitStringKey") \
                if isinstance(unit, dict) else ""
            add(label, f"{quantity['ValueKey']:g} {unit or ''}".strip())
    for label, key in MEDICAL_ID_ITEMS[1:]:
        add(label, value.get(key))
    donor = value.get("HKMedicalIDDataIsOrganDonorKey")
    if isinstance(donor, bool):
        add("Organ donor", "yes" if donor else "no")
    for contact in value.get("HKMedicalIDDataEmergencyContactsKey") or ():
        if not isinstance(contact, dict):
            continue
        parts = [contact.get("HKEmergencyContactNameKey"),
                 contact.get("HKEmergencyContactRelationshipKey"),
                 contact.get("HKEmergencyContactPhoneNumberKey")]
        add("Emergency contact", ", ".join(p for p in parts
                                           if isinstance(p, str) and p))
    return rows


# ── Putting it together ──────────────────────────────────────

def medical_only(folder):
    medical = medical_id_rows(os.path.join(folder, "MedicalIDData.archive"))
    if not medical:
        return []
    return [Dataset("medical_id", "Medical ID", [
        Column("item", "Item", 200), Column("value", "Value", 520)],
        medical, note="What the phone shows on its emergency screen.",
        details=lambda r: f"{r['item']}\n{r['value']}")]


def datasets(conn, sources_conn, folder):
    names = kind_names(conn)
    sources = source_names(conn, sources_conn)
    result = medical_only(folder)
    activity = activity_rows(conn)
    if activity:
        result.append(Dataset("activity", "Daily activity", [
            Column("day", "Day", 100),
            Column("steps", "Steps", 80, "number", "e"),
            Column("energy", "Active energy (kcal)", 140, "number", "e"),
            Column("exercise", "Exercise (min)", 110, "number", "e"),
            Column("stand", "Stand (h)", 80, "number", "e"),
            Column("flights", "Flights", 70, "number", "e"),
            Column("distance", "Walking (m)", 100, "number", "e")],
            activity, sort=("day", True), details=_activity_details,
            note="The phone's own daily summaries, in which each step and "
                 "calorie is counted once."))
    workouts = workout_rows(conn, names, sources)
    if workouts:
        result.append(Dataset("workouts", "Workouts", [
            Column("when", "When", 140, "date"),
            Column("type", "Workout", 220),
            Column("duration", "Duration", 80, "duration", "e"),
            Column("distance", "Distance (m)", 100, "number", "e"),
            Column("energy", "Active energy (kcal)", 140, "number", "e"),
            Column("heart_avg", "Heart rate", 80, "number", "e"),
            Column("route", "Route", 50)],
            workouts, sort=("when", True), details=_workout_details,
            formats={"gpx": ("Routes (GPX, for mapping programs)",
                             write_gpx)}))
    measurements = measurement_rows(conn, names, sources)
    if measurements:
        result.append(Dataset("measurements", "Body and vitals", [
            Column("when", "When", 140, "date"),
            Column("measurement", "Measurement", 200),
            Column("value", "Value", 100, "text", "e", format=_value_text),
            Column("unit", "Unit", 90),
            Column("source", "Recorded by", 200)],
            measurements, sort=("when", True),
            note="Weight, body composition, resting and walking heart rate, "
                 "blood oxygen, VO2 max, heart rate variability and "
                 "breathing rate."))
    sleep = sleep_rows(conn, sources, names)
    if sleep:
        result.append(Dataset("sleep", "Sleep", [
            Column("when", "From", 140, "date"),
            Column("end", "To", 140, "date"),
            Column("length", "Length", 80, "duration", "e"),
            Column("stage", "Stage", 140),
            Column("source", "Recorded by", 200)],
            sleep, sort=("when", True)))
    records = record_rows(conn)
    if records:
        result.append(Dataset("records", "Health records", [
            Column("when", "Date", 140, "date"),
            Column("type", "Kind", 160),
            Column("name", "Record", 440)],
            records, sort=("when", True),
            note="Records from healthcare providers (labs, medications, "
                 "immunizations...). Only their names are listed here."))
    overview = overview_rows(conn, names)
    if overview:
        result.append(Dataset("types", "Data types", [
            Column("type", "Kind of data", 280),
            Column("kind", "Class", 120),
            Column("count", "Samples", 90, "number", "e"),
            Column("first", "First", 140, "date"),
            Column("last", "Last", 140, "date")],
            overview, sort=("count", True),
            note="Everything the database holds, counted. A kind shown as "
                 "'Type N' is one this backup does not name."))
    return result


class HealthReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        own = self.conn.execute("PRAGMA database_list").fetchone()[2]
        folder = os.path.dirname(own)
        if own.lower().endswith(".archive"):     # (no Health database)
            return medical_only(folder)
        paths = [SOURCES] if os.path.isfile(
            os.path.join(folder, os.path.basename(SOURCES))) else []
        with open_copies(self.conn, paths) as found:
            return datasets(self.conn, found.get(SOURCES), folder)
