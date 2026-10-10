# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — recent contacts
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

"""Reads the phone's list of recent contacts (the people last called,
messaged or emailed, which the phone suggests when addressing something).
No GUI."""

from .common import format_datetime
from .records import Column, Dataset, sqlite_rows

DATABASE = "HomeDomain/Library/Recents/Recents"

CHANNELS = {
    "com.apple.MobileSMS": "Messages", "com.apple.mobilemail": "Mail",
    "com.apple.mobilephone": "Phone", "com.apple.facetime": "FaceTime",
    "com.apple.Passbook": "Wallet", "com.apple.passbook": "Wallet",
    "com.apple.maps": "Maps", "com.apple.Maps": "Maps",
    "com.apple.email.maild": "Mail"}


def _channel(identifier, source):
    for key in (identifier, source):
        if key in CHANNELS:
            return CHANNELS[key]
    return (identifier or source or "").strip()


def rows(conn):
    addresses = {}
    for recent, kind, address in sqlite_rows(
            conn, "SELECT recent_id, kind, address FROM contacts "
                  "ORDER BY ROWID"):
        addresses.setdefault(recent, []).append((kind or "", address or ""))
    result = []
    for (rowid, name, bundle, sending, source, last, count) in sqlite_rows(
            conn, "SELECT ROWID, display_name, bundle_identifier, "
                  "sending_address, original_source, last_date, count "
                  "FROM recents"):
        found = addresses.get(rowid, [])
        address = found[0][1] if found else (sending or "")
        result.append({
            "name": (name or "").strip(), "address": address.strip(),
            "also": len(found) - 1 if len(found) > 1 else 0,
            "kind": found[0][0] if found else "",
            "via": _channel(bundle, source),
            "count": count if isinstance(count, int) else None,
            # (stored as thousandths of a second since 1970)
            "last": last / 1000 if isinstance(last, (int, float))
            and last > 0 else None})
    return result


def _details(row):
    lines = [row["name"] or row["address"] or "(no name)"]
    for label, text in (("Address", row["address"]), ("Through", row["via"]),
                        ("Last", format_datetime(row["last"]))):
        if text:
            lines.append(f"{label}: {text}")
    if row["also"]:
        lines.append(f"{row['also']} more address(es)")
    return "\n".join(lines)


def datasets(conn):
    data = rows(conn)
    if not data:
        return []
    return [Dataset("recents", "Recent contacts", [
        Column("last", "Last", 140, "date"), Column("name", "Name", 240),
        Column("address", "Address", 280), Column("via", "Through", 100),
        Column("count", "Times", 60, "number", "e")],
        data, sort=("last", True), details=_details)]


class RecentsReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        return datasets(self.conn)
