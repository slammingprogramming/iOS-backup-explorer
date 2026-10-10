# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — Wi-Fi, Bluetooth and data usage
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

"""Reads what the phone remembers about networks: the Wi-Fi networks it
has joined, the Bluetooth devices it knows, and how much data each app
used over Wi-Fi and the mobile network. No GUI.

The files are small property lists and databases scattered over several
folders of the backup; the tab copies them side by side and the functions
here look them up by name in that one folder.
"""

import os
import plistlib

from .common import apple_time, format_datetime, unix_time
from .records import Column, Dataset, open_copies, sqlite_rows

WIFI_KNOWN = "SystemPreferencesDomain/com.apple.wifi.known-networks.plist"
WIFI_OLD = "SystemPreferencesDomain/SystemConfiguration/com.apple.wifi.plist"
BLUETOOTH_CLASSIC = ("SysSharedContainerDomain-systemgroup.com.apple."
                     "bluetooth/Library/Preferences/"
                     "com.apple.MobileBluetooth.devices.plist")
_BT_DATABASES = ("SysSharedContainerDomain-systemgroup.com.apple.bluetooth/"
                 "Library/Database/com.apple.MobileBluetooth.ledevices.")
BLUETOOTH_PAIRED = _BT_DATABASES + "paired.db"
BLUETOOTH_OTHER = _BT_DATABASES + "other.db"
DATA_USAGE = "WirelessDomain/Library/Databases/DataUsage.sqlite"

# the databases first: the first that exists is the one the tab opens
SOURCES = (DATA_USAGE, BLUETOOTH_PAIRED, BLUETOOTH_OTHER, WIFI_KNOWN,
           WIFI_OLD, BLUETOOTH_CLASSIC)


def discover(index):
    """The files of the backup that this tab reads (backup paths)."""
    found = []
    for path in SOURCES:
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            found.append(path)
    return found


def read_plist(path):
    """The property list at *path* as Python values, or None."""
    try:
        with open(path, "rb") as handle:
            return plistlib.load(handle)
    except Exception:       # a damaged file of any kind is just not shown
        return None


def _text(value):
    """A name that may come as bytes (an SSID is, in newer lists)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace").strip()
    return value.strip() if isinstance(value, str) else ""


# ── Wi-Fi ────────────────────────────────────────────────────

def _place(networks):
    """``"12.3456, 65.4321"`` for the most recent place a network's access
    points were seen at, or ``""``."""
    best = None
    for bss in networks or ():
        if not isinstance(bss, dict):
            continue
        lat, lon = bss.get("LocationLatitude"), bss.get("LocationLongitude")
        if not isinstance(lat, (int, float)) \
                or not isinstance(lon, (int, float)):
            continue
        when = unix_time(bss.get("LocationTimestamp")) or 0
        if best is None or when >= best[0]:
            best = (when, lat, lon, bss.get("LocationAccuracy"))
    if best is None:
        return ""
    text = f"{best[1]:.5f}, {best[2]:.5f}"
    if isinstance(best[3], (int, float)) and best[3] > 0:
        text += f" (within {best[3]:.0f} m)"
    return text


def wifi_rows(folder):
    """The Wi-Fi networks, from the current list or (older iOS) the old one."""
    rows = []
    current = read_plist(os.path.join(folder, os.path.basename(WIFI_KNOWN)))
    if isinstance(current, dict):
        for key, item in current.items():
            if not isinstance(item, dict):
                continue
            extra = item.get("__OSSpecific__")
            extra = extra if isinstance(extra, dict) else {}
            name = _text(item.get("SSID")) or _text(item.get("SSID_STR")) \
                or str(key).split("wifi.network.ssid.", 1)[-1]
            access = [b for b in item.get("BSSList") or ()
                      if isinstance(b, dict)]
            rows.append({
                "network": name,
                "security": _text(item.get("SupportedSecurityTypes")),
                "added": unix_time(item.get("AddedAt")),
                "joined": unix_time(item.get("JoinedByUserAt"))
                or unix_time(extra.get("prevJoined")),
                "seen": unix_time(item.get("LastDiscoveredAt")),
                "hidden": "hidden" if item.get("Hidden") else "",
                "carplay": bool(item.get("CarPlayNetwork")),
                "router": _text(extra.get("BSSID"))
                or _text((access[0].get("BSSID") if access else "")),
                "channel": extra.get("CHANNEL")
                if isinstance(extra.get("CHANNEL"), int) else None,
                "access_points": len(access),
                "place": _place(access),
            })
    old = read_plist(os.path.join(folder, os.path.basename(WIFI_OLD)))
    if isinstance(old, dict):
        for item in old.get("List of known networks") or ():
            if not isinstance(item, dict):
                continue
            rows.append({
                "network": _text(item.get("SSID_STR"))
                or _text(item.get("SSID")),
                "security": _text(item.get("SecurityMode")),
                "added": unix_time(item.get("added"))
                or unix_time(item.get("AddedAt")),
                "joined": unix_time(item.get("lastJoined")),
                "seen": unix_time(item.get("lastAutoJoined")),
                "hidden": "hidden" if item.get("HIDDEN_NETWORK") else "",
                "carplay": False,
                "router": _text(item.get("BSSID")),
                "channel": item.get("CHANNEL")
                if isinstance(item.get("CHANNEL"), int) else None,
                "access_points": 0, "place": "",
            })
    return [r for r in rows if r["network"]]


def _wifi_details(row):
    lines = [row["network"]]
    for label, text in (
            ("Security", row["security"]),
            ("Added", format_datetime(row["added"])),
            ("Last joined by you", format_datetime(row["joined"])),
            ("Last in range", format_datetime(row["seen"])),
            ("Router", row["router"]),
            ("Channel", str(row["channel"]) if row["channel"] else ""),
            ("Access points known", str(row["access_points"] or "")),
            ("Last known place", row["place"])):
        if text:
            lines.append(f"{label}: {text}")
    if row["hidden"]:
        lines.append("A hidden network")
    if row["carplay"]:
        lines.append("Also used by CarPlay")
    return "\n".join(lines)


# ── Bluetooth ────────────────────────────────────────────────

def bluetooth_rows(folder, conns):
    """The Bluetooth devices: the classic ones from the property list and
    the low-energy ones from the two databases (*conns* maps their backup
    paths to connections or None)."""
    rows = []
    classic = read_plist(os.path.join(
        folder, os.path.basename(BLUETOOTH_CLASSIC)))
    if isinstance(classic, dict):
        for address, item in classic.items():
            if not isinstance(item, dict):
                continue
            name = _text(item.get("Name")) or _text(item.get("DefaultName")) \
                or _text(item.get("UserNameKey"))
            seen = item.get("LastSeenTime")
            rows.append({
                "name": name or "(no name)", "address": str(address),
                "kind": "Paired (classic)",
                "seen": float(seen) if isinstance(seen, int)
                and not isinstance(seen, bool) and seen > 0 else None})
    for path, table, kind in ((BLUETOOTH_PAIRED, "PairedDevices",
                               "Paired (low energy)"),
                              (BLUETOOTH_OTHER, "OtherDevices",
                               "Seen nearby (low energy)")):
        conn = conns.get(path)
        if conn is None:
            continue
        for name, address, resolved in sqlite_rows(
                conn, f"SELECT Name, Address, ResolvedAddress FROM {table}"):
            rows.append({"name": _text(name) or "(no name)",
                         "address": _text(address) or _text(resolved),
                         "kind": kind, "seen": None})
    return rows


# ── Data usage ───────────────────────────────────────────────

def usage_rows(conn):
    """How much each app and process sent and received (bytes)."""
    rows = []
    for (proc, bundle, first, last, wifi_in, wifi_out, cell_in,
         cell_out) in sqlite_rows(conn, """
            SELECT p.ZPROCNAME, p.ZBUNDLENAME, p.ZFIRSTTIMESTAMP,
                   p.ZTIMESTAMP, SUM(l.ZWIFIIN), SUM(l.ZWIFIOUT),
                   SUM(l.ZWWANIN), SUM(l.ZWWANOUT)
            FROM ZPROCESS p LEFT JOIN ZLIVEUSAGE l ON l.ZHASPROCESS = p.Z_PK
            GROUP BY p.Z_PK"""):
        numbers = [int(v or 0) for v in (wifi_in, wifi_out, cell_in,
                                         cell_out)]
        rows.append({
            "app": (bundle or proc or "(unknown)").strip(),
            "process": (proc or "").strip(),
            "wifi_in": numbers[0], "wifi_out": numbers[1],
            "cell_in": numbers[2], "cell_out": numbers[3],
            "total": sum(numbers),
            "first": apple_time(first) if first else None,
            "last": apple_time(last) if last else None})
    return rows


def _usage_note(rows):
    from .export_util import describe_size
    wifi = sum(r["wifi_in"] + r["wifi_out"] for r in rows)
    cell = sum(r["cell_in"] + r["cell_out"] for r in rows)
    return (f"All together: {describe_size(wifi)} over Wi-Fi and "
            f"{describe_size(cell)} over the mobile network, as counted by "
            "the phone since it last cleared its statistics.")


def datasets(conn, index):
    folder = os.path.dirname(conn.execute("PRAGMA database_list").fetchone()[2])
    paths = [p for p in (BLUETOOTH_PAIRED, BLUETOOTH_OTHER, DATA_USAGE)
             if index is not None and index.get(p) is not None]
    result = []
    with open_copies(conn, paths) as conns:
        networks = wifi_rows(folder)
        devices = bluetooth_rows(folder, conns)
        usage = usage_rows(conns[DATA_USAGE]) if conns.get(DATA_USAGE) \
            else []
    if networks:
        result.append(Dataset(
            "wifi", "Wi-Fi networks", [
                Column("network", "Network", 240),
                Column("security", "Security", 110),
                Column("joined", "Last joined", 130, "date"),
                Column("seen", "Last in range", 130, "date"),
                Column("added", "Added", 130, "date"),
                Column("hidden", "", 60)],
            networks, sort=("joined", True), details=_wifi_details,
            note="Joined networks the phone remembers. Passwords are kept "
                 "in the keychain and are not shown."))
    if devices:
        result.append(Dataset(
            "bluetooth", "Bluetooth devices", [
                Column("name", "Name", 260),
                Column("kind", "Kind", 170),
                Column("address", "Address", 170),
                Column("seen", "Last seen", 130, "date")],
            devices, sort=("name", False)))
    if usage:
        result.append(Dataset(
            "usage", "Data used by apps", [
                Column("app", "App", 300),
                Column("wifi_in", "Wi-Fi received", 110, "size", "e"),
                Column("wifi_out", "Wi-Fi sent", 100, "size", "e"),
                Column("cell_in", "Mobile received", 110, "size", "e"),
                Column("cell_out", "Mobile sent", 100, "size", "e"),
                Column("last", "Last used", 130, "date")],
            usage, sort=("total", True), note=_usage_note(usage),
            details=lambda r: (f"{r['app']}\nProcess: {r['process']}"
                               if r["process"] and r["process"] != r["app"]
                               else r["app"])))
    return result


class NetworkReader:
    def __init__(self, conn, index):
        self.conn, self.index = conn, index

    def datasets(self):
        return datasets(self.conn, self.index)
