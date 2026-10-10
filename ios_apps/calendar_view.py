# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Calendar tab
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

"""The Calendar tab: the events (sorted, searched, with their details) and
the calendars. Export them as an iCalendar file that any calendar program
imports, or as a spreadsheet, a web page, text or JSON."""

from . import calendar_events as ce
from .records_view import RecordsPanel


def _load(conn, _book, _index):
    reader = ce.CalendarReader(conn)
    return reader, reader.datasets()


class CalendarPanel(RecordsPanel):
    DATABASE = ce.DATABASE
    ORIGINALS = (ce.DATABASE,)
    FOLDER = "calendar"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no calendar."
