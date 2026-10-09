# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading the Voice Memos
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

"""Lists the voice recordings. No GUI.

The recordings are found by looking in the backup's recordings folders, so
they are listed even without their database. When the database is there it
adds each recording's title, date and length.
"""

import os
from dataclasses import dataclass

from .common import apple_time, table_columns

FOLDERS = ("AppDomainGroup-group.com.apple.VoiceMemos.shared/Recordings",
           "MediaDomain/Media/Recordings")
DATABASES = (
    "AppDomainGroup-group.com.apple.VoiceMemos.shared/Recordings/"
    "CloudRecordings.db",
    "MediaDomain/Media/Recordings/Recordings.db")

AUDIO_EXTENSIONS = {".m4a", ".qta", ".caf", ".wav", ".mp3", ".aac", ".amr",
                    ".aiff", ".mp4"}


@dataclass
class Memo:
    path: str                       # in the backup
    name: str                       # the file's name
    file_id: str = ""
    size: int = 0
    title: str = ""
    when: float = None              # when it was recorded
    when_from: str = "file"         # "library" when the database said so
    duration: float = None          # seconds, if the database knows

    @property
    def display_title(self):
        return self.title or os.path.splitext(self.name)[0]


def find_database(index):
    """The path of the recordings database in the backup, or None."""
    for path in DATABASES:
        node = index.get(path)
        if node is not None and not node.is_dir:
            return path
    return None


def scan(index):
    """Every recording in the recordings folders, from the file index alone.
    The date is the file's own date."""
    memos = []
    for folder in FOLDERS:
        root = index.get(folder)
        if root is None or not root.is_dir:
            continue
        for node in index.walk_files(root):
            if os.path.splitext(node.name)[1].lower() not in AUDIO_EXTENSIONS:
                continue
            stamp = node.birth or node.mtime
            memos.append(Memo(index.path_of(node), node.name, node.file_id,
                              node.size, "",
                              float(stamp) if stamp else None))
    memos.sort(key=lambda m: m.when or 0, reverse=True)
    return memos


def has_recordings(index):
    """Whether the backup holds voice recordings (or their database)."""
    return find_database(index) is not None or bool(scan(index))


def enrich(memos, conn):
    """Add titles, dates and lengths from the recordings database to
    *memos* (in place). Raises ``sqlite3.DatabaseError`` if the file is not
    a database."""
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    for table in ("ZCLOUDRECORDING", "ZRECORDING"):
        cols = table_columns(conn, table)
        if "ZPATH" in cols:
            break
    else:
        return memos
    by_name = {m.name.casefold(): m for m in memos}

    def col(name):
        return name if name in cols else "NULL"

    for path, label, date, duration in conn.execute(
            f"SELECT ZPATH, {col('ZCUSTOMLABEL')}, {col('ZDATE')}, "
            f"{col('ZDURATION')} FROM {table}"):
        # the stored path may be one from the phone itself
        name = os.path.basename(str(path or "").replace("\\", "/"))
        memo = by_name.get(name.casefold())
        if memo is None:
            continue
        memo.title = (label or "").strip()
        stamp = apple_time(date)
        if stamp is not None:
            memo.when, memo.when_from = stamp, "library"
        if duration:
            memo.duration = float(duration)
    return memos


SORTS = {
    "Date, newest first": (lambda m: m.when or 0, True),
    "Date, oldest first": (lambda m: m.when or 0, False),
    "Title": (lambda m: m.display_title.casefold(), False),
    "Length, longest first": (lambda m: m.duration or 0, True),
    "Size, largest first": (lambda m: m.size, True),
}


def sort_memos(memos, how):
    key, descending = SORTS[how]
    return sorted(memos, key=key, reverse=descending)


def search_memos(memos, text):
    words = text.casefold().split()
    return [m for m in memos
            if all(w in f"{m.display_title} {m.name}".casefold()
                   for w in words)]
