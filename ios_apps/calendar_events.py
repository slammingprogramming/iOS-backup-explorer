# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading the Calendar app's database
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

"""Reads ``Calendar.sqlitedb``: the events (with their calendar, place,
notes and how they repeat) and the calendars. Can write the events as an
iCalendar (.ics) file. No GUI."""

import re

from . import ics
from .common import apple_time
from .records import Column, Dataset, fetch_dicts

DATABASE = "HomeDomain/Library/Calendar/Calendar.sqlitedb"

NO_YEAR = "1604-"          # what Apple stores as the year when there is none
_FREQUENCIES = {1: "DAILY", 2: "WEEKLY", 3: "MONTHLY", 4: "YEARLY"}
_EVERY = {1: "day", 2: "week", 3: "month", 4: "year"}
_DAYS = re.compile(r"D=((?:[+-]?\d?(?:MO|TU|WE|TH|FR|SA|SU),?)+)")


def describe_repeat(frequency, interval):
    """``Every year`` / ``Every 2 weeks``, or ``""`` for no repeat."""
    unit = _EVERY.get(frequency)
    if not unit:
        return ""
    interval = interval or 1
    return f"Every {unit}" if interval == 1 else f"Every {interval} {unit}s"


def _is_event(row):
    return row.get("entity_type") in (None, 2)


def event_rows(conn):
    """Every event as a dict, newest first."""
    calendars = {r["ROWID"]: r for r in fetch_dicts(
        conn, "Calendar", ["ROWID", "title", "store_id", "color"])}
    stores = {r["ROWID"]: r["name"] for r in fetch_dicts(
        conn, "Store", ["ROWID", "name"])}
    places = {}
    for row in fetch_dicts(conn, "Location",
                           ["ROWID", "title", "address"]):
        places[row["ROWID"]] = " ".join(p for p in (
            row["title"], row["address"]) if p)
    repeats = {}
    for row in fetch_dicts(conn, "Recurrence", [
            "owner_id", "frequency", "interval", "count", "end_date",
            "specifier"]):
        repeats[row["owner_id"]] = row
    rows = []
    for item in fetch_dicts(conn, "CalendarItem", [
            "ROWID", "summary", "description", "location_id", "start_date",
            "end_date", "all_day", "calendar_id", "status", "url",
            "has_recurrences", "entity_type", "UUID", "last_modified",
            "creation_date", "unique_identifier", "start_tz"],
            order="start_date"):
        if not _is_event(item):
            continue
        calendar = calendars.get(item["calendar_id"], {})
        start, end = item["start_date"], item["end_date"]
        repeat = repeats.get(item["ROWID"])
        rows.append({
            "id": item["ROWID"], "uid": item["UUID"]
            or item["unique_identifier"] or f"event-{item['ROWID']}",
            "title": (item["summary"] or "").strip(),
            "start": apple_time(start) if start is not None else None,
            "end": apple_time(end) if end is not None else None,
            "all_day": bool(item["all_day"]),
            "calendar": (calendar.get("title") or "").strip(),
            "account": stores.get(calendar.get("store_id")) or "",
            "place": places.get(item["location_id"], ""),
            "notes": (item["description"] or "").strip(),
            "url": item["url"] or "",
            "repeat": describe_repeat(repeat["frequency"], repeat["interval"])
            if repeat else "",
            "repeat_rule": repeat,
            "changed": apple_time(item["last_modified"])
            if item["last_modified"] else None,
        })
    return rows


def when_text(row):
    """How an event's time is written: a date for an all-day event (kept as
    a date, not moved to the computer's time zone), a date and time else."""
    from .common import format_datetime
    from .records import format_day
    if row["start"] is None:
        return ""
    if row["all_day"]:
        first, last = format_day(row["start"]), format_day(
            row["end"] - 1 if row["end"] else row["start"])
        if first.startswith(NO_YEAR):    # a birthday with no year
            first = f"{first[5:]} (year not set)"
            last = first
        return first if last == first or not row["end"] \
            else f"{first} to {last}"
    text = format_datetime(row["start"])
    if row["end"] and row["end"] != row["start"]:
        end = format_datetime(row["end"])
        text += f" - {end[11:]}" if end[:10] == text[:10] else f" - {end}"
    return text


def rrule(row):
    """The ``RRULE`` value for a repeating event, or None."""
    repeat = row.get("repeat_rule")
    if not repeat or repeat["frequency"] not in _FREQUENCIES:
        return None
    parts = [f"FREQ={_FREQUENCIES[repeat['frequency']]}"]
    if (repeat["interval"] or 1) > 1:
        parts.append(f"INTERVAL={repeat['interval']}")
    days = _DAYS.match(repeat.get("specifier") or "")
    if days:                                # e.g. the last Monday of May
        parts.append("BYDAY=" + days.group(1).rstrip(","))
        if repeat["frequency"] == 4 and row["start"] is not None:
            parts.append(f"BYMONTH={int(ics.day(row['start'])[4:6])}")
    if repeat.get("count"):
        parts.append(f"COUNT={repeat['count']}")
    elif repeat.get("end_date"):
        parts.append(f"UNTIL={ics.utc(apple_time(repeat['end_date']))}")
    return ";".join(parts)


def event_lines(row):
    """The lines of one ``VEVENT``."""
    props = [("UID", ics.escape(row["uid"]))]
    if row["changed"]:
        props.append(("DTSTAMP", ics.utc(row["changed"])))
    else:
        props.append(("DTSTAMP", ics.utc(row["start"] or 0)))
    if row["all_day"] and row["start"] is not None:
        props.append(("DTSTART;VALUE=DATE", ics.day(row["start"])))
        last = row["end"] - 1 if row["end"] else row["start"]
        props.append(("DTEND;VALUE=DATE", ics.next_day(max(last,
                                                           row["start"]))))
    elif row["start"] is not None:
        props.append(("DTSTART", ics.utc(row["start"])))
        if row["end"] is not None:
            props.append(("DTEND", ics.utc(row["end"])))
    props.append(("SUMMARY", ics.escape(row["title"] or "(no title)")))
    if row["place"]:
        props.append(("LOCATION", ics.escape(row["place"])))
    if row["notes"]:
        props.append(("DESCRIPTION", ics.escape(row["notes"])))
    if row["url"]:
        props.append(("URL", row["url"]))
    rule = rrule(row)
    if rule:
        props.append(("RRULE", rule))
    return (["BEGIN:VEVENT"] + ics.lines_of(props) + ["END:VEVENT"])


def write_ics(base, rows):
    """An iCalendar file of the events, for calendar programs to import."""
    return ics.write(base + ".ics", [event_lines(r) for r in rows
                                     if r["start"] is not None], "Events")


def datasets(conn):
    rows = event_rows(conn)
    calendars = {}
    for row in rows:
        entry = calendars.setdefault((row["account"], row["calendar"]), {
            "calendar": row["calendar"] or "(no name)",
            "account": row["account"], "events": 0, "first": None,
            "last": None})
        entry["events"] += 1
        for key, pick in (("first", min), ("last", max)):
            if row["start"] is not None:
                entry[key] = row["start"] if entry[key] is None \
                    else pick(entry[key], row["start"])
    if not rows:
        return []

    def details(row):
        lines = [row["title"] or "(no title)", when_text(row)]
        for label, key in (("Calendar", "calendar"), ("Place", "place"),
                           ("Repeats", "repeat"), ("Address", "url"),
                           ("Notes", "notes")):
            if row[key]:
                lines.append(f"{label}: {row[key]}")
        return "\n".join(lines)

    return [
        Dataset("events", "Events", [
            Column("start", "When", 230, format=when_text),
            Column("title", "Event", 300),
            Column("calendar", "Calendar", 150),
            Column("place", "Place", 180),
            Column("repeat", "Repeats", 90)],
            rows, sort=("start", True), details=details,
            formats={"ics": ("Calendar file (.ics, importable)", write_ics)}),
        Dataset("calendars", "Calendars", [
            Column("calendar", "Calendar", 260),
            Column("account", "Account", 160),
            Column("events", "Events", 80, "number", "e"),
            Column("first", "Earliest", 140, "date"),
            Column("last", "Latest", 140, "date")],
            list(calendars.values()), sort=("events", True)),
    ]


class CalendarReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        return datasets(self.conn)
