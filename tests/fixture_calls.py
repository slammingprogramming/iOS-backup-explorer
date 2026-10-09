# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake call history database (CallHistory.storedata) for tests.

Everything here is invented. The table follows the layout iOS uses,
trimmed to what the reader looks at.
"""

from tests.fixture_apps import T0, build_addressbook, database_bytes

SCHEMA = """
CREATE TABLE ZCALLRECORD (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZANSWERED INTEGER, ZCALLTYPE INTEGER, ZDISCONNECTED_CAUSE INTEGER,
    ZFACE_TIME_DATA INTEGER, ZORIGINATED INTEGER, ZREAD INTEGER,
    ZDATE TIMESTAMP, ZDURATION FLOAT, ZISO_COUNTRY_CODE VARCHAR,
    ZLOCATION VARCHAR, ZNAME VARCHAR, ZSERVICE_PROVIDER VARCHAR,
    ZUNIQUE_ID VARCHAR, ZADDRESS BLOB);
"""

PHONE, FT = "com.apple.Telephony", "com.apple.FaceTime"


def build(conn):
    conn.executescript(SCHEMA)

    def call(pk, address, when, duration, originated, answered, kind=1,
             service=PHONE, name=None, location=None, country=None, read=1):
        if isinstance(address, str) and address.startswith("+"):
            address = address.encode("utf-8")        # the phone stores bytes
        conn.execute(
            "INSERT INTO ZCALLRECORD (Z_PK, ZANSWERED, ZCALLTYPE, ZORIGINATED,"
            " ZREAD, ZDATE, ZDURATION, ZISO_COUNTRY_CODE, ZLOCATION, ZNAME, "
            "ZSERVICE_PROVIDER, ZUNIQUE_ID, ZADDRESS) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pk, answered, kind, originated, read, when, duration, country,
             location, name, service, f"UID-{pk}", address))

    call(1, "+15550101234", T0, 125.0, 1, 1, location="Seattle, WA",
         country="us")                                       # Alice, out
    call(2, "+15550105678", T0 + 3600, 61.0, 0, 1)           # Bob, answered
    call(3, "+15550109999", T0 + 7200, 0.0, 0, 0, name="Spam Likely",
         read=0)                                             # missed, unread
    call(4, "friend@example.com", T0 + 10800, 3725.5, 1, 1, kind=8,
         service=FT)                                         # FaceTime video
    call(5, "+15550101234", T0 + 14400, 30.0, 0, 1, kind=16,
         service=FT)                                         # FaceTime audio
    call(6, None, T0 + 18000, 0.0, 0, 0)                     # unknown, missed
    call(7, "555-010-7777", T0 + 21600, 0.0, 1, 0)           # Pizza, no answer
    call(8, "+15550106666", T0 + 25200, 5.0, 0, 1)           # no name at all
    call(9, "+15550101234", T0 - 40_000_000, 600.0, 0, 1,
         location="Portland, OR", country="us")              # long ago
    conn.commit()


def backup_files():
    return [("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata",
             database_bytes(build)),
            ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb",
             database_bytes(build_addressbook))]
