# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — app permissions
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Reads the permissions apps were given or refused (``TCC.db``): photos,
camera, microphone, contacts, the local network, tracking and so on. No
GUI.

The meaning of the numbers is the one the system documents: an access of 2
is allowed, 0 refused, 3 limited, 1 not decided.
"""

import os
import plistlib
import re

from .common import apple_time, format_datetime
from .records import Column, Dataset, sqlite_rows

DATABASE = "HomeDomain/Library/TCC/TCC.db"
LOCATION = "RootDomain/Library/Caches/locationd/clients.plist"
SOURCES = (DATABASE, LOCATION)
LOCATION_ACCESS = {0: "Not decided", 1: "Restricted", 2: "Never",
                   3: "Always", 4: "While using the app"}

SERVICES = {
    "Photos": "Photos", "PhotosAdd": "Add to Photos", "Camera": "Camera",
    "Microphone": "Microphone", "AddressBook": "Contacts",
    "Calendar": "Calendars", "Reminders": "Reminders",
    "MediaLibrary": "Media and Apple Music", "Motion": "Motion and fitness",
    "Liverpool": "Local network", "Ubiquity": "iCloud",
    "UserTracking": "Tracking", "FocusStatus": "Focus status",
    "BluetoothAlways": "Bluetooth", "SpeechRecognition": "Speech recognition",
    "Siri": "Siri", "FaceID": "Face ID", "Willow": "Home",
    "HealthKit": "Health", "Location": "Location",
    "ListenEvent": "Input monitoring", "ScreenCapture": "Screen recording",
    "WebKitIntelligentTrackingPrevention": "Cross-site tracking prevention",
    "ContactsLimited": "Limited contacts", "Nearby": "Nearby interactions",
    "SensorKitMotion": "Sensor data"}
ACCESS = {0: "Refused", 1: "Not decided", 2: "Allowed", 3: "Limited"}
REASONS = {
    1: "error", 2: "answered the prompt", 3: "set in Settings",
    4: "set by the system", 5: "by the service's policy",
    6: "by a management profile", 7: "by an override",
    8: "app has no usage description", 9: "the prompt timed out",
    10: "not asked yet", 11: "by the app's entitlement",
    12: "by the kind of app"}


def discover(index):
    """The files this tab reads (backup paths), the permissions database
    first."""
    found = []
    for path in SOURCES:
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            found.append(path)
    return found


def service_label(service):
    key = re.sub(r"^kTCCService", "", service or "")
    if key in SERVICES:
        return SERVICES[key]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key).strip()
    return words[:1].upper() + words[1:].lower() if words else service or ""


def rows(conn):
    result = []
    for (service, client, kind, value, reason, changed) in sqlite_rows(
            conn, "SELECT service, client, client_type, auth_value, "
                  "auth_reason, last_modified FROM access"):
        result.append({
            "permission": service_label(service), "service": service or "",
            "app": client or "", "path": kind == 1,
            "access": ACCESS.get(value, f"Value {value}"),
            "how": REASONS.get(reason, ""),
            "changed": float(changed) if isinstance(changed, (int, float))
            and changed > 0 else None})
    return result


def _details(row):
    lines = [row["app"], f"{row['permission']}: {row['access']}"]
    if row["how"]:
        lines.append(f"Set: {row['how']}")
    if row["changed"]:
        lines.append(format_datetime(row["changed"]))
    lines.append(row["service"])
    return "\n".join(line for line in lines if line)


def datasets(conn):
    data = rows(conn)
    if not data:
        return []
    return [Dataset("permissions", "Permissions", [
        Column("app", "App", 300), Column("permission", "Permission", 200),
        Column("access", "Access", 100), Column("how", "How", 200),
        Column("changed", "Changed", 130, "date")],
        data, sort=("app", False), details=_details,
        note="Which apps may use what. The location has a table of its own.")]


def location_rows(folder):
    """The apps and system parts that asked for the location, from the
    location service's own list."""
    try:
        with open(os.path.join(folder, os.path.basename(LOCATION)),
                  "rb") as handle:
            clients = plistlib.load(handle)
    except Exception:             # not there, or not a property list
        return []
    if not isinstance(clients, dict):
        return []
    result = []
    for key, item in clients.items():
        if not isinstance(item, dict):
            continue
        system = str(key).startswith("com.apple.locationd.")
        access = item.get("Authorization")
        stopped = item.get("LocationTimeStopped")
        name = str(key)
        if system:                 # ...executable-/usr/libexec/name
            name = os.path.basename(name.split("-", 1)[-1].rstrip("/"))
        result.append({
            "app": name, "kind": "System" if system else "App",
            "access": LOCATION_ACCESS.get(access, f"Value {access}")
            if isinstance(access, int) else "Not set",
            "last": apple_time(stopped)
            if isinstance(stopped, (int, float)) and stopped else None})
    return result


def location_datasets(folder):
    data = location_rows(folder)
    if not data:
        return []
    return [Dataset("location", "Location services", [
        Column("app", "App or service", 320), Column("kind", "Kind", 70),
        Column("access", "Access", 160),
        Column("last", "Last used", 130, "date")],
        data, sort=("app", False),
        note="Which apps may use the location. The dates are when the "
             "phone last stopped giving an app its location.")]


class PrivacyReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        own = self.conn.execute("PRAGMA database_list").fetchone()[2]
        folder = os.path.dirname(own)
        found = [] if own.lower().endswith(".plist") else datasets(self.conn)
        return found + location_datasets(folder)
