# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Safari tab
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

"""The Safari tab: history, the sites visited most, bookmarks, the reading
list and the open tabs. Open a page's address in your browser by
double-clicking it (web addresses only)."""

import webbrowser
from tkinter import messagebox

from . import safari as sf
from .records_view import RecordsPanel


def _load(conn, _book, _index):
    reader = sf.SafariReader(conn)
    return reader, reader.datasets()


class SafariPanel(RecordsPanel):
    DATABASES = sf.DATABASES
    ORIGINALS = sf.DATABASES
    FOLDER = "safari"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no Safari data."

    def on_loaded(self, datasets):
        for dataset in datasets:
            if any(c.key == "url" for c in dataset.columns):
                dataset.actions = (("Open in browser", "open_page"),)
                dataset.note = ("Double-click a row to open its address in "
                                "your web browser.")
        super().on_loaded(datasets)

    def action_open_page(self, row):
        url = row.get("url", "")
        if url.lower().startswith(("http://", "https://")):
            webbrowser.open(url)
        else:
            messagebox.showinfo(
                "Open", "Only web addresses (http and https) are opened "
                "from here.")
