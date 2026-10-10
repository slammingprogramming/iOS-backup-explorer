# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake Wi-Fi, Bluetooth and data-usage files for tests. Invented."""

import plistlib
from datetime import datetime, timezone

from tests.fixture_apps import T0, database_bytes

WIFI_KNOWN = "com.apple.wifi.known-networks.plist"
WIFI_OLD = "SystemConfiguration/com.apple.wifi.plist"
BT_CLASSIC = ("Library/Preferences/"
              "com.apple.MobileBluetooth.devices.plist")
BT_PAIRED = "Library/Database/com.apple.MobileBluetooth.ledevices.paired.db"
BT_OTHER = "Library/Database/com.apple.MobileBluetooth.ledevices.other.db"
USAGE = "Library/Databases/DataUsage.sqlite"
BT_DOMAIN = "SysSharedContainerDomain-systemgroup.com.apple.bluetooth"

JOINED = datetime(2025, 6, 1, 12, 30, 0)           # naive, meaning UTC
ADDED = datetime(2025, 5, 1, 8, 0, 0)
SEEN = datetime(2025, 6, 2, 9, 15, 0)


def wifi_known(old_format=False):
    networks = {
        "wifi.network.ssid.Home Net": {
            "SSID": "Home Net".encode("utf-8"),
            "SupportedSecurityTypes": "WPA2 Personal",
            "AddedAt": ADDED, "JoinedByUserAt": JOINED,
            "LastDiscoveredAt": SEEN, "Hidden": False,
            "CarPlayNetwork": False,
            "__OSSpecific__": {"BSSID": "aa:bb:cc:00:11:22", "CHANNEL": 36},
            "BSSList": [
                {"BSSID": "aa:bb:cc:00:11:22", "LocationLatitude": 12.5,
                 "LocationLongitude": -45.25, "LocationAccuracy": 35.0,
                 "LocationTimestamp": datetime(2025, 5, 3)},
                {"BSSID": "aa:bb:cc:00:11:33", "LocationLatitude": 12.6,
                 "LocationLongitude": -45.5, "LocationAccuracy": 20.0,
                 "LocationTimestamp": datetime(2025, 6, 1)},
                {"BSSID": "aa:bb:cc:00:11:44"},          # no place
            ]},
        "wifi.network.ssid.Caf\u00e9 \u2615": {
            "SSID": "Caf\u00e9 \u2615".encode("utf-8"),
            "SupportedSecurityTypes": "Open", "AddedAt": ADDED,
            "Hidden": True, "CarPlayNetwork": True,
            "__OSSpecific__": {"prevJoined": JOINED}},
        "wifi.network.ssid.NoSsidField": {"AddedAt": ADDED},
        "wifi.network.ssid.BadBytes": {"SSID": b"\xff\xfe-net"},
        "junk": "not a dict",
    }
    return plistlib.dumps(networks)


def wifi_old():
    return plistlib.dumps({"List of known networks": [
        {"SSID_STR": "Old Net", "SecurityMode": "WPA2", "BSSID": "11:22",
         "lastJoined": JOINED, "lastAutoJoined": SEEN, "added": ADDED,
         "HIDDEN_NETWORK": True},
        {"SSID_STR": ""}, "junk"]})


def bluetooth_classic():
    return plistlib.dumps({
        "7C:F3:00:00:00:01": {"Name": "Sam's Headphones",
                              "LastSeenTime": 1_728_501_402},
        "D8:BE:00:00:00:02": {},                       # nothing known
        "AA:AA:00:00:00:03": {"DefaultName": "Speaker", "LastSeenTime": 0},
        "junk": 5})


def build_paired(conn):
    conn.execute("CREATE TABLE PairedDevices (Uuid TEXT, Name TEXT, "
                 "NameOrigin INTEGER, Address TEXT, ResolvedAddress TEXT, "
                 "LastSeenTime INTEGER, LastConnectionTime INTEGER)")
    conn.execute("INSERT INTO PairedDevices VALUES ('u1', 'Smart Watch', 2, "
                 "'11:11:11:11:11:11', '22:22:22:22:22:22', 45139, 248)")
    conn.commit()


def build_other(conn):
    conn.execute("CREATE TABLE OtherDevices (Uuid TEXT, Name TEXT, "
                 "NameOrigin INTEGER, Address TEXT, ResolvedAddress TEXT, "
                 "LastSeenTime INTEGER, LastConnectionTime INTEGER)")
    conn.executemany("INSERT INTO OtherDevices VALUES (?, ?, 0, ?, ?, 244, "
                     "0)", [("u2", "Beacon 1", "33:33", ""),
                            ("u3", None, "", "44:44"),
                            ("u4", "Beacon 3", "55:55", "")])
    conn.commit()


def build_usage(conn):
    conn.executescript("""
        CREATE TABLE ZPROCESS (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,
            Z_OPT INTEGER, ZFIRSTTIMESTAMP REAL, ZTIMESTAMP REAL,
            ZBUNDLENAME TEXT, ZPROCNAME TEXT);
        CREATE TABLE ZLIVEUSAGE (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,
            Z_OPT INTEGER, ZKIND INTEGER, ZMETADATA INTEGER, ZTAG INTEGER,
            ZHASPROCESS INTEGER, ZBILLCYCLEEND INTEGER, ZTIMESTAMP REAL,
            ZWIFIIN REAL, ZWIFIOUT REAL, ZWWANIN REAL, ZWWANOUT REAL);
    """)
    conn.executemany("INSERT INTO ZPROCESS (Z_PK, ZFIRSTTIMESTAMP, ZTIMESTAMP,"
                     " ZBUNDLENAME, ZPROCNAME) VALUES (?,?,?,?,?)", [
        (1, T0, T0 + 1000, "com.example.video", "Video"),
        (2, T0, T0 + 500, None, "mediaserverd"),
        (3, T0, None, "com.example.quiet", "Quiet"),
        (4, None, None, None, None)])
    conn.executemany(
        "INSERT INTO ZLIVEUSAGE (ZHASPROCESS, ZWIFIIN, ZWIFIOUT, ZWWANIN, "
        "ZWWANOUT) VALUES (?,?,?,?,?)", [
            (1, 1000.0, 100.0, 5000.0, 50.0),
            (1, 2000.0, 200.0, 0.0, 0.0),          # more rows, same app
            (2, 10.0, 0.0, 10.0, 0.0),
            (99, 5.0, 5.0, 5.0, 5.0)])             # belongs to no process
    conn.commit()


def backup_files(wifi=True, old=False, bluetooth=True, usage=True):
    files = []
    if wifi:
        files.append(("SystemPreferencesDomain", WIFI_KNOWN, wifi_known()))
    if old:
        files.append(("SystemPreferencesDomain", WIFI_OLD, wifi_old()))
    if bluetooth:
        files += [(BT_DOMAIN, BT_CLASSIC, bluetooth_classic()),
                  (BT_DOMAIN, BT_PAIRED, database_bytes(build_paired)),
                  (BT_DOMAIN, BT_OTHER, database_bytes(build_other))]
    if usage:
        files.append(("WirelessDomain", USAGE, database_bytes(build_usage)))
    return files
