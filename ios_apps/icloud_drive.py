# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — iCloud Drive files
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

"""Lists the files that were in iCloud Drive, from the file provider's own
backup manifest. No GUI.

Only the paths are in the manifest. The files themselves are in iCloud, not
in the backup (a phone that has not downloaded a file keeps only a small
placeholder).
"""

import os

from .records import Column, Dataset, sqlite_rows

DATABASE = ("HomeDomain/Library/Application Support/FileProvider/backup/"
            "backup_manifest.db")


def rows(conn):
    result = []
    for (path,) in sqlite_rows(
            conn, "SELECT relative_path FROM backup_manifest"):
        if not isinstance(path, str) or not path.strip("/"):
            continue
        folder, name = os.path.split(path.strip("/"))
        extension = os.path.splitext(name)[1].lower().lstrip(".")
        result.append({"name": name, "folder": folder, "path": path,
                       "kind": extension})
    return result


def datasets(conn):
    data = rows(conn)
    if not data:
        return []
    return [Dataset("files", "Files", [
        Column("name", "Name", 360), Column("folder", "Folder", 420),
        Column("kind", "Type", 70)],
        data, sort=("name", False),
        details=lambda r: r["path"],
        note="Only the names are kept in a backup; the files are in "
             "iCloud.")]


class ICloudDriveReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        return datasets(self.conn)
