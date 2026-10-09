# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — shared helpers for the app views
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

"""Plumbing shared by every app view (Messages, Notes, Calls, ...).

None of this needs a GUI. The pieces:

* :func:`apple_time` turns the timestamps iOS databases use into Unix time.
* :class:`Workspace` is a private temporary folder for working copies of
  the databases an app view reads. It is deleted when the backup is closed.
* :func:`locate_database` finds a database in the backup together with its
  ``-wal`` / ``-shm`` files, so recent changes are not lost.
* :class:`SqliteSource` runs queries against such a copy on one thread.
* :class:`ContactBook` turns phone numbers and email addresses into names.
"""

import concurrent.futures
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime

APPLE_EPOCH = 978_307_200
"""Seconds from 1970-01-01 to 2001-01-01, the start of Apple's clock."""


def apple_time(value):
    """Unix time for an Apple database timestamp, or None if there is none.

    iOS counts seconds from 2001-01-01. Newer Messages databases count
    *nanoseconds* instead, so a huge number is divided down first.
    """
    if value is None or value == "":
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds == 0:
        return None
    if abs(seconds) > 1e11:
        seconds /= 1e9
    return seconds + APPLE_EPOCH


def format_datetime(stamp, seconds=False):
    """A local date and time such as ``2026-10-09 14:05``, or ``""``."""
    if stamp is None:
        return ""
    try:
        return datetime.fromtimestamp(stamp).strftime(
            "%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


class Workspace:
    """A private temporary folder for working copies of backup files.

    Decrypted databases and attachments are written here for the app views
    to read. The folder is removed by :meth:`close`.
    """

    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="ios-backup-explorer-apps-")

    def subfolder(self, name):
        path = os.path.join(self.path, name)
        os.makedirs(path, exist_ok=True)
        return path

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)


def locate_database(index, path):
    """``[(file_id, name), ...]`` for the SQLite database at *path*
    (``Domain/folder/name``) and its ``-wal`` / ``-shm`` siblings.

    Those siblings can hold the newest changes, so they must be copied
    together with the database. Empty if the database itself is missing.
    """
    node = index.get(path)
    if node is None or node.is_dir:
        return []
    base = os.path.basename(path)
    items = [(node.file_id, base)]
    for suffix in ("-wal", "-shm"):
        sibling = index.get(path + suffix)
        if sibling is not None and not sibling.is_dir:
            items.append((sibling.file_id, base + suffix))
    return items


class SqliteSource:
    """Runs functions against a working copy of a database, all on one
    dedicated thread (an SQLite connection may only be used on the thread
    that made it). ``run(func, *args)`` calls ``func(connection, *args)``
    there and returns a Future.
    """

    def __init__(self, path):
        self.path = path
        self._conn = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="app-db")

    def run(self, func, *args):
        return self._executor.submit(self._call, func, args)

    def _call(self, func, args):
        if self._conn is None:
            self._conn = sqlite3.connect(self.path)
            self._conn.execute("PRAGMA query_only = ON")
        return func(self._conn, *args)

    def close(self):
        def close_connection():
            if self._conn is not None:
                self._conn.close()
                self._conn = None

        self._executor.submit(close_connection)
        self._executor.shutdown(wait=False)


def table_columns(conn, table):
    """The column names of *table* (empty if it does not exist)."""
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


# ── Names for numbers ────────────────────────────────────────

_NON_DIGITS = re.compile(r"\D")


def handle_key(handle):
    """A normal form of a phone number or email, for matching contacts.

    Emails are lower-cased. Phone numbers keep only digits, and only their
    last ten, so ``+1 (555) 010-1234`` and ``5550101234`` match.
    """
    handle = (handle or "").strip()
    if "@" in handle:
        return handle.lower()
    digits = _NON_DIGITS.sub("", handle)
    return digits[-10:]


class ContactBook:
    """Looks up a contact's name from a phone number or email address."""

    PHONE, EMAIL = 3, 4         # ABMultiValue.property values

    def __init__(self):
        self._names = {}
        self.person_count = 0

    @classmethod
    def from_connection(cls, conn):
        """Read the address book database (``AddressBook.sqlitedb``)."""
        book = cls()
        try:
            people = {}
            for rowid, first, last, org, nick in conn.execute(
                    "SELECT ROWID, First, Last, Organization, Nickname "
                    "FROM ABPerson"):
                name = " ".join(p for p in (first, last) if p) \
                    or org or nick
                if name:
                    people[rowid] = name
            book.person_count = len(people)
            for record_id, prop, value in conn.execute(
                    "SELECT record_id, property, value FROM ABMultiValue "
                    "WHERE property IN (?, ?)", (cls.PHONE, cls.EMAIL)):
                if record_id in people and value:
                    key = handle_key(str(value))
                    if key:
                        book._names.setdefault(key, people[record_id])
        except sqlite3.Error:
            pass            # no address book, or one we cannot read
        return book

    def name_for(self, handle):
        """The contact's name for *handle*, or None."""
        key = handle_key(handle)
        return self._names.get(key) if key else None

    def __len__(self):
        return len(self._names)
