# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake Screen Time files for tests. Everything here is invented."""

import plistlib
from datetime import datetime, timedelta

BASE = ("Library/com.apple.DeviceActivity/Cloud/"
        "000654-08-aaaaaaaa-0000-0000-0000-000000000000")
DEVICE_A = "DD5B9B00-0000-0000-0000-000000000001"
DEVICE_B = "EE6C0C11-0000-0000-0000-000000000002"
DOMAIN = "SysSharedContainerDomain-systemgroup.com.apple.DeviceActivity"

APPLE0 = datetime(2001, 1, 1)
# days start at local midnight where the phone was: UTC-4
DAY1 = datetime(2025, 3, 3, 4, 0)
DAY2 = DAY1 + timedelta(days=1)
DAY3 = DAY1 + timedelta(days=2)
WEEK = DAY1


def cocoa(moment):
    return (moment - APPLE0).total_seconds()


def activity(bundle, seconds, pickups=0, notifications=0):
    return {"bundleIdentifier": bundle, "totalActivityDuration": seconds,
            "numberOfPickups": pickups, "numberOfNotifications": notifications,
            "isTrusted": True}


def record(start, length, total, apps=(), sites=(), pickups_extra=0,
           first_pickup=None):
    value = {
        "recordZoneName": "zone", "totalActivityDuration": float(total),
        "totalPickupsWithoutApplicationActivity": pickups_extra,
        "dateInterval": {"start": start, "duration": float(length)},
        "categoryActivities": [{
            "identifier": "DH1002", "totalActivityDuration": float(total),
            "applicationActivities": list(apps),
            "webDomainActivities": [
                {"domain": d, "totalActivityDuration": float(t),
                 "isTrusted": True} for d, t in sites]},
            {"identifier": "DH1005", "totalActivityDuration": 0.0,
             "applicationActivities": [], "webDomainActivities": []}]}
    if first_pickup is not None:
        value["firstPickup"] = first_pickup
    return plistlib.dumps({"value": value}, fmt=plistlib.FMT_BINARY)


def path(device, kind, start):
    return f"{BASE}/{device}/{kind}/ActivitySegments/{cocoa(start)}.plist"


def backup_files(second_device=False, hours=3, broken=True):
    files = []

    def add(device, kind, start, data):
        files.append((DOMAIN, path(device, kind, start), data))

    add(DEVICE_A, "Daily", DAY1, record(DAY1, 86400, 3600, [
        activity("com.apple.mobilesafari", 2000, 5, 3),
        activity("com.example.game", 1000, 2, 0),
        activity("com.apple.MobileSMS", 600, 4, 10)],
        [("example.com", 300), ("news.example.org", 100)],
        pickups_extra=3))
    add(DEVICE_A, "Daily", DAY2, record(DAY2, 86400, 7200, [
        activity("com.apple.mobilesafari", 5000, 8, 1),
        activity("com.example.game", 2000, 1, 0)],
        [("example.com", 700)], pickups_extra=1))
    add(DEVICE_A, "Daily", DAY3, record(DAY3, 86400, 0))     # unused day
    add(DEVICE_A, "Weekly", WEEK, record(
        WEEK, 604800, 10800, [activity("com.apple.mobilesafari", 7000, 13,
                                       4)], pickups_extra=4,
        first_pickup=DAY1 + timedelta(hours=8)))
    for hour in range(hours):
        start = DAY1 + timedelta(hours=hour)
        add(DEVICE_A, "Hourly", start, record(
            start, 3600, 600 * (hour + 1),
            [activity("com.apple.mobilesafari", 600 * (hour + 1), hour + 1,
                      0)], first_pickup=start + timedelta(minutes=5)))
    if second_device:
        add(DEVICE_B, "Daily", DAY1, record(DAY1, 86400, 500, [
            activity("com.example.tablet", 500, 1, 0)]))
    if broken:
        files.append((DOMAIN, f"{BASE}/{DEVICE_A}/Daily/ActivitySegments/"
                      f"{cocoa(DAY1 + timedelta(days=9))}.plist",
                      b"not a property list"))
        files.append((DOMAIN, f"{BASE}/{DEVICE_A}/Daily/ActivitySegments/"
                      "notes.txt", b"x"))
        files.append((DOMAIN, f"{BASE}/{DEVICE_A}/Daily/ActivitySegments/"
                      f"{cocoa(DAY1 + timedelta(days=10))}.plist",
                      plistlib.dumps({"value": {"nothing": 1}})))
    return files
