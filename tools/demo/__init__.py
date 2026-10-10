# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""An invented iPhone backup, for the screenshots and for trying the app.

Nothing in it comes from a real device: the people, places, messages,
photos and numbers are made up (the phone numbers are in the ranges set
aside for fiction, the addresses use example.com). It is written as a
folder of domain folders (``HomeDomain``, ``CameraRollDomain``, ...), which
the app opens like any backup. See ``tools/make_demo_backup.py``.
"""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
"""The moment the demo phone was backed up."""

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def ago(**kwargs):
    """A moment before the backup (``ago(days=2, hours=3)``)."""
    return NOW - timedelta(**kwargs)


def cocoa(moment):
    """Seconds since 2001-01-01 (how most iOS databases count)."""
    return (moment - APPLE_EPOCH).total_seconds()


def unix(moment):
    return moment.timestamp()


class Writer:
    """Writes the files of the demo backup under *root*."""

    def __init__(self, root):
        self.root = root
        self.count = 0

    def file(self, domain, path, data, when=None):
        target = os.path.join(self.root, domain, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        if when is not None:
            stamp = unix(when) if isinstance(when, datetime) else when
            os.utime(target, (stamp, stamp))
        self.count += 1
        return target

    def file_at_root(self, name, data):
        """A file beside the domain folders (``Info.plist``...)."""
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, name), "wb") as handle:
            handle.write(data)
        self.count += 1

    def database(self, domain, path, builder, when=None):
        """A SQLite database filled in by ``builder(conn)``."""
        folder = tempfile.mkdtemp(prefix="ibe-demo-")
        try:
            temporary = os.path.join(folder, "x.db")
            conn = sqlite3.connect(temporary)
            builder(conn)
            conn.commit()
            conn.close()
            with open(temporary, "rb") as handle:
                data = handle.read()
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return self.file(domain, path, data, when)


def clone_schema(builder, conn):
    """Create in *conn* the tables (and indexes) that a test fixture's
    ``builder`` makes, without its rows, so the demo data follows exactly
    the layout the readers expect."""
    source = sqlite3.connect(":memory:")
    try:
        builder(source)
        for (sql,) in source.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND "
                "name NOT LIKE 'sqlite_%' ORDER BY rowid"):
            conn.execute(sql)
    finally:
        source.close()
