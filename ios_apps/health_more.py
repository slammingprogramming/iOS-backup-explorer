# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""More of what the Health database holds: awards, sleep schedules, and the
data of friends in Activity sharing.

* **Awards** (``ACHAchievementsPlugin_earned_instances``): the phone keeps the
  *internal name* of each award earned (``NewMoveRecord``,
  ``MonthlyChallengeTypeTotalWorkouts_2024_02``), the day, and the value in a
  unit. The names the Fitness app shows are not in the database, so these are
  made readable from the internal names (CamelCase split into words), and a
  workout type named inside one is looked up in the public HealthKit list.
* **Sleep schedules** (``sleep_schedule_samples``): the weekdays, bedtime and
  wake-up time of each schedule, and one-day changes. A one-day change's day
  is stored as a Modified Julian Date (days since 1858-11-17).
* **Audiograms** (``binary_samples`` of the kind named
  ``HKDataTypeIdentifierAudiogram``): each is an archived list of points, every
  point holding a frequency and the hearing level of the left and right ear
  *with their units written in the archive* (Hz, dB HL), so nothing here is a
  guess.
* **Friends in Activity sharing** (``fitness_friend_*``): what friends'
  activity summaries, workouts and awards the phone received. The friends'
  names are not in the database, only an identifier, so each friend is shown as
  "Friend 1", "Friend 2"... in the order they first appear (activity
  summaries, then workouts, then awards).

No GUI.
"""

import re
from datetime import datetime, timedelta, timezone

import plistlib

from . import keyed_archive
from .common import apple_time, format_datetime, table_columns
from .records import Column, Dataset, format_day, sqlite_rows

MJD_ORIGIN = datetime(1858, 11, 17, tzinfo=timezone.utc)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")
_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_UNITS = {"kcal": "kcal", "m": "m", "min": "min", "count": ""}


def humanize(name):
    """``New move record`` for ``NewMoveRecord`` (and the like). A part such
    as ``HKWorkoutActivityTypeCycling`` is resolved by the caller."""
    parts = []
    for piece in re.split(r"[_\-]+", name or ""):
        parts.extend(_WORDS.findall(piece))
    text = " ".join(parts).strip()
    return text[:1].upper() + text[1:].lower() if text else ""


def award_name(unique_name, workout_names):
    """A readable name for an award's internal name."""
    name = unique_name or ""
    match = re.search(r"HKWorkoutActivityType(\w+)", name)
    if match:
        kind = workout_names.get(match.group(1).lower(), humanize(
            match.group(1)))
        before = humanize(name[:match.start()].rstrip("-_"))
        return f"{before} ({kind})" if before else kind
    return humanize(name)


def _unit(value, unit):
    if value is None:
        return ""
    unit = _UNITS.get(unit, unit or "")
    number = f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}".rstrip(
        "0").rstrip(".")
    return f"{number} {unit}".strip()


def award_rows(conn, workout_names):
    if "template_unique_name" not in table_columns(
            conn, "ACHAchievementsPlugin_earned_instances"):
        return []
    rows = []
    for name, created, earned, value, unit in sqlite_rows(
            conn, "SELECT template_unique_name, created_date, earned_date, "
                  "value_in_canonical_unit, value_canonical_unit FROM "
                  "ACHAchievementsPlugin_earned_instances ORDER BY ROWID"):
        day = None
        try:
            day = datetime.strptime(earned, "%Y-%m-%d").replace(
                tzinfo=timezone.utc).timestamp() if earned else None
        except ValueError:
            pass
        rows.append({
            "award": award_name(name, workout_names), "internal": name or "",
            "day": day if day is not None else apple_time(created),
            "value": _unit(value, unit)})
    return rows


def mjd_day(index):
    """The date (midnight UTC, as Unix seconds) of a Modified Julian Date."""
    try:
        return (MJD_ORIGIN + timedelta(days=int(index))).timestamp()
    except (OverflowError, ValueError, TypeError):
        return None


def _clock(hour, minute):
    if hour is None or minute is None:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _days_text(row):
    chosen = [w[:3].capitalize() for w in WEEKDAYS if row.get(w)]
    if len(chosen) == 7:
        return "Every day"
    return ", ".join(chosen)


def sleep_schedule_rows(conn):
    if "bed_hour" not in table_columns(conn, "sleep_schedule_samples"):
        return []
    rows = []
    for (start, *rest) in sqlite_rows(
            conn, "SELECT s.start_date, " + ", ".join(
                f"c.{w}" for w in WEEKDAYS) +
            ", c.bed_hour, c.bed_minute, c.wake_hour, c.wake_minute, "
            "c.override_day_index FROM sleep_schedule_samples c JOIN samples "
            "s ON s.data_id = c.data_id ORDER BY s.start_date"):
        row = dict(zip(WEEKDAYS, rest[:7]))
        bed_h, bed_m, wake_h, wake_m, override = rest[7:]
        one_day = override is not None
        row.update({
            "set": apple_time(start),
            "kind": "One-day change" if one_day else "Schedule",
            "for": mjd_day(override) if one_day else None,
            "days": "" if one_day else _days_text(row),
            "bed": _clock(bed_h, bed_m), "wake": _clock(wake_h, wake_m)})
        if one_day and not row["bed"] and not row["wake"]:
            row["bed"] = row["wake"] = "(skipped)"
        rows.append(row)
    return rows


AUDIOGRAM = "HKDataTypeIdentifierAudiogram"


def _quantity(value):
    """``(number, unit)`` of an archived ``HKQuantity``, else ``(None, "")``."""
    if not isinstance(value, dict):
        return None, ""
    number = value.get("ValueKey")
    unit = value.get("UnitKey")
    unit = unit.get("HKUnitStringKey", "") if isinstance(unit, dict) else ""
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return None, ""
    return number, str(unit)


def audiogram_rows(conn, names):
    """One row for each point of each audiogram, oldest audiogram last."""
    numbers = [n for n, i in names.items() if i == AUDIOGRAM]
    if not numbers or "payload" not in table_columns(conn, "binary_samples"):
        return []
    rows = []
    marks = ",".join("?" * len(numbers))
    for start, payload in sqlite_rows(
            conn, "SELECT s.start_date, b.payload FROM binary_samples b "
                  f"JOIN samples s ON s.data_id = b.data_id WHERE "
                  f"s.data_type IN ({marks}) ORDER BY s.start_date",
            tuple(numbers)):
        try:
            tree = keyed_archive.unarchive(plistlib.loads(bytes(payload)))
        except (ValueError, TypeError, plistlib.InvalidFileException,
                keyed_archive.ArchiveError):
            continue
        points = tree if isinstance(tree, list) else (
            tree.get("SensitivityPointsKey") if isinstance(tree, dict)
            else None)
        for point in points if isinstance(points, list) else ():
            if not isinstance(point, dict):
                continue
            frequency, f_unit = _quantity(point.get("FrequencyKey"))
            left, l_unit = _quantity(point.get("LeftEarSensitivityKey"))
            right, r_unit = _quantity(point.get("RightEarSensitivityKey"))
            if frequency is None:
                continue
            rows.append({
                "when": apple_time(start), "frequency": frequency,
                "frequency_unit": f_unit or "Hz", "left": left, "right": right,
                "level_unit": l_unit or r_unit or "dB HL"})
    return rows


def _level(value, row):
    return "" if value is None else f"{value:g} {row['level_unit']}"


def _friends(conn):
    """``{friend uuid: number}`` in order of first appearance."""
    numbers = {}
    for table in ("fitness_friend_activity_snapshots",
                  "fitness_friend_workouts", "fitness_friend_achievements"):
        if "friend_uuid" not in table_columns(conn, table):
            continue
        for (friend,) in sqlite_rows(
                conn, f"SELECT friend_uuid FROM {table} ORDER BY data_id"):
            if friend not in numbers:
                numbers[friend] = len(numbers) + 1
    return numbers


def friend_workout_rows(conn, numbers, workout_types):
    if "friend_uuid" not in table_columns(conn, "fitness_friend_workouts"):
        return []
    rows = []
    for (friend, duration, energy, distance, kind, start, indoor) in \
            sqlite_rows(
                conn, "SELECT w.friend_uuid, w.duration, "
                      "w.total_energy_burned, w.total_distance, "
                      "w.activity_type, s.start_date, w.is_indoor_workout "
                      "FROM fitness_friend_workouts w LEFT JOIN samples s "
                      "ON s.data_id = w.data_id ORDER BY s.start_date"):
        rows.append({
            "friend": f"Friend {numbers.get(friend, '?')}",
            "when": apple_time(start), "kind": workout_types.get(
                kind, f"Type {kind}"),
            "duration": duration, "energy": energy, "distance": distance,
            "indoor": bool(indoor)})
    return rows


def friend_activity_rows(conn, numbers):
    if "friend_uuid" not in table_columns(
            conn, "fitness_friend_activity_snapshots"):
        return []
    rows = []
    for (friend, move, move_goal, brisk, brisk_goal, hours, hours_goal,
         steps, uploaded) in sqlite_rows(
            conn, "SELECT friend_uuid, energy_burned, energy_burned_goal, "
                  "brisk_minutes, brisk_minutes_goal, active_hours, "
                  "active_hours_goal, steps, uploaded_date FROM "
                  "fitness_friend_activity_snapshots ORDER BY uploaded_date"):
        rows.append({
            "friend": f"Friend {numbers.get(friend, '?')}",
            "when": apple_time(uploaded), "move": move,
            "move_goal": move_goal, "exercise": brisk,
            "exercise_goal": brisk_goal, "stand": hours,
            "stand_goal": hours_goal, "steps": steps})
    return rows


def _fraction(value, goal, unit=""):
    if value is None:
        return ""
    text = f"{value:,.0f}"
    if goal:
        text += f" / {goal:,.0f}"
    return f"{text} {unit}".strip()


def datasets(conn, workout_types, names=None):
    """The tables for what the database holds (each only if it has rows).
    *names* is ``{kind number: identifier}`` (see ``health.kind_names``)."""
    workout_names = {v.lower().replace(" ", ""): v
                     for v in workout_types.values()}
    result = []
    awards = award_rows(conn, workout_names)
    if awards:
        result.append(Dataset(
            "awards", "Awards", [
                Column("day", "Earned", 100, "day"),
                Column("award", "Award", 340),
                Column("value", "Value", 110, "text", "e")],
            awards, sort=("day", True),
            note="The phone stores each award's internal name, which is "
                 "made readable here; the names the Fitness app shows are "
                 "not in the backup.",
            details=lambda row: f"{row['award']}\nInternal name: "
                                f"{row['internal']}"))
    points = audiogram_rows(conn, names or {})
    if points:
        result.append(Dataset(
            "audiograms", "Audiograms", [
                Column("when", "Taken", 140, "date"),
                Column("frequency", "Frequency", 100, "text", "e",
                       format=lambda r: f"{r['frequency']:g} "
                                        f"{r['frequency_unit']}"),
                Column("left", "Left ear", 100, "text", "e",
                       format=lambda r: _level(r["left"], r)),
                Column("right", "Right ear", 100, "text", "e",
                       format=lambda r: _level(r["right"], r))],
            points, sort=("when", True),
            note="Hearing tests (audiograms) from the Health app, one row "
                 "for each frequency tested. Lower levels mean better "
                 "hearing."))
    schedules = sleep_schedule_rows(conn)
    if schedules:
        result.append(Dataset(
            "sleep_schedules", "Sleep schedules", [
                Column("set", "Set on", 140, "date"),
                Column("kind", "Kind", 110),
                Column("days", "Days", 220),
                Column("for", "For the day", 100, "day"),
                Column("bed", "Bedtime", 80, "text", "e"),
                Column("wake", "Wake up", 80, "text", "e")],
            schedules, sort=("set", True),
            note="Each row is a schedule you set, or a change for one day. "
                 "Times are the clock times of the schedule."))
    numbers = _friends(conn)
    workouts = friend_workout_rows(conn, numbers, workout_types)
    if workouts:
        result.append(Dataset(
            "friend_workouts", "Friends' workouts", [
                Column("when", "When", 140, "date"),
                Column("friend", "Friend", 90),
                Column("kind", "Workout", 200),
                Column("duration", "Length", 90, "duration", "e"),
                Column("energy", "Energy (kcal)", 100, "number", "e"),
                Column("distance", "Distance (m)", 100, "number", "e")],
            workouts, sort=("when", True),
            note="Workouts that friends in Activity sharing sent to this "
                 "phone. The database holds no names, so friends are "
                 "numbered."))
    activity = friend_activity_rows(conn, numbers)
    if activity:
        result.append(Dataset(
            "friend_activity", "Friends' activity", [
                Column("when", "Uploaded", 140, "date"),
                Column("friend", "Friend", 90),
                Column("move", "Move", 130, "text", format=lambda r:
                       _fraction(r["move"], r["move_goal"], "kcal")),
                Column("exercise", "Exercise", 120, "text", format=lambda r:
                       _fraction(r["exercise"], r["exercise_goal"], "min")),
                Column("stand", "Stand", 110, "text", format=lambda r:
                       _fraction(r["stand"], r["stand_goal"], "h")),
                Column("steps", "Steps", 90, "number", "e", format=lambda r:
                       "" if r["steps"] is None else f"{r['steps']:,.0f}")],
            activity, sort=("when", True),
            note="Activity summaries friends in Activity sharing sent to "
                 "this phone (value / goal)."))
    return result
