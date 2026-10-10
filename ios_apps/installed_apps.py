# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the installed apps
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

"""Lists the apps the phone had installed (from the home screen's own
state database) with the badge each showed. No GUI.

Only the identifier of an app is stored there; a readable name is shown for
Apple's own apps and the identifier for the others.
"""

from .appnames import app_name
from .records import Column, Dataset, sqlite_rows

DATABASE = "HomeDomain/Library/FrontBoard/applicationState.db"


def rows(conn):
    badges = {}
    for identifier, value in sqlite_rows(
            conn, "SELECT t.application_identifier, v.value FROM kvs v "
                  "JOIN application_identifier_tab t "
                  "ON t.id = v.application_identifier JOIN key_tab k "
                  "ON k.id = v.key WHERE k.key = 'SBApplicationBadgeKey'"):
        if isinstance(value, (bytes, bytearray)):
            continue
        badges[identifier] = str(value).strip()
    result = []
    for (identifier,) in sqlite_rows(
            conn, "SELECT application_identifier FROM "
                  "application_identifier_tab ORDER BY id"):
        if not isinstance(identifier, str) or not identifier:
            continue
        result.append({
            "app": app_name(identifier), "identifier": identifier,
            "maker": "Apple" if identifier.startswith("com.apple.")
            else "", "badge": badges.get(identifier, "")})
    return result


def datasets(conn):
    data = rows(conn)
    if not data:
        return []
    return [Dataset("apps", "Apps", [
        Column("app", "App", 360), Column("identifier", "Identifier", 360),
        Column("maker", "", 70), Column("badge", "Badge", 70)],
        data, sort=("app", False),
        note="The apps the home screen knew of. Apple's own apps are named; "
             "for the others only the identifier is stored here.")]


class AppsReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        return datasets(self.conn)
