# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""An invented device and invented backups, for the pictures of the
"Devices & backups" window. Nothing here touches a real device or lists a
real backup: the window is given these instead of the computer's own.

The backups are tiny folders (a few property lists and files) made with the
same layout the program reads; the sizes shown in the pictures are invented
too (``SIZES``), because a real backup is many gigabytes."""

import datetime
import os
import plistlib
import sqlite3

import device_tools as dt

UDID = "00008130-000A1B2C3D4E5F60"

BACKUPS = (
    # folder name, device, model, iOS, build, encrypted, finished, made
    ("00008130-000A1B2C3D4E5F60", "Taylor's iPhone", "iPhone15,4", "18.5",
     "22F76", False, True, datetime.datetime(2026, 10, 9, 18, 30),
     "Finder"),
    ("00008020-001C2D3E4F506172", "Alex's iPad", "iPad13,18", "17.7.2",
     "21H221", True, True, datetime.datetime(2026, 9, 28, 21, 5),
     "iOS Backup Explorer"),
    ("a1b2c3d4e5f60718293a4b5c6d7e8f9012345678", "Taylor's old iPhone",
     "iPhone10,4", "16.7.10", "20H350", True, False,
     datetime.datetime(2026, 6, 2, 9, 40), "Added by you"),
)

SIZES = {  # bytes, as a phone's backup would be
    "Taylor's iPhone": 48_300_000_000,
    "Alex's iPad": 21_700_000_000,
    "Taylor's old iPhone": 9_400_000_000,
}


def _plist(path, data):
    with open(path, "wb") as handle:
        plistlib.dump(data, handle)


def make_backups(root):
    """Make the invented backups under *root* (one folder for each place
    that "keeps" them) and return ``[(folder, who keeps them)]``."""
    places = {}
    for (name, device, model, version, build, encrypted, finished, made,
         who) in BACKUPS:
        folder_for_who = places.setdefault(who, os.path.join(
            root, who.replace(" ", "-").lower()))
        backup = os.path.join(folder_for_who, name)
        os.makedirs(backup)
        _plist(os.path.join(backup, "Info.plist"), {
            "Device Name": device, "Product Type": model,
            "Product Version": version, "Build Version": build,
            "Unique Identifier": name, "Last Backup Date": made})
        _plist(os.path.join(backup, "Manifest.plist"), {
            "IsEncrypted": encrypted, "Date": made, "Version": "10.0"})
        _plist(os.path.join(backup, "Status.plist"), {
            "IsFullBackup": True, "Date": made,
            "SnapshotState": "finished" if finished else "new"})
        conn = sqlite3.connect(os.path.join(backup, "Manifest.db"))
        conn.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain "
                     "TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
        conn.commit()
        conn.close()
    return [(folder, who) for who, folder in places.items()]


class DemoRun:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True

    def wait(self, timeout=None):
        return True


class DemoToolbox:
    """A toolbox with one invented, trusted iPhone on the cable. A backup
    it "starts" never finishes by itself: the picture is of one underway."""

    missing = []
    can_list = True
    can_backup = True

    def has(self, name):
        return True

    def devices(self):
        return [UDID]

    def pairing(self, udid):
        return dt.PAIRED

    def info(self, udid):
        return dt.DeviceInfo(
            udid=udid, name="Taylor's iPhone", model="iPhone15,4",
            product="iPhone OS", version="18.5", build="22F76",
            serial="DEMO0SERIAL", passcode_set=True,
            storage_total=128_000_000_000, storage_free=47_000_000_000,
            battery=82, encrypts_backups=False)

    def start_backup(self, udid, folder, full=False, **callbacks):
        for line in ("Starting backup...", "Backup will be unencrypted.",
                     "Incremental backup mode.",
                     "Received 3,412 files from device."):
            callbacks["on_line"](line)
        callbacks["on_progress"](46.0)
        return DemoRun()
