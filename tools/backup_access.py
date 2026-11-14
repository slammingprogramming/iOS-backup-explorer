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
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

SIDECARS = ("-wal", "-shm")          # (a database's journal files)

# The decryption library prints this, about each file whose decrypted size is
# not the one the manifest gave (routine for a database the phone compacted
# as it backed it up).
LIBRARY_NOTE = "INFO: decrypted "


class _WithoutLibraryNotes:
    """Stands in for ``sys.stdout``: the stream that was there, less the
    library's note about each file.

    The note names the working copy of the file, a path that holds the name of
    whoever is logged in, and what the tools here print is meant to be pasted
    into a public issue. Whole lines are judged; anything else is passed on as
    it comes, so a prompt without a newline is not held back."""

    def __init__(self, stream):
        self._stream = stream
        self._held = ""                 # (a start of a line that may be a note)
        self._lock = threading.Lock()

    def write(self, text):
        with self._lock:
            data, passed = self._held + text, []
            while "\n" in data:
                line, _, data = data.partition("\n")
                if not line.startswith(LIBRARY_NOTE):
                    passed.append(line + "\n")
            if data and (data.startswith(LIBRARY_NOTE)
                         or LIBRARY_NOTE.startswith(data)):
                self._held = data
            else:
                self._held = ""
                passed.append(data)
            if passed:
                self._stream.write("".join(passed))
        return len(text)

    def release(self):
        """What is held, if it turned out not to be a note."""
        with self._lock:
            held, self._held = self._held, ""
            if held and not held.startswith(LIBRARY_NOTE):
                self._stream.write(held)

    def __getattr__(self, name):        # (flush, isatty, encoding...)
        return getattr(self._stream, name)


@contextlib.contextmanager
def without_library_notes():
    """While inside, what is printed is cleared of the library's notes about
    files (see ``_WithoutLibraryNotes``). Threads that print meanwhile (the
    program's workers) are covered too, since ``sys.stdout`` is the one."""
    previous = sys.stdout
    filtered = _WithoutLibraryNotes(previous)
    sys.stdout = filtered
    try:
        yield
    finally:
        if sys.stdout is filtered:
            sys.stdout = previous
        filtered.release()


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
            compat_report.password_message(options.folder))
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
    with without_library_notes():
        try:
            session.open(folder, password).result(1800)
            rows = session.scan().result(1800)
            yield OpenedBackup(session, rows, FileIndex(rows))
        finally:
            try:
                session.close()
                session._executor.shutdown(wait=True)
            except Exception:                          # (best effort)
                pass


@contextlib.contextmanager
def scratch_folder():
    """A temporary folder that is removed afterwards, whatever happens."""
    folder = tempfile.mkdtemp(prefix="ibe-report-")
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)
