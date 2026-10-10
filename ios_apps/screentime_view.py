# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Screen Time tab
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

"""The Screen Time tab: time per day and week, per app and per website,
pickups and notifications."""

from . import screentime as st
from .records_view import RecordsPanel


def _load(conn, _book, _index):
    reader = st.ScreenTimeReader(conn)
    return reader, reader.datasets()


class ScreenTimePanel(RecordsPanel):
    FOLDER = "screentime"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no Screen Time data."

    def discover(self, index):
        return st.discover(index)

    def local_name(self, backup_path):
        return st.local_name(backup_path)

    def extra_originals(self):
        return list(self.DATABASES)
