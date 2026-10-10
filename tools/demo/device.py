# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""What the demo phone knows about itself: networks, accounts, permissions,
apps, Screen Time, iCloud Drive and the device information."""

import plistlib
import random
from datetime import datetime, timedelta

from . import NOW, ago, clone_schema, cocoa, unix

HOME = "HomeDomain"


def _naive(moment):
    return moment.replace(tzinfo=None)


# ── Device information ───────────────────────────────────────

def information(writer):
    writer.file_at_root("Info.plist", plistlib.dumps({
        "Device Name": "Taylor's iPhone", "Display Name": "Taylor's iPhone",
        "Product Name": "iPhone 15", "Product Type": "iPhone15,4",
        "Product Version": "18.5", "Build Version": "22F76",
        "Serial Number": "DEMO0SERIAL", "Unique Identifier": "DEMO" * 10,
        "IMEI": "000000000000000", "Phone Number": "+1 555 010 0100",
        "Last Backup Date": _naive(NOW)}))
    writer.file_at_root("Status.plist", plistlib.dumps(
        {"IsFullBackup": True, "Version": "3.3"}))
    writer.file("SystemPreferencesDomain",
                "SystemConfiguration/preferences.plist", plistlib.dumps({
                    "Root": {"System": {"ComputerName": "Taylor's iPhone",
                                        "HostName": "Taylors-iPhone"},
                             "Network": {"HostNames": {
                                 "LocalHostName": "Taylors-iPhone"}}}}))


# ── Network ──────────────────────────────────────────────────

WIFI = [
    ("Maple Street WiFi", "WPA3 Personal", 5, 0.1, False, False,
     (39.7990, -89.6440)),
    ("Cafe Aroma Guest", "Open", 12, 2, False, False, (39.7817, -89.6501)),
    ("Springfield Airport Free WiFi", "Open", 200, 160, False, False, None),
    ("Orchard Lane", "WPA2 Personal", 90, 30, False, False,
     (39.6125, -89.2340)),
    ("Hotel Lisboa Guest", "WPA2 Personal", 150, 140, False, False, None),
    ("Taylor's iPhone", "WPA2 Personal", 300, 280, True, False, None),
    ("Office-Secure", "WPA2 Enterprise", 120, 1, False, False,
     (39.7790, -89.6550)),
    ("CarPlay Link", "WPA2 Personal", 250, 100, False, True, None),
]
BLUETOOTH = [("Taylor's AirPods Pro", "Paired (classic)", 2),
             ("Car Audio", "Paired (classic)", 20),
             ("Kitchen Speaker", "Paired (classic)", 45),
             ("Keyboard K380", "Paired (classic)", 120)]


def network(writer):
    from tests import fixture_network as fn
    networks = {}
    for name, security, added, joined, hidden, carplay, place in WIFI:
        item = {"SSID": name.encode("utf-8"),
                "SupportedSecurityTypes": security,
                "AddedAt": _naive(ago(days=added + 30)),
                "LastDiscoveredAt": _naive(ago(days=joined)),
                "Hidden": hidden, "CarPlayNetwork": carplay,
                "__OSSpecific__": {"CHANNEL": 36,
                                   "BSSID": "02:00:00:00:00:%02x" % added},
                "JoinedByUserAt": _naive(ago(days=joined, hours=2))}
        if place:
            item["BSSList"] = [{
                "BSSID": "02:00:00:00:00:%02x" % added,
                "LocationLatitude": place[0], "LocationLongitude": place[1],
                "LocationAccuracy": 35.0,
                "LocationTimestamp": _naive(ago(days=joined))}]
        networks[f"wifi.network.ssid.{name}"] = item
    writer.file("SystemPreferencesDomain",
                "com.apple.wifi.known-networks.plist",
                plistlib.dumps(networks))

    classic = {}
    for number, (name, _kind, days) in enumerate(BLUETOOTH):
        classic["7C:F3:00:00:00:%02X" % number] = {
            "Name": name, "LastSeenTime": int(unix(ago(days=days)))}
    domain = fn.BT_DOMAIN
    writer.file(domain, fn.BT_CLASSIC, plistlib.dumps(classic))

    def paired(conn):
        clone_schema(fn.build_paired, conn)
        conn.execute("INSERT INTO PairedDevices VALUES ('u1', 'Fitness "
                     "Watch', 2, '11:11:11:11:11:11', "
                     "'22:22:22:22:22:22', 45139, 248)")

    def other(conn):
        clone_schema(fn.build_other, conn)
        rng = random.Random(3)
        names = ["TV 55", "BLE Beacon %d", "Fitness Band", "Smart Lock",
                 "Thermostat", "Headphones %d", "Phone %d", "Tag %d",
                 "Speaker %d"]
        for number in range(26):
            name = names[number % len(names)]
            name = name % rng.randrange(10, 99) if "%d" in name else name
            conn.execute("INSERT INTO OtherDevices VALUES (?, ?, 0, ?, '', "
                         "?, 0)", (f"u{number}", name,
                                   "33:33:%02X" % number,
                                   rng.randrange(200, 40000)))

    writer.database(domain, fn.BT_PAIRED, paired)
    writer.database(domain, fn.BT_OTHER, other)

    apps = [("com.apple.mobilesafari", "MobileSafari", 900, 120, 3400, 410),
            ("com.apple.MobileSMS", "MobileSMS", 320, 150, 1900, 880),
            ("com.apple.mobilemail", "MobileMail", 540, 60, 2400, 340),
            ("com.apple.Maps", "Maps", 1500, 200, 4200, 700),
            ("com.apple.Music", "Music", 3100, 20, 9800, 90),
            ("com.apple.podcasts", "Podcasts", 2200, 10, 7400, 40),
            ("com.apple.mobileslideshow", "photolibraryd", 5200, 3800, 1200,
             900),
            ("com.example.video", "Video", 8800, 300, 21000, 800),
            ("com.example.chat", "Chat", 640, 380, 1500, 900),
            ("com.example.social", "Social", 2900, 410, 7200, 1300),
            ("com.example.maps", "TrailMaps", 1800, 190, 3100, 400),
            ("com.apple.AppStore", "appstored", 4100, 90, 2300, 120),
            ("com.apple.weather", "Weather", 90, 5, 260, 20),
            ("com.apple.news", "News", 710, 20, 1900, 60),
            (None, "mediaserverd", 120, 1, 640, 3),
            (None, "apsd", 40, 30, 90, 70)]

    def usage(conn):
        clone_schema(fn.build_usage, conn)
        for pk, (bundle, process, wifi_in, wifi_out, cell_in,
                 cell_out) in enumerate(apps, 1):
            conn.execute(
                "INSERT INTO ZPROCESS (Z_PK, ZFIRSTTIMESTAMP, ZTIMESTAMP, "
                "ZBUNDLENAME, ZPROCNAME) VALUES (?,?,?,?,?)",
                (pk, cocoa(ago(days=200)), cocoa(ago(days=pk % 5)),
                 bundle, process))
            for part in range(3):
                conn.execute(
                    "INSERT INTO ZLIVEUSAGE (ZHASPROCESS, ZWIFIIN, ZWIFIOUT,"
                    " ZWWANIN, ZWWANOUT) VALUES (?,?,?,?,?)",
                    (pk, wifi_in * 1_000_000.0, wifi_out * 1_000_000.0,
                     cell_in * 100_000.0, cell_out * 100_000.0))
    writer.database("WirelessDomain", fn.USAGE, usage)


# ── Accounts ─────────────────────────────────────────────────

def accounts(writer):
    from tests import fixture_accounts as fa

    def build(conn):
        clone_schema(fa.build, conn)
        conn.executemany("INSERT INTO ZACCOUNTTYPE VALUES (?, ?)", [
            (1, "iCloud"), (2, "Google"), (3, "Exchange"),
            (4, "CalDAV"), (5, "Game Center"), (6, "Apple ID")])
        d0 = cocoa(ago(days=900))
        conn.executemany("INSERT INTO ZACCOUNT VALUES (?,?,?,?,?,?,?,?,?)", [
            (1, 1, 1, 1, None, d0, "iCloud", "taylor.morgan@example.com",
             "com.apple.purplebuddy"),
            (2, 1, 1, 6, None, d0, "Apple ID", "taylor.morgan@example.com",
             "com.apple.AuthKit"),
            (3, 1, 1, 2, None, d0 + 1e7, "Personal", "taylor.m@example.org",
             "com.apple.accounts.accountsd"),
            (4, 1, 1, 3, None, d0 + 2e7, "Work Mail",
             "taylor.morgan@work.example.com",
             "com.apple.accounts.accountsd"),
            (5, 1, 1, 4, 1, d0 + 1, "Calendar", None,
             "com.apple.accounts.accountsd"),
            (6, 1, 1, 5, None, d0 + 3e7, "Game Center", "taylor_m",
             "com.apple.purplebuddy"),
            (7, 0, 0, 2, 3, d0 + 4e7, "Contacts", None,
             "com.apple.accounts.accountsd")])
        services = ["Mail", "Contacts", "Calendars", "Reminders", "Notes",
                    "Photos", "Keychain", "Backup"]
        for number, name in enumerate(services, 1):
            conn.execute("INSERT INTO ZDATACLASS VALUES (?, ?)",
                         (number, f"com.apple.Dataclass.{name}".encode()))
        pairs = [(1, n) for n in range(1, 9)] + [(3, 1), (3, 2), (3, 3),
                                                 (4, 1), (4, 2), (4, 3)]
        conn.executemany("INSERT INTO Z_2ENABLEDDATACLASSES VALUES (?, ?)",
                         pairs)
    writer.database(HOME, fa.ACCOUNTS, build)


# ── Permissions and apps ─────────────────────────────────────

def privacy(writer):
    from tests import fixture_small_tabs as fx

    def build(conn):
        clone_schema(fx.build_privacy, conn)
        rows = [
            ("kTCCServicePhotos", "com.example.chat", 2, 2, 20),
            ("kTCCServicePhotos", "com.example.social", 3, 2, 12),
            ("kTCCServiceCamera", "com.example.chat", 2, 2, 20),
            ("kTCCServiceCamera", "com.example.social", 0, 2, 12),
            ("kTCCServiceMicrophone", "com.example.chat", 2, 2, 20),
            ("kTCCServiceMicrophone", "com.example.video", 0, 2, 40),
            ("kTCCServiceAddressBook", "com.example.chat", 0, 2, 20),
            ("kTCCServiceAddressBook", "com.example.social", 0, 3, 5),
            ("kTCCServiceLiverpool", "com.example.maps", 2, 2, 60),
            ("kTCCServiceLiverpool", "com.example.video", 0, 2, 40),
            ("kTCCServiceUserTracking", "com.example.social", 0, 2, 12),
            ("kTCCServiceUserTracking", "com.example.video", 0, 2, 40),
            ("kTCCServiceMotion", "com.example.maps", 2, 2, 60),
            ("kTCCServiceBluetoothAlways", "com.example.maps", 2, 2, 60),
            ("kTCCServiceUbiquity", "com.apple.mobilenotes", 2, 4, 400),
            ("kTCCServiceReminders", "com.example.chat", 0, 2, 20)]
        for service, client, value, reason, days in rows:
            conn.execute(
                "INSERT INTO access (service, client, client_type, "
                "auth_value, auth_reason, last_modified) "
                "VALUES (?,?,0,?,?,?)",
                (service, client, value, reason, int(unix(ago(days=days)))))
    writer.database(HOME, "Library/TCC/TCC.db", build)

    def level(authorization, days):
        item = {"Authorization": authorization, "Registered": True}
        if days is not None:
            item["LocationTimeStopped"] = cocoa(ago(days=days))
        return item

    writer.file("RootDomain", "Library/Caches/locationd/clients.plist",
                plistlib.dumps({
                    "com.apple.Maps": level(4, 0),
                    "com.apple.camera": level(4, 3),
                    "com.apple.weather": level(3, 1),
                    "com.apple.findmy": level(3, 0),
                    "com.example.maps": level(4, 2),
                    "com.example.social": level(2, None),
                    "com.example.video": level(0, None),
                    "com.apple.locationd.executable-/usr/libexec/"
                    "timezoneupdated": level(4, 6)}))


BUNDLES = ["com.apple.mobilesafari", "com.apple.MobileSMS",
           "com.apple.mobilephone", "com.apple.mobilemail", "com.apple.camera",
           "com.apple.mobileslideshow", "com.apple.Maps",
           "com.apple.mobilenotes", "com.apple.reminders",
           "com.apple.mobilecal", "com.apple.Music", "com.apple.podcasts",
           "com.apple.Health", "com.apple.Preferences", "com.apple.AppStore",
           "com.apple.facetime", "com.apple.weather", "com.apple.stocks",
           "com.apple.news", "com.apple.iBooks", "com.apple.tv",
           "com.apple.Passbook", "com.apple.calculator",
           "com.apple.mobiletimer", "com.apple.Fitness", "com.apple.findmy",
           "com.apple.shortcuts", "com.apple.DocumentsApp",
           "com.apple.VoiceMemos", "com.apple.compass", "com.apple.Translate",
           "com.apple.Home", "com.example.chat", "com.example.social",
           "com.example.video", "com.example.maps", "com.example.musicplayer",
           "com.example.bank", "com.example.notesplus", "com.example.photoedit"]


def apps(writer):
    from tests import fixture_small_tabs as fx

    def build(conn):
        clone_schema(fx.build_apps, conn)
        conn.execute("INSERT INTO key_tab VALUES (1, 'SBApplicationBadgeKey')")
        for number, bundle in enumerate(BUNDLES, 1):
            conn.execute("INSERT INTO application_identifier_tab VALUES "
                         "(?, ?)", (number, bundle))
        for bundle, badge in (("com.apple.MobileSMS", 2),
                              ("com.apple.mobilemail", 14),
                              ("com.example.chat", 5),
                              ("com.apple.AppStore", 1)):
            conn.execute(
                "INSERT INTO kvs (application_identifier, key, value) "
                "VALUES (?, 1, ?)", (BUNDLES.index(bundle) + 1, badge))
    writer.database(HOME, "Library/FrontBoard/applicationState.db", build)


def icloud_drive(writer):
    from tests import fixture_small_tabs as fx
    paths = []
    for name in ("Budget 2026.xlsx", "Tax documents 2025.pdf",
                 "Passport scan.pdf", "Lease agreement.pdf",
                 "Insurance policy.pdf", "Trip itinerary.pdf",
                 "Recipes.pages", "Meeting minutes.docx"):
        paths.append(f"Documents/{name}")
    for number in range(1, 9):
        paths.append(f"Documents/Receipts/2026-{number:02d} receipt.pdf")
    for number in range(1, 7):
        paths.append(f"Photos to print/IMG_{4000 + number}.jpg")
    for name in ("Plan.numbers", "Notes.txt", "Mood board.key"):
        paths.append(f"Projects/Garden redesign/{name}")
    for name in ("Chapter 1.pages", "Chapter 2.pages", "Outline.txt"):
        paths.append(f"Projects/Short story/{name}")
    paths += ["Downloads/installer.dmg", "Downloads/report.csv",
              "Shared/Family calendar.ics", "Shared/Holiday packing.pdf"]

    def build(conn):
        clone_schema(fx.build_icloud, conn)
        conn.executemany("INSERT INTO backup_manifest (relative_path) VALUES "
                         "(?)", [(p,) for p in paths])
    writer.database(HOME, "Library/Application Support/FileProvider/backup/"
                    "backup_manifest.db", build)


# ── Screen Time ──────────────────────────────────────────────

APPS = [("com.apple.mobilesafari", 5), ("com.apple.MobileSMS", 4),
        ("com.example.social", 6), ("com.example.video", 7),
        ("com.example.chat", 3), ("com.apple.mobilemail", 2),
        ("com.apple.Maps", 1), ("com.apple.Music", 2),
        ("com.apple.mobileslideshow", 1), ("com.apple.camera", .5),
        ("com.apple.news", 1), ("com.apple.mobilenotes", 1),
        ("com.example.musicplayer", 2), ("com.apple.podcasts", 1.5)]
SITES = ["example.org", "news.example.com", "recipes.example.org",
         "www.example.net", "docs.example.dev", "shop.example.com"]


def screen_time(writer):
    from tests import fixture_screentime as fs
    rng = random.Random(11)
    offset = timedelta(hours=5)          # (the phone's days begin at 05:00
    base = datetime(NOW.year, NOW.month, NOW.day)         # UTC: UTC-5)

    def day_record(start, length, scale):
        apps = []
        for bundle, weight in APPS:
            if rng.random() < .15:
                continue
            seconds = max(0.0, rng.gauss(weight * 650 * scale,
                                         weight * 250))
            if seconds > 20:
                apps.append(fs.activity(
                    bundle, round(seconds), rng.randrange(1, 9),
                    rng.randrange(0, 25)))
        sites = [(site, round(rng.gauss(500, 300) * scale))
                 for site in SITES if rng.random() < .6]
        sites = [(s, max(30, t)) for s, t in sites]
        total = sum(a["totalActivityDuration"] for a in apps) * .9
        return fs.record(start, length, total, apps, sites,
                         pickups_extra=rng.randrange(2, 12))

    def add(kind, start, data):
        writer.file(fs.DOMAIN, fs.path(fs.DEVICE_A, kind, start), data,
                    NOW)

    for days in range(60):
        start = base - timedelta(days=days) + offset
        weekend = (base - timedelta(days=days)).weekday() >= 5
        add("Daily", start, day_record(start, 86400, 1.25 if weekend
                                       else 1.0))
    sunday = base - timedelta(days=(base.weekday() + 1) % 7)
    for weeks in range(8):
        start = sunday - timedelta(weeks=weeks) + offset
        add("Weekly", start, day_record(start, 604800, 6.5))
    for hours in range(24 * 14):
        start = (NOW.replace(tzinfo=None, minute=0, second=0)
                 - timedelta(hours=hours))
        local = start - offset
        if not 7 <= local.hour <= 23 or rng.random() < .25:
            continue
        add("Hourly", start, day_record(start, 3600, .1))
