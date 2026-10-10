# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Voicemail tab
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

"""The Voicemail tab: who called, when, how long, and the words the phone
wrote down, with the recording to play or save. Export the audio with the
words beside it, or a list."""

from tkinter import messagebox

from . import voicemail as vm
from .records_view import RecordsPanel


def _load(conn, book, index):
    reader = vm.VoicemailReader(conn, book, index)
    return reader, reader.datasets()


class VoicemailPanel(RecordsPanel):
    DATABASE = vm.DATABASE
    FOLDER = "voicemail"
    WITH_CONTACTS = True
    LOADER = staticmethod(_load)
    MISSING = "This backup has no voicemail."

    def discover(self, index):
        return vm.discover(index)

    def extra_originals(self):
        chosen = self.selected_rows() or (self.dataset.rows if self.dataset
                                          else [])
        paths = [p + suffix for p in self.DATABASES[:1]
                 for suffix in ("", "-wal", "-shm")]
        paths += list(self.DATABASES[1:])
        paths += [r["audio"] for r in chosen if r["audio"]]
        return paths

    def _audio_of(self, row, what):
        if not row["audio"]:
            messagebox.showinfo(
                "Info", f"This voicemail's recording is not in the backup, "
                f"so it cannot be {what}.")
            return None
        return row["audio"]

    def action_play(self, row):
        path = self._audio_of(row, "played")
        if path:
            self.open_backup_file(path)

    def action_save(self, row):
        path = self._audio_of(row, "saved")
        if path:
            self.save_backup_file(path, vm.friendly_name(
                row, vm.extension_of(row)))
