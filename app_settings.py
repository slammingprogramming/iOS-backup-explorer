# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the few things that are remembered between runs
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

"""What the program remembers: the extra folders to look for backups in,
where new backups are made, and where the libimobiledevice tools are if they
are not on the ``PATH``. Three paths, in one small JSON file in the user's
own settings folder; no passwords, no names, nothing about any backup.

A missing or damaged file is the same as an empty one, and a failed save
never stops the program (it only means the choice is forgotten).
"""

import json
import os

FILE_NAME = "settings.json"
KEYS = ("backup_folders", "backup_destination", "tools_folder")


def settings_folder(system, environ, home):
    """The user's folder for this program's settings."""
    if system == "Windows":
        base = environ.get("APPDATA") or os.path.join(home, "AppData",
                                                      "Roaming")
        return os.path.join(base, "iOS Backup Explorer")
    if system == "Darwin":
        return os.path.join(home, "Library", "Application Support",
                            "iOS Backup Explorer")
    base = environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "ios-backup-explorer")


class Settings:
    """The remembered choices. ``Settings.load(folder)`` reads them,
    ``save()`` writes them back."""

    def __init__(self, folder=None):
        self.folder = folder
        self.backup_folders = []
        self.backup_destination = ""
        self.tools_folder = ""

    @classmethod
    def load(cls, folder):
        settings = cls(folder)
        try:
            with open(os.path.join(folder, FILE_NAME), "r",
                      encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return settings
        if not isinstance(data, dict):
            return settings
        folders = data.get("backup_folders")
        if isinstance(folders, list):
            settings.backup_folders = [f for f in folders
                                       if isinstance(f, str) and f]
        for key in ("backup_destination", "tools_folder"):
            if isinstance(data.get(key), str):
                setattr(settings, key, data[key])
        return settings

    def add_folder(self, path):
        """Remember *path* as a place to look for backups."""
        path = os.path.abspath(path)
        if path not in self.backup_folders:
            self.backup_folders.append(path)

    def remove_folder(self, path):
        self.backup_folders = [f for f in self.backup_folders if f != path]

    def save(self):
        """Write the settings; False if that was not possible."""
        if not self.folder:
            return False
        data = {key: getattr(self, key) for key in KEYS}
        target = os.path.join(self.folder, FILE_NAME)
        partial = target + ".tmp"
        try:
            os.makedirs(self.folder, exist_ok=True)
            with open(partial, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=2)
            os.replace(partial, target)
        except OSError:
            return False
        return True
