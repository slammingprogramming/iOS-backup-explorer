# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Maps tab
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

"""The Maps tab: favorites, the places in guides, and the history of
searches. Export the places as a GPX file for mapping programs."""

from . import maps as mp
from .records_view import RecordsPanel


def _load(conn, _book, _index):
    reader = mp.MapsReader(conn)
    return reader, reader.datasets()


class MapsPanel(RecordsPanel):
    DATABASE = mp.DATABASE
    ORIGINALS = (mp.DATABASE,)
    FOLDER = "maps"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no Maps data."
