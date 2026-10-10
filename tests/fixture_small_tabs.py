# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake databases for the Privacy, Apps, Recent contacts and iCloud Drive
tabs. Everything here is invented."""

import plistlib

from tests.fixture_apps import database_bytes

UNIX0 = 1_700_000_000

PRIVACY = ("HomeDomain", "Library/TCC/TCC.db")
APPS = ("HomeDomain", "Library/FrontBoard/applicationState.db")
RECENTS = ("HomeDomain", "Library/Recents/Recents")
LOCATION = ("RootDomain", "Library/Caches/locationd/clients.plist")
ICLOUD = ("HomeDomain", "Library/Application Support/FileProvider/backup/"
          "backup_manifest.db")


def build_privacy(conn):
    conn.execute("""CREATE TABLE access (service TEXT, client TEXT,
        client_type INTEGER, auth_value INTEGER, auth_reason INTEGER,
        auth_version INTEGER, csreq BLOB, policy_id INTEGER,
        indirect_object_identifier_type INTEGER,
        indirect_object_identifier TEXT, indirect_object_code_identity BLOB,
        flags INTEGER, last_modified INTEGER)""")
    conn.executemany(
        "INSERT INTO access (service, client, client_type, auth_value, "
        "auth_reason, last_modified) VALUES (?,?,?,?,?,?)", [
            ("kTCCServicePhotos", "com.example.app", 0, 2, 2, UNIX0),
            ("kTCCServiceLiverpool", "com.example.app", 0, 0, 4, UNIX0 + 5),
            ("kTCCServiceAddressBook", "com.apple.mobilesafari", 0, 3, 3,
             UNIX0 + 10),
            ("kTCCServiceSomethingNewHere", "/usr/bin/tool", 1, 1, 99, None),
            ("kTCCServiceMicrophone", "com.example.other", 0, 7, None, 0),
            (None, None, 0, 2, 2, UNIX0)])
    conn.execute("CREATE TABLE admin (key TEXT, value INTEGER)")
    conn.commit()


def build_apps(conn):
    conn.executescript("""
        CREATE TABLE application_identifier_tab (id INTEGER PRIMARY KEY,
            application_identifier TEXT);
        CREATE TABLE key_tab (id INTEGER PRIMARY KEY, key TEXT);
        CREATE TABLE kvs (id INTEGER PRIMARY KEY, application_identifier
            INTEGER, key INTEGER, value BLOB);
    """)
    conn.executemany("INSERT INTO application_identifier_tab VALUES (?, ?)", [
        (1, "com.apple.mobilesafari"), (2, "com.example.tool"),
        (3, "com.apple.unknownthing"), (4, ""), (5, None)])
    conn.executemany("INSERT INTO key_tab VALUES (?, ?)", [
        (1, "SBApplicationBadgeKey"), (2, "compatibilityInfo")])
    conn.executemany("INSERT INTO kvs (application_identifier, key, value) "
                     "VALUES (?, ?, ?)", [
        (1, 1, 3), (2, 1, "!"), (3, 1, b"blob"), (1, 2, b"x")])
    conn.commit()


def build_recents(conn):
    conn.executescript("""
        CREATE TABLE contacts (ROWID INTEGER PRIMARY KEY, recent_id INTEGER,
            display_name TEXT, kind TEXT, address TEXT);
        CREATE TABLE recents (ROWID INTEGER PRIMARY KEY, display_name TEXT,
            bundle_identifier TEXT, sending_address TEXT,
            original_source TEXT, dates BLOB, last_date REAL, weight REAL,
            record_hash TEXT, count INTEGER, group_kind INTEGER);
    """)
    ms = UNIX0 * 1000
    conn.executemany(
        "INSERT INTO recents (ROWID, display_name, bundle_identifier, "
        "sending_address, original_source, last_date, count) "
        "VALUES (?,?,?,?,?,?,?)", [
            (1, "Alex Example", "com.apple.MobileSMS", None, None, ms, 5),
            (2, "", "com.apple.mobilemail", None, None, ms + 60_000, 2),
            (3, None, "com.example.unknown", "x@example.com", None, None,
             None),
            (4, "Pizza", None, None, "com.apple.Passbook", ms - 5000, 1)])
    conn.executemany(
        "INSERT INTO contacts (recent_id, display_name, kind, address) "
        "VALUES (?,?,?,?)", [
            (1, "Alex Example", "phone", "+15550100001"),
            (1, "Alex Example", "email", "alex@example.com"),
            (2, "", "email", "someone@example.org")])
    conn.commit()


def build_icloud(conn):
    conn.execute("""CREATE TABLE backup_manifest (relative_path TEXT,
        file_id INTEGER, doc_id INTEGER, gen_count INTEGER,
        new_file_id INTEGER, new_doc_id INTEGER, new_gen_count INTEGER)""")
    conn.executemany("INSERT INTO backup_manifest (relative_path) VALUES (?)",
                     [("Projects/Plan 2025/notes.TXT",), ("readme",),
                      ("Folder/.hidden.pdf.icloud",), ("/",), ("",),
                      (None,), ("Deep/er/still/file.tar.gz",)])
    conn.commit()


def location_plist():
    return plistlib.dumps({
        "com.example.app": {"Authorization": 4, "Registered": True,
                            "LocationTimeStopped": 700_000_000.5},
        "com.apple.Maps": {"Authorization": 3},
        "com.example.never": {"Authorization": 2},
        "com.example.undecided": {"Authorization": 0},
        "com.example.mask": {"SupportedAuthorizationMask": 7},
        "com.example.weird": {"Authorization": 9, "LocationTimeStopped": 0},
        "com.apple.locationd.executable-/usr/libexec/somed": {
            "Authorization": 4},
        "com.apple.locationd.bundle-/System/Library/LocationBundles/"
        "Thing.bundle/": {},
        "junk": "not a record"})


def files(privacy=True, apps=True, recents=True, icloud=True,
          location=True):
    result = []
    if location:
        result.append(LOCATION + (location_plist(),))
    for wanted, (domain, path), builder in (
            (privacy, PRIVACY, build_privacy), (apps, APPS, build_apps),
            (recents, RECENTS, build_recents), (icloud, ICLOUD,
                                                build_icloud)):
        if wanted:
            result.append((domain, path, database_bytes(builder)))
    return result
