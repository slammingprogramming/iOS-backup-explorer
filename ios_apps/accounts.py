# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — accounts and facts about the device
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

"""Reads the accounts set up on the phone (``Accounts3.sqlite``: iCloud,
mail, calendars, and the services that sign in behind them) and what the
backup says about the device itself: the ``Info.plist``, ``Manifest.plist``
and ``Status.plist`` that a backup folder holds, and the computer name in
the phone's preferences. No GUI.

No password or key is read: the accounts database keeps those in the
keychain, not in the file.
"""

import os
import plistlib
import re

from .common import own_path, apple_time, format_datetime, unix_time
from .records import Column, Dataset, sqlite_rows

ACCOUNTS = "HomeDomain/Library/Accounts/Accounts3.sqlite"
PREFERENCES = "SystemPreferencesDomain/SystemConfiguration/preferences.plist"
SOURCES = (ACCOUNTS, PREFERENCES)

INFO_ITEMS = (
    ("Device name", "Device Name"), ("Model", "Product Name"),
    ("Model identifier", "Product Type"), ("iOS version", "Product Version"),
    ("Build", "Build Version"), ("Serial number", "Serial Number"),
    ("Identifier (UDID)", "Unique Identifier"), ("Phone number",
                                                 "Phone Number"),
    ("IMEI", "IMEI"), ("IMEI 2", "IMEI 2"), ("MEID", "MEID"),
    ("SIM (ICCID)", "ICCID"), ("Last backup", "Last Backup Date"),
    ("iTunes version", "iTunes Version"))
LOCKDOWN_ITEMS = (
    ("Device name", "DeviceName"), ("Model identifier", "ProductType"),
    ("iOS version", "ProductVersion"), ("Build", "BuildVersion"),
    ("Serial number", "SerialNumber"), ("Identifier (UDID)",
                                        "UniqueDeviceID"))


def discover(index):
    found = []
    for path in SOURCES:
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            found.append(path)
    return found


def read_plist(path):
    try:
        with open(path, "rb") as handle:
            return plistlib.load(handle)
    except Exception:         # damaged or not there: just not shown
        return None


def _shown(value):
    """A value of a property list as text, or ``""``."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if hasattr(value, "year"):
        return format_datetime(unix_time(value))
    return ""


def backup_info(folder):
    """``[(label, value), ...]`` from the plists of the backup *folder*
    (empty if it has none, as an extracted backup does not)."""
    info = {}
    if not folder:
        return []
    top = read_plist(os.path.join(folder, "Info.plist"))
    if isinstance(top, dict):
        for label, key in INFO_ITEMS:
            text = _shown(top.get(key))
            if text:
                info[label] = text
    manifest = read_plist(os.path.join(folder, "Manifest.plist"))
    if isinstance(manifest, dict):
        lock = manifest.get("Lockdown")
        if isinstance(lock, dict):
            for label, key in LOCKDOWN_ITEMS:
                text = _shown(lock.get(key))
                if text and label not in info:
                    info[label] = text
        for label, key in (("Backup made", "Date"),
                           ("Encrypted", "IsEncrypted"),
                           ("Passcode was set", "WasPasscodeSet")):
            text = _shown(manifest.get(key))
            if text:
                info[label] = text
    status = read_plist(os.path.join(folder, "Status.plist"))
    if isinstance(status, dict):
        text = _shown(status.get("IsFullBackup"))
        if text:
            info["Full backup"] = text
    return list(info.items())


def _find_key(value, key, depth=0):
    """The first string stored under *key* anywhere inside *value*."""
    if depth > 8:
        return ""
    if isinstance(value, dict):
        if isinstance(value.get(key), str) and value[key].strip():
            return value[key].strip()
        for item in value.values():
            found = _find_key(item, key, depth + 1)
            if found:
                return found
    return ""


def preferences_info(folder):
    """The names the phone calls itself, from its preferences."""
    data = read_plist(os.path.join(folder, os.path.basename(PREFERENCES)))
    items = []
    for label, key in (("Name of the device", "ComputerName"),
                       ("Host name", "HostName"),
                       ("Local host name", "LocalHostName")):
        found = _find_key(data, key)
        if found:
            items.append((label, found))
    return items


# ── The accounts ─────────────────────────────────────────────

def _enabled_services(conn):
    """``{account id: [service names]}`` of the services each account is
    switched on for."""
    names = {pk: _as_text(name) for pk, name in sqlite_rows(
        conn, "SELECT Z_PK, ZNAME FROM ZDATACLASS")}
    result = {}
    for (table,) in sqlite_rows(
            conn, "SELECT name FROM sqlite_master WHERE type = 'table' "
                  "AND name GLOB 'Z_*ENABLEDDATACLASSES'"):
        if not re.fullmatch(r"Z_\w+", table):
            continue
        columns = [r[1] for r in sqlite_rows(
            conn, f"PRAGMA table_info({table})")]
        account = next((c for c in columns if c.endswith("ENABLEDACCOUNTS")),
                       None)
        service = next((c for c in columns
                        if c.endswith("ENABLEDDATACLASSES")), None)
        if not account or not service:
            continue
        for owner, dataclass in sqlite_rows(
                conn, f"SELECT {account}, {service} FROM {table}"):
            name = names.get(dataclass)
            if name:
                result.setdefault(owner, []).append(name)
    return result


def _as_text(value):
    """Text that the database may hold as a blob (service names are)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace").strip()
    return value.strip() if isinstance(value, str) else ""


def _service_label(name):
    """``com.apple.Dataclass.Contacts`` -> ``Contacts``."""
    return name.rsplit(".", 1)[-1]


def account_rows(conn):
    services = _enabled_services(conn)
    types = {}
    rows = []
    items = sqlite_rows(conn, """
        SELECT a.Z_PK, t.ZACCOUNTTYPEDESCRIPTION, a.ZACCOUNTDESCRIPTION,
               a.ZUSERNAME, a.ZACTIVE, a.ZVISIBLE, a.ZDATE,
               a.ZPARENTACCOUNT, a.ZOWNINGBUNDLEID
        FROM ZACCOUNT a LEFT JOIN ZACCOUNTTYPE t ON t.Z_PK = a.ZACCOUNTTYPE
        ORDER BY a.Z_PK""")
    for item in items:
        types[item[0]] = item[1] or ""
    for (pk, kind, description, user, active, visible, added, parent,
         owner) in items:
        rows.append({
            "type": kind or "(unknown type)",
            "description": (description or "").strip(),
            "user": (user or "").strip(),
            "active": "" if active else "off",
            "hidden": "" if visible in (None, 1) else "hidden",
            "added": apple_time(added) if added else None,
            "parent": types.get(parent, "") if parent else "",
            "owner": owner or "",
            "services": ", ".join(sorted(
                {_service_label(n) for n in services.get(pk, ())})),
        })
    return rows


def _details(row):
    lines = [row["type"]]
    for label, text in (("Description", row["description"]),
                        ("Account name", row["user"]),
                        ("Part of", row["parent"]),
                        ("Switched on for", row["services"]),
                        ("Set up by", row["owner"]),
                        ("Added", format_datetime(row["added"]))):
        if text:
            lines.append(f"{label}: {text}")
    if row["active"]:
        lines.append("Not active")
    if row["hidden"]:
        lines.append("Not shown in Settings")
    return "\n".join(lines)


def device_dataset(items):
    """The facts about the device as a two-column table (or None)."""
    rows = [{"item": label, "value": value} for label, value in items]
    if not rows:
        return None
    return Dataset(
        "device", "This device", [
            Column("item", "Item", 200), Column("value", "Value", 460)],
        rows, note="From the backup's own information files and the "
                   "phone's preferences.")


def datasets(conn, folder, backup_folder=None, has_accounts=True):
    """The datasets: the device (first, when anything is known) and the
    accounts (*has_accounts* is False when the backup has no accounts
    database, so *conn* is not a database at all)."""
    result = []
    facts = backup_info(backup_folder)
    known = {label for label, _value in facts}
    device = device_dataset(facts + [item for item in preferences_info(folder)
                                     if item[0] not in known])
    if device is not None:
        result.append(device)
    rows = account_rows(conn) if has_accounts else []
    if rows:
        result.append(Dataset(
            "accounts", "Accounts", [
                Column("type", "Type", 180),
                Column("description", "Description", 200),
                Column("user", "Account name", 240),
                Column("services", "Switched on for", 240),
                Column("added", "Added", 130, "date"),
                Column("active", "", 50)],
            rows, sort=("type", False), details=_details,
            note="Passwords and sign-in keys are not in a backup's "
                 "accounts file; they are kept in the keychain."))
    return result


class AccountsReader:
    def __init__(self, conn, backup_folder=None):
        self.conn = conn
        self.backup_folder = backup_folder

    def datasets(self):
        own = own_path(self.conn)
        return datasets(self.conn, os.path.dirname(own), self.backup_folder,
                        not own.lower().endswith(".plist"))
