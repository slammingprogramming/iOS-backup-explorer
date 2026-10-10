# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Podcasts tab
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

"""The Podcasts tab: the shows and the episodes, with what was played."""

from . import podcasts as m
from .records_view import RecordsPanel


def _load(conn, _book, _index):
    reader = m.PodcastsReader(conn)
    return reader, reader.datasets()


class PodcastsPanel(RecordsPanel):
    FOLDER = "podcasts"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no Podcasts data."

    def discover(self, index):
        return m.discover(index)

    def extra_originals(self):
        return [p + suffix for p in self.DATABASES
                for suffix in ("", "-wal", "-shm")]
