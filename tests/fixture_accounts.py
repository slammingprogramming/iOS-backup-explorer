# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake accounts database and device files for tests. Invented."""

import plistlib
from datetime import datetime

from tests.fixture_apps import T0, database_bytes

ACCOUNTS = "Library/Accounts/Accounts3.sqlite"
PREFERENCES = "SystemConfiguration/preferences.plist"


def build(conn):
    conn.executescript("""
        CREATE TABLE ZACCOUNTTYPE (Z_PK INTEGER PRIMARY KEY,
            ZACCOUNTTYPEDESCRIPTION TEXT);
        CREATE TABLE ZACCOUNT (Z_PK INTEGER PRIMARY KEY, ZACTIVE INTEGER,
            ZVISIBLE INTEGER, ZACCOUNTTYPE INTEGER, ZPARENTACCOUNT INTEGER,
            ZDATE REAL, ZACCOUNTDESCRIPTION TEXT, ZUSERNAME TEXT,
            ZOWNINGBUNDLEID TEXT);
        CREATE TABLE ZDATACLASS (Z_PK INTEGER PRIMARY KEY, ZNAME BLOB);
        CREATE TABLE Z_2ENABLEDDATACLASSES (Z_2ENABLEDACCOUNTS INTEGER,
            Z_7ENABLEDDATACLASSES INTEGER);
    """)
    conn.executemany("INSERT INTO ZACCOUNTTYPE VALUES (?, ?)", [
        (1, "iCloud"), (2, "CalDAV"), (3, "Game Center"), (4, None)])
    conn.executemany("INSERT INTO ZACCOUNT VALUES (?,?,?,?,?,?,?,?,?)", [
        (1, 1, 1, 1, None, T0, "iCloud", "person@example.com",
         "com.example.setup"),
        (2, 1, 0, 2, 1, T0 + 10, None, None, "accountsd"),
        (3, 0, 1, 3, None, T0 + 20, "  Games  ", "player1", None),
        (4, 1, None, 4, None, None, None, None, None),
        (5, 1, 1, 99, None, T0 + 30, None, None, None),   # unknown type
    ])
    # service names are stored as blobs, as in a real database
    conn.executemany("INSERT INTO ZDATACLASS VALUES (?, ?)", [
        (1, b"com.apple.Dataclass.Contacts"),
        (2, b"com.apple.Dataclass.Calendars"),
        (3, "com.apple.Dataclass.Mail"),                 # (a text one)
        (4, None)])
    conn.executemany("INSERT INTO Z_2ENABLEDDATACLASSES VALUES (?, ?)", [
        (1, 1), (1, 2), (1, 3), (1, 4), (1, 1), (2, 2), (3, 77)])
    conn.commit()


def preferences_plist(name=True):
    system = {"ComputerName": "Sam's Phone", "HostName": "Sams-Phone"} \
        if name else {}
    return plistlib.dumps({"Root": {
        "System": system,
        "Network": {"HostNames": {"LocalHostName": "Sams-Phone-local"}}}})


def info_plist():
    return plistlib.dumps({
        "Device Name": "Sam's Phone", "Product Name": "iPhone 13",
        "Product Type": "iPhone14,5", "Product Version": "18.2",
        "Build Version": "22C152", "Serial Number": "SERIAL12345",
        "Unique Identifier": "UDID-0001", "Phone Number": "+1 555 010 0000",
        "IMEI": "123456789012345", "GUID": "ignored",
        "Last Backup Date": datetime(2025, 6, 1, 12, 0)})


def manifest_plist():
    return plistlib.dumps({
        "IsEncrypted": False, "WasPasscodeSet": True,
        "Date": datetime(2025, 6, 1, 12, 5),
        "Lockdown": {"DeviceName": "Different Name",
                     "ProductType": "iPhone14,5", "ProductVersion": "18.2",
                     "BuildVersion": "22C152",
                     "SerialNumber": "SERIAL12345",
                     "UniqueDeviceID": "UDID-0001"}})


def status_plist():
    return plistlib.dumps({"IsFullBackup": True, "Version": "3.3"})


def backup_files(accounts=True, preferences=True):
    files = []
    if accounts:
        files.append(("HomeDomain", ACCOUNTS, database_bytes(build)))
    if preferences:
        files.append(("SystemPreferencesDomain", PREFERENCES,
                      preferences_plist()))
    return files
