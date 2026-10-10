# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake Reminders databases for tests. Everything here is invented."""

from tests.fixture_apps import T0, database_bytes

FOLDER = "Library/Reminders/Container_v1/Stores"
STORE_A = f"{FOLDER}/Data-AAAA.sqlite"
STORE_B = f"{FOLDER}/Data-BBBB.sqlite"
STORE_LOCAL = f"{FOLDER}/Data-local.sqlite"
DAY = 86400
D0 = T0 - T0 % DAY                  # midnight UTC

KINDS = [(6, "REMCDAccount"), (25, "REMCDList"), (32, "REMCDReminder")]


def _kinds(conn):
    conn.execute("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, "
                 "Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER)")
    conn.executemany("INSERT INTO Z_PRIMARYKEY VALUES (?, ?, 0, 0)", KINDS)


REMINDER_COLUMNS = ("Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZTITLE TEXT, "
                    "ZNOTES TEXT, ZCOMPLETED INTEGER, ZFLAGGED INTEGER, "
                    "ZPRIORITY INTEGER, ZLIST INTEGER, ZPARENTREMINDER "
                    "INTEGER, ZALLDAY INTEGER, ZMARKEDFORDELETION INTEGER, "
                    "ZDUEDATE REAL, ZCREATIONDATE REAL, ZCOMPLETIONDATE REAL, "
                    "ZLASTMODIFIEDDATE REAL, ZSTARTDATE REAL")


def build_a(conn):
    """Reminders in a table of their own; lists and the account among the
    rows of ZREMCDOBJECT."""
    _kinds(conn)
    conn.executescript(f"""
        CREATE TABLE ZREMCDOBJECT (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,
            ZNAME TEXT, ZNAME1 TEXT, ZNAME2 TEXT, ZACCOUNT INTEGER,
            ZPARENTACCOUNT INTEGER, ZMARKEDFORDELETION INTEGER DEFAULT 0);
        CREATE TABLE ZREMCDREMINDER ({REMINDER_COLUMNS});
    """)
    conn.executemany(
        "INSERT INTO ZREMCDOBJECT (Z_PK, Z_ENT, ZNAME, ZNAME2, ZACCOUNT, "
        "ZPARENTACCOUNT, ZMARKEDFORDELETION) VALUES (?,?,?,?,?,?,?)", [
            (1, 6, "iCloud", None, None, None, 0),
            (3, 6, "Old account", None, None, None, 1),     # deleted
            (4, 25, None, "Groceries <home>", 1, 1, 0),
            (5, 25, None, "Work", 1, 1, 0),
            (6, 25, None, "Gone list", 1, 1, 1),
            (7, 25, None, "Orphan list", 3, 3, 0)])    # its account is gone
    insert = ("INSERT INTO ZREMCDREMINDER (Z_PK, Z_ENT, ZTITLE, ZNOTES, "
              "ZCOMPLETED, ZFLAGGED, ZPRIORITY, ZLIST, ZPARENTREMINDER, "
              "ZALLDAY, ZMARKEDFORDELETION, ZDUEDATE, ZCREATIONDATE, "
              "ZCOMPLETIONDATE, ZLASTMODIFIEDDATE) "
              "VALUES (?,32,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    conn.executemany(insert, [
        (15, "Buy milk", "Semi-skimmed;\nnot oat, please", 0, 1, 1, 4, None,
         1, 0, D0 + 2 * DAY, T0, None, T0 + 10),                # all day
        (16, "Call plumber", None, 0, 0, 0, 4, None, 0, 0, None, T0 + 5,
         None, T0 + 6),                                         # no due date
        (17, "Send report", None, 1, 0, 5, 5, None, 0, 0, T0 + 3600, T0 + 7,
         T0 + 7200, T0 + 7200),                                 # done
        (18, "Check the wording", None, 0, 0, 9, 5, 17, 0, 0, T0 + 3 * DAY,
         T0 + 8, None, T0 + 9),                                 # a subtask
        (19, "", None, 0, 0, 0, 4, None, 0, 0, None, T0 + 9, None, T0 + 9),
        (20, "Thrown away", None, 0, 0, 0, 4, None, 0, 1, None, T0 + 9, None,
         T0 + 9),                                               # deleted
        (21, "Nowhere", None, 0, 0, 0, 99, None, 0, 0, None, T0 + 9, None,
         T0 + 9),                                               # no list
    ])
    conn.commit()


def build_b(conn):
    """The other layout: reminders among the rows of ZREMCDOBJECT too."""
    _kinds(conn)
    conn.executescript(f"""
        CREATE TABLE ZREMCDOBJECT ({REMINDER_COLUMNS}, ZNAME TEXT,
            ZNAME1 TEXT, ZNAME2 TEXT, ZACCOUNT INTEGER,
            ZPARENTACCOUNT INTEGER);
    """)
    conn.execute("INSERT INTO ZREMCDOBJECT (Z_PK, Z_ENT, ZNAME) VALUES "
                 "(1, 6, 'On My iPhone')")
    conn.execute("INSERT INTO ZREMCDOBJECT (Z_PK, Z_ENT, ZNAME2, ZACCOUNT) "
                 "VALUES (2, 25, 'Local list', 1)")
    conn.execute("INSERT INTO ZREMCDOBJECT (Z_PK, Z_ENT, ZTITLE, ZLIST, "
                 "ZCOMPLETED, ZCREATIONDATE, ZLASTMODIFIEDDATE) "
                 "VALUES (3, 32, 'Water the plants', 2, 0, ?, ?)",
                 (T0 + 20, T0 + 21))
    conn.commit()


def build_empty(conn):
    conn.execute("CREATE TABLE Z_METADATA (Z_VERSION INTEGER)")
    conn.commit()


def backup_files(second=True, local=True):
    files = [("HomeDomain", STORE_A, database_bytes(build_a))]
    if second:
        files.append(("HomeDomain", STORE_B, database_bytes(build_b)))
    if local:
        files.append(("HomeDomain", STORE_LOCAL, database_bytes(build_empty)))
    files.append(("HomeDomain", f"{FOLDER}/Data-AAAA.sqlite-wal", b""))
    files.append(("HomeDomain", f"{FOLDER}/notes.txt", b"x"))
    return files
