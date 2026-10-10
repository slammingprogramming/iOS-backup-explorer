# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake Safari databases (History.db, Bookmarks.db, SafariTabs.db).

Everything here is invented. The tables follow the layout iOS uses,
trimmed to what the reader looks at.
"""

from tests.fixture_apps import T0, database_bytes

HISTORY = "HomeDomain/Library/Safari/History.db"
BOOKMARKS = "HomeDomain/Library/Safari/Bookmarks.db"
TABS = "HomeDomain/Library/Safari/SafariTabs.db"


def build_history(conn):
    conn.executescript("""
        CREATE TABLE history_items (id INTEGER PRIMARY KEY, url TEXT,
            domain_expansion TEXT, visit_count INTEGER);
        CREATE TABLE history_visits (id INTEGER PRIMARY KEY,
            history_item INTEGER, visit_time REAL, title TEXT,
            load_successful BOOLEAN DEFAULT 1);
    """)
    conn.executemany("INSERT INTO history_items (id, url, visit_count) "
                     "VALUES (?, ?, ?)", [
        (1, "https://www.example.com/page?a=1&b=2", 3),
        (2, "https://news.example.org/story", 1),
        (3, "http://Example.COM/other", 1),
        (4, "about:blank", 1),
        (5, "https://shop.example.net/<cart>", 1)])
    conn.executemany(
        "INSERT INTO history_visits (history_item, visit_time, title, "
        "load_successful) VALUES (?, ?, ?, ?)", [
            (1, T0 + 10, "Example page", 1),
            (1, T0 + 500, "Example page", 1),
            (1, T0 + 900, "", 1),                    # a visit with no title
            (2, T0 + 100, "A <b>story</b>", 1),
            (3, T0 + 200, "Other", 0),               # the page did not load
            (4, T0 + 300, None, 1),
            (5, T0 + 400, "Cart", 1)])
    conn.commit()


BOOKMARK_COLUMNS = ("id INTEGER PRIMARY KEY, special_id INTEGER DEFAULT 0, "
                    "parent INTEGER, type INTEGER, title TEXT, url TEXT, "
                    "external_uuid TEXT, last_modified REAL, deleted INTEGER "
                    "DEFAULT 0, date_closed REAL")


def build_bookmarks(conn):
    conn.execute(f"CREATE TABLE bookmarks ({BOOKMARK_COLUMNS})")
    rows = [
        (0, 0, None, 1, "Root", None, "Root", None),
        (1, 1, 0, 1, "BookmarksBar", None, "UUID-BAR", None),
        (2, 3, 0, 1, "com.apple.ReadingList", None,
         "com.apple.ReadingList", None),
        (3, 0, 1, 1, "Shopping", None, "UUID-SHOP", None),
        (4, 0, 3, 1, "Deals & Offers", None, "UUID-DEALS", None),
        (10, 0, 1, 0, "Example", "https://www.example.com/", "U10", T0 + 1),
        (11, 0, 3, 0, "Shop <one>", "https://shop.example.net/?a=1&b=\"2\"",
         "U11", T0 + 2),
        (12, 0, 4, 0, "Deep", "https://deep.example.net/", "U12", T0 + 3),
        (13, 0, 0, 0, "At the root", "https://root.example.net/", "U13", None),
        (14, 0, 2, 0, "Read later", "https://later.example.net/", "U14",
         T0 + 4),
        (15, 0, 1, 0, "Removed", "https://gone.example.net/", "U15", T0),
        (16, 0, 1, 0, None, "https://untitled.example.net/", "U16", None),
    ]
    for row in rows:
        conn.execute("INSERT INTO bookmarks (id, special_id, parent, type, "
                     "title, url, external_uuid, last_modified, deleted) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", row + (1 if row[0] == 15
                                                          else 0,))
    conn.commit()


def build_tabs(conn):
    conn.execute(f"CREATE TABLE bookmarks ({BOOKMARK_COLUMNS})")
    for row in [
            (0, 0, None, 1, "Root", None, "Root", None),
            (5, 0, 0, 1, "Local", None, "UUID-LOCAL", None),
            (6, 0, 0, 1, "Private", None, "UUID-PRIVATE", None),
            (7, 0, 5, 0, "Tab one", "https://tab1.example.com/", "T7", None),
            (8, 0, 6, 0, "", "https://private.example.com/", "T8", None),
            (9, 0, 5, 0, None, "https://tab2.example.com/", "T9", None),
            (10, 0, 5, 0, "No address", None, "T10", None)]:
        conn.execute("INSERT INTO bookmarks (id, special_id, parent, type, "
                     "title, url, external_uuid, last_modified) "
                     "VALUES (?,?,?,?,?,?,?,?)", row)
    conn.commit()


def backup_files(history=True, bookmarks=True, tabs=True):
    files = []
    if history:
        files.append(("HomeDomain", HISTORY.split("/", 1)[1],
                      database_bytes(build_history)))
    if bookmarks:
        files.append(("HomeDomain", BOOKMARKS.split("/", 1)[1],
                      database_bytes(build_bookmarks)))
    if tabs:
        files.append(("HomeDomain", TABS.split("/", 1)[1],
                      database_bytes(build_tabs)))
    return files
