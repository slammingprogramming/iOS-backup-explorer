# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — tables of records, the common shape of small apps
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

"""Many things on a phone are lists of records with a few columns: Safari's
history, bookmarks, calendar events, reminders, voicemails, networks the
phone has joined. A reader turns the app's database into one or more
:class:`Dataset` objects; one panel (``records_view``) shows any of them,
sorted, searched and exported, so each new app needs only a reader. No GUI.
"""

import contextlib
import os
import sqlite3
from dataclasses import dataclass, field

from .common import (apple_time, format_datetime, table_columns,  # noqa: F401
                     utc_datetime)
from .export_util import describe_duration, describe_size

KINDS = ("text", "date", "day", "number", "duration", "size")
# ("day": a calendar date kept as midnight UTC, shown as that date)


@dataclass
class Column:
    key: str
    heading: str
    width: int = 120
    kind: str = "text"            # one of KINDS: how a value is shown
    anchor: str = "w"
    format: object = None         # format(row) -> the text, when a value
                                  # alone does not say how to show it

    def show(self, value, row=None):
        """The text for *value* (of *row*) in this column."""
        if self.format is not None and row is not None:
            return self.format(row)
        if value is None or value == "":
            return ""
        if self.kind == "day":
            return format_day(value)
        if self.kind == "date":
            return format_datetime(value)
        if self.kind == "duration":
            return describe_duration(value)
        if self.kind == "size":
            return describe_size(value)
        if self.kind == "number":
            return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
        return str(value)


@dataclass
class Dataset:
    """One table: what to call it, its columns and its rows (dicts)."""
    key: str
    title: str
    columns: list
    rows: list = field(default_factory=list)
    note: str = ""                # shown under the table (what to know)
    sort: tuple = None            # (column key, descending)
    details: object = None        # detail(row) -> text for the pane, or None
    actions: tuple = ()           # ((label, name), ...): see RecordsPanel
    formats: dict = field(default_factory=dict)   # more export formats:
                                  # {key: (label, writer(path_base, rows))}
    file_formats: dict = field(default_factory=dict)   # formats that copy
                                  # files out of the backup (audio, ...):
                                  # {key: (label, writer(folder, rows,
                                  # copy_file) -> paths or (paths, notes))}

    def text_of(self, row):
        """All the words of *row* that can be searched."""
        parts = []
        for column in self.columns:
            parts.append(column.show(row.get(column.key), row))
        if self.details is not None:
            parts.append(self.details(row) or "")
        return " ".join(p for p in parts if p)

    def search(self, rows, text):
        words = text.casefold().split()
        if not words:
            return list(rows)
        return [r for r in rows
                if _has_all(self.text_of(r).casefold(), words)]

    def sorted_rows(self, rows, key=None, descending=None):
        key = key or (self.sort[0] if self.sort else None)
        if key is None:
            return list(rows)
        if descending is None:
            descending = bool(self.sort and self.sort[1]
                              and self.sort[0] == key)
        known = [r for r in rows if r.get(key) not in (None, "")]
        unknown = [r for r in rows if r.get(key) in (None, "")]
        try:
            known.sort(key=lambda r: _order(r.get(key)), reverse=descending)
        except TypeError:
            known.sort(key=lambda r: str(r.get(key)).casefold(),
                       reverse=descending)
        return known + unknown                  # no value: always last


def _has_all(haystack, words):
    return all(w in haystack for w in words)


def _order(value):
    return value.casefold() if isinstance(value, str) else value


def format_day(stamp):
    """``2026-05-25`` for a date kept as midnight UTC (all-day events), not
    moved to the computer's time zone."""
    try:
        return utc_datetime(stamp).strftime("%Y-%m-%d")
    except (OverflowError, ValueError, TypeError):
        return ""


def sqlite_rows(conn, sql, params=()):
    """Run *sql*; ``[]`` if a table or column it needs is missing (the
    layouts differ between iOS versions)."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


@contextlib.contextmanager
def open_copies(conn, backup_paths):
    """``{backup path: connection or None}`` for the working copies of
    several databases that sit next to the one *conn* is connected to (see
    ``AppPanel.DATABASES``). *conn* itself stands in for its own file; the
    others are opened read-only and closed again afterwards. Used on the
    database thread."""
    own = conn.execute("PRAGMA database_list").fetchone()[2]
    folder = os.path.dirname(own)
    opened, found = [], {}
    try:
        for backup_path in backup_paths:
            path = os.path.join(folder, os.path.basename(backup_path))
            if os.path.normcase(path) == os.path.normcase(own):
                found[backup_path] = conn
            elif os.path.isfile(path):
                other = sqlite3.connect(path)
                other.execute("PRAGMA query_only = ON")
                opened.append(other)
                found[backup_path] = other
            else:
                found[backup_path] = None
        yield found
    finally:
        for other in opened:
            other.close()


def fetch_dicts(conn, table, columns, where="", order="", joins=""):
    """The rows of *table* as dicts with the keys *columns*. A column the
    table does not have is ``None`` in every row, and a missing table gives
    no rows, so one reader copes with every iOS version."""
    present = table_columns(conn, table)
    if not present:
        return []
    select = ", ".join(f"{table}.{c}" if c in present else "NULL"
                       for c in columns)
    sql = f"SELECT {select} FROM {table} {joins}"
    if where:
        sql += f" WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    try:
        return [dict(zip(columns, row)) for row in conn.execute(sql)]
    except sqlite3.OperationalError:
        return []
