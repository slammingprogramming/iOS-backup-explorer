# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""What the report tools in this folder share: opening a backup (asking for its
password if it needs one), listing its files, and copying a few of them into a
temporary folder that is deleted afterwards.

The report tools (``schema_report.py``, ``health_kinds_report.py``) print the
*shape* of what a backup holds, never its contents, so that the output can be
pasted into an issue. This module never prints anything.
"""

import contextlib
import getpass
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

SIDECARS = ("-wal", "-shm")          # (a database's journal files)


def add_password_options(parser):
    """The two ways to give a password; the password is never stored."""
    parser.add_argument("--password-prompt", action="store_true",
                        help="ask for the password of an encrypted backup "
                        "on the terminal")
    parser.add_argument("--password-window", action="store_true",
                        help="ask for it in a small window instead")


def password_from(options):
    """The password the user chose to give (None if none was asked for, or
    the window was cancelled)."""
    if getattr(options, "password_prompt", False):
        return getpass.getpass("Backup password: ")
    if getattr(options, "password_window", False):
        import compat_report
        return compat_report.ask_password(
            "Enter the password of this backup. It is used only to open it, "
            "then dropped (never saved or printed).")
    return None


class OpenedBackup:
    """An opened backup: ``index`` (the file tree) and ``rows`` (every file
    and folder as ``(id, domain, path, flags, size, mtime, birth)``)."""

    def __init__(self, session, rows, index):
        self.session, self.rows, self.index = session, rows, index

    def file_id(self, path):
        node = self.index.get(path)
        return None if node is None or node.is_dir else node.file_id

    def size(self, path):
        node = self.index.get(path)
        return None if node is None or node.is_dir else node.size

    def copy_to(self, folder, paths):
        """Copy the files at the backup *paths* (and the journal files beside
        them) into *folder*. Returns ``{path: local file}`` for the ones
        copied."""
        wanted, local = [], {}
        for path in paths:
            for suffix in ("",) + SIDECARS:
                file_id = self.file_id(path + suffix)
                if file_id is not None:
                    wanted.append(file_id)
                    if not suffix:
                        domain, _, relative = path.partition("/")
                        local[path] = os.path.join(
                            folder, domain, *relative.split("/"))
        if wanted:
            self.session.extract(wanted, folder).result(3600)
        return {p: f for p, f in local.items() if os.path.isfile(f)}


@contextlib.contextmanager
def open_backup(folder, password=None):
    """Open the backup (or extracted folder) at *folder*. Raises whatever the
    program raises for a backup it cannot open (a wrong password, a folder
    that is not a backup)."""
    import ios_backup_explorer as app
    from file_index import FileIndex
    session = app.BackupSession()
    try:
        session.open(folder, password).result(1800)
        rows = session.scan().result(1800)
        yield OpenedBackup(session, rows, FileIndex(rows))
    finally:
        try:
            session.close()
            session._executor.shutdown(wait=True)
        except Exception:                              # (best effort)
            pass


@contextlib.contextmanager
def scratch_folder():
    """A temporary folder that is removed afterwards, whatever happens."""
    folder = tempfile.mkdtemp(prefix="ibe-report-")
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)
