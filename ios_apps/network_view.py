# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Network tab
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

"""The Network tab: the Wi-Fi networks the phone joined, the Bluetooth
devices it knows, and the data each app used."""

from . import network as nw
from .records_view import RecordsPanel


def _load(conn, _book, index):
    reader = nw.NetworkReader(conn, index)
    return reader, reader.datasets()


class NetworkPanel(RecordsPanel):
    FOLDER = "network"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no network information."

    def discover(self, index):
        return nw.discover(index)

    def extra_originals(self):
        return [p + suffix for p in self.DATABASES
                for suffix in (("", "-wal", "-shm")
                               if not p.endswith(".plist") else ("",))]
