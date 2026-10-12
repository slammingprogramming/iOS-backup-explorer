# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Sleep added up per night.

The Health database lists sleep as stages (in bed, asleep, awake, core, deep,
REM). To say what a *night* was, the stages are joined into nights and each
night is given the day it ended on, **where the phone was**. The database
keeps only the *name* of the time zone of each record (``data_provenances.
tz_name``), so turning that into an offset needs a time zone database.
Python's ``zoneinfo`` uses the operating system's, which Windows does not
have; the optional ``tzdata`` package supplies one (``pip install tzdata``).
Without any, the stages are still listed and this table is not made.

Rules (stated in ``docs/HEALTH.md``):

* A night is a run of sleep records in which no record starts more than four
  hours after the latest end of the ones before it. (A nap is a short night.)
* It belongs to the local date of its last record's end (the morning you woke
  up), in the time zone that record was made in.
* Records from two devices that overlap (a phone's "in bed" and a watch's
  stages) are counted once: each total is the *union* of its records.
"""

from datetime import datetime, timezone
from functools import lru_cache

GAP = 4 * 3600
ASLEEP = (1, 3, 4, 5)           # asleep (unspecified), core, deep, REM
STAGE_TOTALS = {"core": (3,), "deep": (4,), "rem": (5,), "other": (1,),
                "awake": (2,), "in_bed": (0,)}


@lru_cache(maxsize=None)
def zone(name):
    """The time zone called *name*, or None if there is none by that name or
    the computer has no time zone database (see the module note)."""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:        # no module (Python 3.8), no database, no name
        return None


def database_available():
    """Whether time zone names can be turned into offsets at all."""
    return zone("Etc/UTC") is not None


def union_seconds(intervals):
    """The total length of the union of ``(start, end)`` intervals."""
    total, current_start, current_end = 0.0, None, None
    for start, end in sorted(intervals):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total += current_end - current_start
    return total


def split_into_nights(samples):
    """Groups of samples (sorted by start), a new group wherever more than
    ``GAP`` seconds pass with no sleep record."""
    groups, current, latest = [], [], None
    for sample in sorted(samples, key=lambda s: (s["start"], s["end"])):
        if current and sample["start"] - latest > GAP:
            groups.append(current)
            current, latest = [], None
        current.append(sample)
        latest = sample["end"] if latest is None else max(latest,
                                                          sample["end"])
    if current:
        groups.append(current)
    return groups


def _clock(stamp, tz):
    return datetime.fromtimestamp(stamp, tz).strftime("%H:%M")


def _night(group):
    """The row for one group, or ``(None, why)``."""
    last = max(group, key=lambda s: s["end"])
    names = [last.get("zone")] + [s.get("zone") for s in group]
    tz = next((zone(n) for n in names if zone(n) is not None), None)
    if tz is None:
        if not any(names):
            return None, "no time zone"
        return None, ("no database" if not database_available()
                      else "unknown time zone")
    asleep = [s for s in group if s["stage"] in ASLEEP]
    woke = max((s["end"] for s in asleep), default=last["end"])
    went = min(s["start"] for s in group)
    fell = min((s["start"] for s in asleep), default=None)
    day = datetime.fromtimestamp(woke, tz).date()
    row = {
        "night": datetime(day.year, day.month, day.day,
                          tzinfo=timezone.utc).timestamp(),
        "bed": _clock(went, tz),
        "asleep_at": _clock(fell, tz) if fell is not None else "",
        "woke": _clock(woke, tz),
        "ended": woke,
        "asleep": union_seconds((s["start"], s["end"]) for s in asleep),
        "source": ", ".join(sorted({s["source"] for s in group
                                    if s.get("source")})),
        "zone": last.get("zone") or "",
        "records": len(group)}
    for key, stages in STAGE_TOTALS.items():
        row[key] = union_seconds((s["start"], s["end"]) for s in group
                                 if s["stage"] in stages)
    return row, None


def per_night(samples):
    """``(rows, problem)``: one row for each night, newest first; *problem*
    says why some nights, or all, could not be placed (or None).

    *samples* are dicts with ``start``, ``end`` (Unix seconds), ``stage`` (the
    HealthKit sleep value), ``zone`` (a time zone name, or None) and
    ``source``.
    """
    usable = [s for s in samples if s.get("start") is not None
              and s.get("end") is not None and s["end"] > s["start"]
              and isinstance(s.get("stage"), int)]
    rows, unplaced = [], {}
    for group in split_into_nights(usable):
        row, why = _night(group)
        if row is None:
            unplaced[why] = unplaced.get(why, 0) + 1
        else:
            rows.append(row)
    rows.sort(key=lambda r: (r["night"], r["ended"]), reverse=True)
    if not unplaced:
        return rows, None
    count = sum(unplaced.values())
    if "no database" in unplaced:
        return rows, ("this computer has no time zone database, so "
                      f"{count:,} night{'s' if count != 1 else ''} could "
                      "not be placed on a day: install one with "
                      "'pip install tzdata'")
    return rows, (f"{count:,} night{'s' if count != 1 else ''} could not be "
                  "placed on a day because the backup records no time zone "
                  "for them, or one this computer does not know")
