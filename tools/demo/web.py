# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The demo phone's Safari data, calendar and reminders."""

import random
from datetime import datetime, timedelta, timezone

from . import NOW, ago, clone_schema, cocoa

HOME = "HomeDomain"


# ── Safari ───────────────────────────────────────────────────

SITES = [
    ("www.example.org", [
        ("Pine Ridge Trail Guide", "/trail-guide/pine-ridge"),
        ("Weather forecast for Springfield", "/weather/springfield"),
        ("City bike share map", "/bikes/map"),
        ("Sourdough starter: a beginner's guide", "/recipes/sourdough")]),
    ("news.example.com", [
        ("Local council approves new bike lanes", "/local/bike-lanes"),
        ("Autumn festival returns this weekend", "/events/autumn-festival"),
        ("Morning briefing", "/briefing")]),
    ("www.example.net", [
        ("Lisbon in three days", "/travel/lisbon-three-days"),
        ("Best pastel de nata, ranked", "/travel/pastel-de-nata"),
        ("Tram 28 timetable", "/travel/tram-28")]),
    ("shop.example.com", [
        ("Lightweight rain jacket", "/p/rain-jacket"),
        ("Trail running shoes", "/p/trail-shoes"),
        ("Your cart", "/cart")]),
    ("docs.example.dev", [
        ("Getting started – documentation", "/start"),
        ("API reference", "/api")]),
    ("recipes.example.org", [
        ("Lemon cake with olive oil", "/lemon-cake"),
        ("Roasted tomato soup", "/tomato-soup")]),
    ("www.example.com", [
        ("Springfield Health Clinic – patient portal", "/clinic"),
        ("Pizza Palace – order online", "/pizza-palace")]),
]


def safari(writer):
    from tests import fixture_safari as fs
    rng = random.Random(7)

    def history(conn):
        clone_schema(fs.build_history, conn)
        item = 0
        for host, pages in SITES:
            for title, path in pages:
                item += 1
                conn.execute("INSERT INTO history_items (id, url, "
                             "visit_count) VALUES (?, ?, 0)",
                             (item, f"https://{host}{path}"))
                for _ in range(rng.randrange(1, 7)):
                    moment = ago(days=rng.randrange(0, 40),
                                 hours=rng.randrange(0, 24),
                                 minutes=rng.randrange(0, 60))
                    conn.execute(
                        "INSERT INTO history_visits (history_item, "
                        "visit_time, title, load_successful) "
                        "VALUES (?,?,?,?)",
                        (item, cocoa(moment), title,
                         0 if rng.random() < .03 else 1))
        conn.execute("UPDATE history_items SET visit_count = (SELECT "
                     "COUNT(*) FROM history_visits WHERE history_item = "
                     "history_items.id)")

    def bookmarks(conn):
        conn.execute(f"CREATE TABLE bookmarks ({fs.BOOKMARK_COLUMNS})")
        rows = [
            (0, 0, None, 1, "Root", None, "Root", None),
            (1, 1, 0, 1, "BookmarksBar", None, "UUID-BAR", None),
            (2, 3, 0, 1, "com.apple.ReadingList", None,
             "com.apple.ReadingList", None),
            (3, 0, 1, 1, "Cooking", None, "UUID-COOK", None),
            (4, 0, 1, 1, "Travel", None, "UUID-TRAVEL", None),
            (5, 0, 1, 1, "Work", None, "UUID-WORK", None),
            (10, 0, 1, 0, "Weather – Springfield",
             "https://www.example.org/weather/springfield", "U10", 1),
            (11, 0, 1, 0, "City bike share map",
             "https://www.example.org/bikes/map", "U11", 2),
            (12, 0, 3, 0, "Lemon cake with olive oil",
             "https://recipes.example.org/lemon-cake", "U12", 3),
            (13, 0, 3, 0, "Roasted tomato soup",
             "https://recipes.example.org/tomato-soup", "U13", 4),
            (14, 0, 3, 0, "Sourdough starter guide",
             "https://www.example.org/recipes/sourdough", "U14", 5),
            (15, 0, 4, 0, "Lisbon in three days",
             "https://www.example.net/travel/lisbon-three-days", "U15", 6),
            (16, 0, 4, 0, "Tram 28 timetable",
             "https://www.example.net/travel/tram-28", "U16", 7),
            (17, 0, 5, 0, "Documentation",
             "https://docs.example.dev/start", "U17", 8),
            (18, 0, 5, 0, "API reference", "https://docs.example.dev/api",
             "U18", 9),
            (19, 0, 2, 0, "Autumn festival returns this weekend",
             "https://news.example.com/events/autumn-festival", "U19", 10),
            (20, 0, 2, 0, "Best pastel de nata, ranked",
             "https://www.example.net/travel/pastel-de-nata", "U20", 11),
        ]
        for row in rows:
            moment = cocoa(ago(days=60 - (row[7] or 0) * 4)) \
                if row[7] else None
            conn.execute(
                "INSERT INTO bookmarks (id, special_id, parent, type, title,"
                " url, external_uuid, last_modified, deleted) "
                "VALUES (?,?,?,?,?,?,?,?,0)", row[:7] + (moment,))

    def tabs(conn):
        conn.execute(f"CREATE TABLE bookmarks ({fs.BOOKMARK_COLUMNS})")
        for row in [
                (0, 0, None, 1, "Root", None, "Root"),
                (5, 0, 0, 1, "Local", None, "UUID-LOCAL"),
                (6, 0, 0, 1, "Private", None, "UUID-PRIVATE"),
                (7, 0, 5, 0, "Pine Ridge Trail Guide",
                 "https://www.example.org/trail-guide/pine-ridge", "T7"),
                (8, 0, 5, 0, "Lisbon in three days",
                 "https://www.example.net/travel/lisbon-three-days", "T8"),
                (9, 0, 5, 0, "Lightweight rain jacket",
                 "https://shop.example.com/p/rain-jacket", "T9"),
                (10, 0, 5, 0, "Morning briefing",
                 "https://news.example.com/briefing", "T10")]:
            conn.execute("INSERT INTO bookmarks (id, special_id, parent, "
                         "type, title, url, external_uuid) "
                         "VALUES (?,?,?,?,?,?,?)", row)

    writer.database(HOME, "Library/Safari/History.db", history)
    writer.database(HOME, "Library/Safari/Bookmarks.db", bookmarks)
    writer.database(HOME, "Library/Safari/SafariTabs.db", tabs)


# ── Calendar ─────────────────────────────────────────────────

def _midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def calendar(writer):
    from tests import fixture_calendar as fc

    def build(conn):
        clone_schema(fc.build, conn)
        conn.executemany("INSERT INTO Store VALUES (?, ?)",
                         [(1, "iCloud"), (2, "Holidays"), (3, "Work")])
        conn.executemany("INSERT INTO Calendar VALUES (?,?,?,?)", [
            (1, 1, "Home", "#FF9500"), (2, 3, "Work", "#34AADC"),
            (3, 2, "US Holidays", "#8295AF"), (4, 1, "Family", "#AF52DE")])
        conn.executemany("INSERT INTO Location VALUES (?,?,?)", [
            (1, "Springfield Health Clinic", "100 Clinic Way, Springfield"),
            (2, "Pine Ridge Trailhead", "Pine Ridge Road"),
            (3, "Cafe Aroma", "5 Market Square, Springfield"),
            (4, "Review room 2B", "Main office")])
        pk = [100]

        def event(title, start, end, calendar_id=1, all_day=0, place=None,
                  notes=None, repeat=None, url=None):
            pk[0] += 1
            number = pk[0]
            if repeat:
                conn.execute(
                    "INSERT INTO Recurrence VALUES (?,?,?,?,?,?,?)",
                    (number, repeat[0], repeat[1], repeat[2], None, "",
                     number))
            conn.execute(
                "INSERT INTO CalendarItem (ROWID, summary, description, "
                "location_id, start_date, end_date, all_day, calendar_id, "
                "url, has_recurrences, entity_type, UUID, last_modified) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,2,?,?)",
                (number, title, notes, place, cocoa(start), cocoa(end),
                 all_day, calendar_id, url, 1 if repeat else 0,
                 f"DEMO-{number}", cocoa(ago(days=30))))

        def at(days, hour, minute=0):
            day = NOW + timedelta(days=days)
            return datetime(day.year, day.month, day.day, hour, minute,
                            tzinfo=timezone.utc)

        event("Team standup", at(1, 14), at(1, 14, 15), 2, repeat=(2, 1, 0))
        event("Dentist appointment", at(3, 15, 30), at(3, 16, 15), 1,
              place=None, notes="Bring the insurance card.")
        event("Doctor – annual check-up", at(5, 14, 30), at(5, 15, 15),
              1, place=1)
        event("Pine Ridge hike", at(1, 11, 30), at(1, 19, 0), 1, place=2,
              notes="Meet Alex, Jordan and Sam. Bring water and snacks.")
        event("Lunch with Jordan", at(-2, 16, 0), at(-2, 17, 0), 1, place=3)
        event("Q4 planning review", at(4, 15, 0), at(4, 16, 30), 2, place=4,
              notes="Agenda: scope, schedule, risks.")
        event("Yoga class", at(2, 22, 30), at(2, 23, 30), 1,
              repeat=(2, 1, 0))
        event("Sunday dinner at Mom's", at(2, 21, 0), at(2, 23, 0), 4)
        event("Sourdough workshop", at(8, 16, 0), at(8, 18, 0), 1, place=3)
        event("Lisbon trip", _midnight(NOW + timedelta(days=21)),
              _midnight(NOW + timedelta(days=25)) - timedelta(seconds=1), 1,
              all_day=1, notes="Flight TP 237 departs 10:05.")
        event("Mom's birthday", _midnight(datetime(2027, 4, 18)),
              _midnight(datetime(2027, 4, 19)) - timedelta(seconds=1), 4,
              all_day=1, repeat=(4, 1, 0))
        event("Alex's birthday", _midnight(datetime(2027, 3, 14)),
              _midnight(datetime(2027, 3, 15)) - timedelta(seconds=1), 4,
              all_day=1, repeat=(4, 1, 0))
        event("Pay rent", _midnight(NOW + timedelta(days=22)),
              _midnight(NOW + timedelta(days=23)) - timedelta(seconds=1), 1,
              all_day=1, repeat=(3, 1, 0))
        for title, day in (("Indigenous Peoples' Day", datetime(2026, 10, 12)),
                           ("Halloween", datetime(2026, 10, 31)),
                           ("Veterans Day", datetime(2026, 11, 11)),
                           ("Thanksgiving", datetime(2026, 11, 26)),
                           ("Christmas Day", datetime(2026, 12, 25)),
                           ("New Year's Day", datetime(2027, 1, 1))):
            event(title, _midnight(day),
                  _midnight(day) + timedelta(days=1, seconds=-1), 3,
                  all_day=1)
        for weeks in range(1, 9):
            event("Weekly review", at(-7 * weeks, 20), at(-7 * weeks, 20,
                                                          30), 2)

    writer.database(HOME, "Library/Calendar/Calendar.sqlitedb", build)


# ── Reminders ────────────────────────────────────────────────

def reminders(writer):
    from tests import fixture_reminders as fr

    def build(conn):
        clone_schema(fr.build_a, conn)
        conn.executemany(
            "INSERT INTO Z_PRIMARYKEY VALUES (?, ?, 0, 0)", fr.KINDS)
        conn.execute("INSERT INTO ZREMCDOBJECT (Z_PK, Z_ENT, ZNAME) "
                     "VALUES (1, 6, 'iCloud')")
        lists = {4: "Groceries", 5: "Home", 6: "Work", 7: "Trip prep"}
        for pk, name in lists.items():
            conn.execute(
                "INSERT INTO ZREMCDOBJECT (Z_PK, Z_ENT, ZNAME2, ZACCOUNT, "
                "ZPARENTACCOUNT, ZMARKEDFORDELETION) VALUES (?,25,?,1,1,0)",
                (pk, name))
        pk = [0]

        def reminder(title, list_id, due=None, all_day=0, priority=0,
                     flagged=0, done=0, notes=None, parent=None):
            pk[0] += 1
            number = pk[0]
            conn.execute(
                "INSERT INTO ZREMCDREMINDER (Z_PK, Z_ENT, ZTITLE, ZNOTES, "
                "ZCOMPLETED, ZFLAGGED, ZPRIORITY, ZLIST, ZPARENTREMINDER, "
                "ZALLDAY, ZMARKEDFORDELETION, ZDUEDATE, ZCREATIONDATE, "
                "ZCOMPLETIONDATE, ZLASTMODIFIEDDATE) VALUES "
                "(?,32,?,?,?,?,?,?,?,?,0,?,?,?,?)",
                (number, title, notes, done, flagged, priority, list_id,
                 parent, all_day, cocoa(due) if due else None,
                 cocoa(ago(days=10)), cocoa(ago(days=1)) if done else None,
                 cocoa(ago(days=1))))
            return number

        def day(days):
            moment = NOW + timedelta(days=days)
            return datetime(moment.year, moment.month, moment.day,
                            tzinfo=timezone.utc)

        reminder("Milk, eggs and butter", 4, day(1), 1, flagged=1)
        reminder("Lemons for the cake", 4, day(2), 1)
        reminder("Coffee beans", 4, done=1)
        reminder("Call the dentist to confirm", 5, NOW + timedelta(
            days=1, hours=-3), priority=1, flagged=1,
            notes="Appointment is on Friday afternoon.")
        reminder("Water the plants", 5, NOW + timedelta(days=2), priority=5)
        reminder("Fix the bike light", 5, priority=9)
        reminder("Renew passport", 7, day(15), 1, priority=1,
                 notes="Photo and form are in the top drawer.")
        trip = reminder("Book the airport transfer", 7, day(14), 1)
        reminder("Compare prices", 7, parent=trip)
        reminder("Send draft schedule to Jordan", 6, NOW + timedelta(
            days=3, hours=2), priority=5)
        reminder("Update the roadmap page", 6, day(5), 1)
        reminder("Book the review room", 6, done=1)

    writer.database(HOME, "Library/Reminders/Container_v1/Stores/"
                    "Data-DEMO0001.sqlite", build)
    writer.database(HOME, "Library/Reminders/Container_v1/Stores/"
                    "Data-local.sqlite", fr.build_empty)
