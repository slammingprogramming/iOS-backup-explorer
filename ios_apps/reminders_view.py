# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Reminders tab
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

"""The Reminders tab: every reminder with its list, due date, priority and
notes, and the lists. Export as a to-do file that calendar and task
programs import, or as a spreadsheet, web page, text or JSON."""

from . import reminders as rm
from .records_view import RecordsPanel


def _load(conn, _book, index):
    reader = rm.RemindersReader(conn, index)
    return reader, reader.datasets()


class RemindersPanel(RecordsPanel):
    FOLDER = "reminders"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no reminders."

    def discover(self, index):
        return rm.discover(index)

    def extra_originals(self):
        return [p + suffix for p in self.DATABASES
                for suffix in ("", "-wal", "-shm")]
