# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake Calendar.sqlitedb for tests. Everything here is invented."""

from tests.fixture_apps import T0, database_bytes

DATABASE = "HomeDomain/Library/Calendar/Calendar.sqlitedb"
DAY = 86400
D0 = T0 - T0 % DAY             # midnight UTC, where all-day events begin
NO_YEAR = -12_522_988_800      # 1604-03-01: Apple's "no year" for birthdays


def build(conn):
    conn.executescript("""
        CREATE TABLE Store (ROWID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, store_id INTEGER,
            title TEXT, color TEXT);
        CREATE TABLE Location (ROWID INTEGER PRIMARY KEY, title TEXT,
            address TEXT);
        CREATE TABLE Recurrence (ROWID INTEGER PRIMARY KEY, frequency INTEGER,
            interval INTEGER, count INTEGER, end_date REAL, specifier TEXT,
            owner_id INTEGER);
        CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, summary TEXT,
            description TEXT, location_id INTEGER, start_date REAL,
            end_date REAL, all_day INTEGER, calendar_id INTEGER,
            status INTEGER, url TEXT, has_recurrences INTEGER,
            entity_type INTEGER DEFAULT 2, UUID TEXT, last_modified REAL,
            creation_date REAL, unique_identifier TEXT, start_tz TEXT);
    """)
    conn.executemany("INSERT INTO Store VALUES (?, ?)",
                     [(1, "iCloud"), (2, "Holidays")])
    conn.executemany("INSERT INTO Calendar VALUES (?, ?, ?, ?)", [
        (1, 1, "Home", "#FF9500"), (2, 1, "Work <team>", "#34AADC"),
        (3, 2, "US Holidays", "#8295AF")])
    conn.execute("INSERT INTO Location VALUES (1, 'Office', '1 Main St, "
                 "Springfield')")
    conn.executemany("INSERT INTO Recurrence VALUES (?,?,?,?,?,?,?)", [
        (1, 4, 1, 0, None, "", 12),                  # every year
        (2, 2, 2, 5, None, "", 13),                  # every 2 weeks, 5 times
        (3, 4, 1, 6, None, "D=-1MO", 14),            # last Monday of the year's month
        (4, 1, 1, 0, T0 + 30 * DAY, "", 15)])        # daily until a date

    def item(pk, title, start, end, all_day=0, calendar=1, location=None,
             description=None, url=None, recurring=0, entity=2, uid=None):
        conn.execute(
            "INSERT INTO CalendarItem (ROWID, summary, description, "
            "location_id, start_date, end_date, all_day, calendar_id, url, "
            "has_recurrences, entity_type, UUID, last_modified) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pk, title, description, location, start, end, all_day, calendar,
             url, recurring, entity, uid or f"UUID-{pk}", T0 + pk))

    item(10, "Dentist", T0 + 9 * 3600, T0 + 10 * 3600, location=1,
         description="Bring the form;\nsecond line, with a comma")
    item(11, "Team <offsite>", D0 + DAY, D0 + 2 * DAY - 1, all_day=1,
         calendar=2)                                  # one whole day
    item(12, "Anniversary", D0 + 30 * DAY, D0 + 31 * DAY - 1, all_day=1,
         recurring=1)
    item(13, "Standup", T0 + 3 * DAY, T0 + 3 * DAY + 1800, calendar=2,
         recurring=1)
    item(14, "Memorial Day", D0 + 60 * DAY, D0 + 61 * DAY - 1, all_day=1,
         calendar=3, recurring=1)
    item(15, "Vitamins", T0 + 5 * DAY, T0 + 5 * DAY + 60, recurring=1,
         url="https://example.com/vitamins")
    item(16, "A trip", D0 + 10 * DAY, D0 + 13 * DAY - 1, all_day=1)  # 3 days
    item(17, "Birthday, no year", NO_YEAR, NO_YEAR + DAY - 1, all_day=1,
         calendar=3)
    item(18, "", T0 + 20 * DAY, T0 + 20 * DAY + 600)  # no title
    item(19, "Late night", T0 + 2 * DAY + 23 * 3600,
         T0 + 3 * DAY + 3600)                         # over midnight
    item(20, "A reminder, not an event", T0, T0, entity=3)
    conn.commit()


def backup_files():
    return [("HomeDomain", DATABASE.split("/", 1)[1], database_bytes(build))]
