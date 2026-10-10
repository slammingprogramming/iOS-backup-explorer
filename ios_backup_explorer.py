# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is a hard fork of BackupLens, which is
# Copyright (c) 2026 Eyyup (Eric) Gunes and was released under the MIT
# License. The original MIT copyright and permission notice are preserved
# in LICENSE-MIT and NOTICE and must remain with this software. Original
# project: https://github.com/mrgunes/BackupLens
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

"""
iOS Backup Explorer — Your data. Your eyes only.

A free, open-source GUI tool to decrypt, browse, and extract files
from encrypted iPhone/iPad backups made by iTunes or Finder.

100% offline. No tracking. No telemetry. No network calls.
Your backup password never leaves your machine.

Hard fork of BackupLens by Eyyup (Eric) Gunes (MIT License).
https://github.com/mrgunes/BackupLens
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
import collections
import concurrent.futures
import contextlib
import pathlib
import queue
import shutil
import sqlite3
import sys
import tempfile
import threading
import traceback
import time
import os
import plistlib
import platform
import re

import browser_panel
import folder_backup
from ios_apps import registry as app_registry
from ios_apps.context import AppContext
from file_index import (  # noqa: F401
    FileIndex, format_size, read_file_details,
)

__version__ = "2.0.1"
APP_NAME = "iOS Backup Explorer"

# The file list shows this many rows per page; longer listings are paged.
MAX_ROWS = 10000


# ── Helpers (no GUI) ─────────────────────────────────────────

def read_file_info(blob):
    """Return ``(size, mtime)`` from a Manifest.db ``file`` blob.

    Either value is ``None`` when it cannot be read.
    """
    size, mtime, _birth = read_file_details(blob)
    return size, mtime


_WINDOWS_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE
)


class UnsafePathError(ValueError):
    """A backup path that cannot be written safely under the output folder."""


def sanitize_component(part, windows=None):
    """Make one path component valid on the host file system."""
    if windows is None:
        windows = os.name == "nt"
    part = part.replace("\x00", "_")
    if not windows:
        return part
    part = _WINDOWS_ILLEGAL.sub("_", part)
    if _WINDOWS_RESERVED.match(part.split(".")[0]):
        part = "_" + part
    if part.endswith((".", " ")):
        part = part[:-1] + "_"
    return part or "_"


def build_output_path(dest, domain, relative_path, file_id="", used=None,
                      windows=None):
    """Return where a backup file is written: ``dest/domain/relative_path``.

    Raises UnsafePathError if the path would escape *dest*. Names that
    collide with one already written in this run (*used*, case-insensitive)
    get the file ID appended instead of overwriting each other.
    """
    parts = relative_path.split("/")
    if ".." in parts:
        raise UnsafePathError("path contains '..'")
    parts = [p for p in parts if p not in ("", ".")]
    if not parts:
        raise UnsafePathError("empty path")
    parts = [sanitize_component(domain, windows)] + [
        sanitize_component(p, windows) for p in parts
    ]

    real_dest = os.path.realpath(dest)
    out_path = os.path.join(real_dest, *parts)
    real_out = os.path.realpath(out_path)
    try:
        inside = os.path.commonpath(
            [os.path.normcase(real_dest), os.path.normcase(real_out)]
        ) == os.path.normcase(real_dest)
    except ValueError:
        inside = False
    if not inside or os.path.normcase(real_out) == os.path.normcase(real_dest):
        raise UnsafePathError("path escapes the output folder")

    if used is not None:
        key = os.path.normcase(out_path)
        if key in used and file_id:
            stem, ext = os.path.splitext(parts[-1])
            parts[-1] = f"{stem}_{file_id[:8]}{ext}"
            out_path = os.path.join(real_dest, *parts)
            key = os.path.normcase(out_path)
        used.add(key)
    return out_path


def fs_path(path):
    """Use the Windows extended-length form for very long paths.

    iOS backups contain deep paths (e.g. Notes attachments) that exceed
    the 260 character limit once joined to the output folder.
    """
    if os.name != "nt":
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\") or len(path) < 240:
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def is_wrong_passphrase(exc):
    """True if *exc* means the backup password was rejected."""
    return (type(exc).__name__ == "IncorrectPassphraseError"
            or (isinstance(exc, ValueError)
                and "incorrect passphrase" in str(exc).lower()))


ENCRYPTED = "encrypted"
UNENCRYPTED = "unencrypted"
EXTRACTED = "extracted"     # already decrypted and extracted into folders

_FILE_ID = re.compile(r"[0-9a-f]{40}\Z")


class BackupFormatError(ValueError):
    """The folder is not an iOS backup this app can open."""


class PassphraseRequiredError(ValueError):
    """The backup is encrypted but no password was given."""


def detect_backup(backup_dir):
    """Return ENCRYPTED, UNENCRYPTED or EXTRACTED for the backup in
    *backup_dir* (EXTRACTED: a folder of domain folders that a tool already
    decrypted and extracted, with no Manifest of its own).

    Raises BackupFormatError, with a message fit to show the user, if the
    folder is not a backup this app can open.
    """
    if not os.path.isdir(backup_dir):
        raise BackupFormatError("The backup folder does not exist.")
    plist_path = os.path.join(backup_dir, "Manifest.plist")
    try:
        with open(plist_path, "rb") as handle:
            manifest = plistlib.load(handle)
    except FileNotFoundError:
        if os.path.exists(os.path.join(backup_dir, "Manifest.mbdb")):
            raise BackupFormatError(_LEGACY_FORMAT) from None
        if folder_backup.looks_extracted(backup_dir):
            return EXTRACTED
        raise BackupFormatError(
            "This folder has no Manifest.plist, so it does not look like an "
            "iOS backup. Select the long hex-named folder inside "
            "MobileSync/Backup (or a folder of extracted domain folders, "
            "such as HomeDomain)."
        ) from None
    except Exception as exc:
        raise BackupFormatError(
            f"Manifest.plist could not be read ({type(exc).__name__})."
        ) from exc
    if not isinstance(manifest, dict):
        raise BackupFormatError("Manifest.plist is not in the expected format.")
    if not os.path.isfile(os.path.join(backup_dir, "Manifest.db")):
        if os.path.exists(os.path.join(backup_dir, "Manifest.mbdb")):
            raise BackupFormatError(_LEGACY_FORMAT)
        raise BackupFormatError("This backup has no Manifest.db file.")
    return ENCRYPTED if manifest.get("IsEncrypted") else UNENCRYPTED


_LEGACY_FORMAT = (
    "This backup uses the old Manifest.mbdb format (made by iTunes for "
    "iOS 9 and earlier), which this app cannot open."
)


class ExtractionReport:
    """Outcome of one extraction run."""

    def __init__(self):
        self.extracted = 0
        self.skipped = []   # (label, reason)
        self.errors = []    # (label, reason)
        self.cancelled = False


def _default_backup_factory(**kwargs):
    from iphone_backup_decrypt import EncryptedBackup
    return EncryptedBackup(**kwargs)


_QUIET_CLASSES = {}


def _disarm_finalizer(obj):
    """Make *obj*'s ``__del__`` do nothing.

    Used after cleaning up explicitly, so that a later garbage collection
    (possibly on another thread) neither repeats the cleanup nor complains
    about it. Works the same for every version of the library.
    """
    cls = type(obj)
    quiet = _QUIET_CLASSES.get(cls)
    if quiet is None:
        quiet = _QUIET_CLASSES[cls] = type(
            cls.__name__, (cls,), {"__del__": lambda self: None})
    try:
        obj.__class__ = quiet
    except TypeError:
        pass


class EncryptedBackend:
    """An encrypted backup, opened with ``iphone_backup_decrypt``."""

    def __init__(self, factory, backup_dir, passphrase):
        self._lib = factory(backup_directory=backup_dir,
                            passphrase=passphrase)

    def manifest_db_cursor(self):
        return self._lib.manifest_db_cursor()

    def extract(self, cur, file_id, domain, rel_path, mtime, out_path):
        # extract_file() looks the file up by relative path and a LIKE
        # pattern on the domain, so a '_' or '%' in the domain could also
        # match a different domain holding the same path.
        cur.execute(
            "SELECT COUNT(*) FROM Files "
            "WHERE relativePath = ? AND domain LIKE ? AND flags=1",
            (rel_path, domain),
        )
        if cur.fetchone()[0] <= 1:
            self._lib.extract_file(relative_path=rel_path,
                                   domain_like=domain,
                                   output_filename=out_path)
            return

        # Ambiguous: pick the exact row by file ID instead.
        def only_this_file(**kwargs):
            return out_path if kwargs.get("file_id") == file_id else False

        count = self._lib.extract_files(
            relative_paths_like=rel_path, domain_like=domain,
            output_folder=os.path.dirname(out_path),
            filter_callback=only_this_file,
        )
        if count != 1:
            raise RuntimeError("could not select this file unambiguously")

    def materialize(self, cur, file_id, domain, rel_path, size, mtime,
                    cache_dir):
        """Return a path to the decrypted file, decrypting it into
        *cache_dir* the first time it is asked for."""
        path = os.path.join(cache_dir, file_id)
        if os.path.exists(path):
            return path
        os.makedirs(cache_dir, exist_ok=True)
        if size == 0:
            open(path, "wb").close()
        else:
            self.extract(cur, file_id, domain, rel_path, mtime, path)
        return path

    def close(self):
        lib, self._lib = self._lib, None
        if lib is None:
            return
        # Clean up explicitly, here on the thread that owns the SQLite
        # connection, and do not rely on the library object being freed:
        # a traceback that is still alive somewhere (an error raised inside
        # manifest_db_cursor(), say) keeps it alive, and it would then be
        # finalised on another thread, which cannot close the connection
        # and so leaves the decrypted Manifest.db behind.
        try:
            lib._cleanup()
        except Exception:
            pass
        finally:
            _disarm_finalizer(lib)


class PlainBackend:
    """An unencrypted backup: no password, no library, no temporary files.

    Manifest.db is opened read-only and ``immutable``, so SQLite neither
    locks it nor writes journal files next to the user's backup, and file
    data is copied straight out of the backup folder.
    """

    def __init__(self, backup_dir):
        self._dir = os.path.abspath(backup_dir)
        manifest = pathlib.Path(self._dir, "Manifest.db")
        self._conn = sqlite3.connect(
            manifest.as_uri() + "?mode=ro&immutable=1", uri=True
        )
        try:
            self._conn.execute("SELECT 1 FROM Files LIMIT 1").close()
        except sqlite3.DatabaseError as exc:
            self._conn.close()
            raise BackupFormatError(
                f"Manifest.db could not be read as a backup index ({exc})."
            ) from exc

    @contextlib.contextmanager
    def manifest_db_cursor(self):
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def extract(self, cur, file_id, domain, rel_path, mtime, out_path):
        # file_id comes from the backup itself, so do not trust it to be a
        # plain name when building a path.
        if not _FILE_ID.match(file_id):
            raise ValueError("invalid file ID in the backup manifest")
        source = os.path.join(self._dir, file_id[:2], file_id)
        handle, partial = tempfile.mkstemp(dir=os.path.dirname(out_path))
        os.close(handle)
        try:
            shutil.copyfile(source, partial)
            os.replace(partial, out_path)
        except BaseException:
            if os.path.exists(partial):
                os.remove(partial)
            raise
        if mtime:
            os.utime(out_path, (mtime, mtime))

    def materialize(self, cur, file_id, domain, rel_path, size, mtime,
                    cache_dir):
        """Return a path to the file's data. Nothing is copied: the data
        is already plain in the backup folder."""
        if not _FILE_ID.match(file_id):
            raise ValueError("invalid file ID in the backup manifest")
        if size == 0:
            # Empty files have no data in the backup.
            path = os.path.join(cache_dir, file_id)
            if not os.path.exists(path):
                os.makedirs(cache_dir, exist_ok=True)
                open(path, "wb").close()
            return path
        source = os.path.join(self._dir, file_id[:2], file_id)
        if not os.path.isfile(source):
            raise FileNotFoundError(source)
        return source

    def close(self):
        self._conn.close()


OpenResult = collections.namedtuple("OpenResult", "domains total encrypted")


class BackupSession:
    """Owns the opened backup and runs every call on ONE worker thread.

    ``iphone_backup_decrypt`` keeps a SQLite connection to the decrypted
    manifest, and SQLite connections may only be used on the thread that
    created them. The public methods therefore never touch the backup
    directly: they queue the work on a single dedicated thread and return a
    ``concurrent.futures.Future``. That thread opens the backup, runs all
    queries and extractions, and releases it, so the connection is always
    used (and closed) where it was created.

    Encrypted and unencrypted backups are both handled here; the type is
    detected from the backup's Manifest.plist.
    """

    def __init__(self, backup_factory=None):
        self._factory = backup_factory or _default_backup_factory
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="backup-worker"
        )
        self._backup = None
        self._cancel = threading.Event()
        self._closed = False

    # ── Public API (any thread; each returns a Future) ───────

    def open(self, backup_dir, passphrase=None):
        """Open a backup. Future -> OpenResult(domains, total, encrypted).

        *passphrase* is only needed (and only used) for encrypted backups.
        """
        return self._executor.submit(self._open, backup_dir, passphrase)

    def scan(self, progress=None):
        """Read the whole manifest. Future -> list of rows
        ``(file_id, domain, relative_path, flags, size, mtime, birth)`` for
        every file (flags 1) and folder (flags 2).

        *progress(done, total)* is called now and then from the worker.
        """
        return self._executor.submit(self._scan, progress)

    def extract(self, file_ids, dest, progress=None):
        """Write files (decrypted if need be) into *dest*.

        Future -> ExtractionReport.
        """
        self._cancel.clear()
        return self._executor.submit(self._extract, list(file_ids), dest,
                                     progress)

    def extract_all(self, dest, progress=None):
        """Write every file in the backup into *dest*.

        Unlike extracting what is on screen, this reads the whole manifest,
        so it is not limited to the file list's row cap.
        Future -> ExtractionReport.
        """
        self._cancel.clear()
        return self._executor.submit(self._extract_all, dest, progress)

    def export_files(self, items, dest_dir):
        """Write backup files into *dest_dir* under names the caller picks.

        *items* are ``(file_id, name)``; each *name* must be a plain file
        name. Used to make working copies of databases and attachments for
        the app views. Future -> list of the names written.
        """
        return self._executor.submit(self._export_files, list(items),
                                     dest_dir)

    def list_all(self):
        """Every file in the backup.

        Future -> list of (file_id, domain, relative_path, size, mtime).
        """
        return self._executor.submit(self._list_all)

    def cache_file(self, file_id, cache_dir):
        """Make one file readable on disk. Future -> path.

        For an unencrypted backup the path is the data in the backup folder
        itself; for an encrypted one the file is decrypted into *cache_dir*
        on first use.
        """
        return self._executor.submit(self._cache_file, file_id, cache_dir)

    def cancel_extraction(self):
        self._cancel.set()

    def close(self):
        """Release the backup (and any temporary decrypted manifest)."""
        if self._closed:
            return
        self._closed = True
        self._cancel.set()
        self._executor.submit(self._discard)
        self._executor.shutdown(wait=False)

    # ── Worker-thread internals ──────────────────────────────

    def _discard(self):
        self._swap_backup(None)

    def _swap_backup(self, new_backup):
        # Releasing the old backup here keeps its SQLite connection (and,
        # for encrypted backups, the library's temporary decrypted
        # Manifest.db) on the thread that created it.
        old, self._backup = self._backup, new_backup
        if old is not None:
            old.close()
        del old

    def _require_backup(self):
        if self._backup is None:
            raise RuntimeError("No backup is open.")
        return self._backup

    def _open(self, backup_dir, passphrase):
        # The previously opened backup (if any) stays usable until the new
        # one has opened successfully.
        kind = detect_backup(backup_dir)
        if kind == ENCRYPTED:
            if not passphrase:
                raise PassphraseRequiredError(
                    "This backup is encrypted. Enter its password."
                )
            backup = EncryptedBackend(self._factory, backup_dir, passphrase)
        elif kind == EXTRACTED:
            backup = folder_backup.FolderBackend(backup_dir, fs_path)
        else:
            backup = PlainBackend(backup_dir)
        try:
            with backup.manifest_db_cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT domain FROM Files ORDER BY domain"
                )
                domains = [r[0] for r in cur.fetchall() if r[0]]
                cur.execute("SELECT COUNT(*) FROM Files WHERE flags=1")
                total = cur.fetchone()[0]
        except BaseException:
            # Do not let the traceback keep the half-open backup alive
            # past this thread.
            backup.close()
            backup = None
            raise
        self._swap_backup(backup)
        return OpenResult(domains, total, kind == ENCRYPTED)

    def _scan(self, progress):
        backup = self._require_backup()
        rows = []
        with backup.manifest_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM Files WHERE flags IN (1, 2)")
            total = cur.fetchone()[0]
            cur.execute("SELECT fileID, domain, relativePath, flags, file "
                        "FROM Files WHERE flags IN (1, 2)")
            for done, (file_id, domain, rel_path, flags, blob) in \
                    enumerate(cur, 1):
                size, mtime, birth = read_file_details(blob)
                rows.append((file_id, domain, rel_path, flags, size, mtime,
                             birth))
                if progress is not None and done % 5000 == 0:
                    progress(done, total)
        if progress is not None:
            progress(len(rows), total)
        return rows

    def _export_files(self, items, dest_dir):
        backup = self._require_backup()
        os.makedirs(dest_dir, exist_ok=True)
        written = []
        with backup.manifest_db_cursor() as cur:
            for file_id, name in items:
                if not name or name != os.path.basename(name) \
                        or name in (".", ".."):
                    raise ValueError(f"not a plain file name: {name!r}")
                cur.execute(
                    "SELECT domain, relativePath, file FROM Files "
                    "WHERE fileID=? AND flags=1", (file_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise FileNotFoundError(file_id)
                domain, rel_path, blob = row
                size, mtime = read_file_info(blob)
                out_path = fs_path(os.path.join(dest_dir, name))
                if size == 0:
                    open(out_path, "wb").close()
                else:
                    backup.extract(cur, file_id, domain, rel_path, mtime,
                                   out_path)
                written.append(name)
        return written

    def _extract_all(self, dest, progress):
        backup = self._require_backup()
        with backup.manifest_db_cursor() as cur:
            cur.execute("SELECT fileID FROM Files WHERE flags=1 "
                        "ORDER BY domain, relativePath")
            file_ids = [row[0] for row in cur.fetchall()]
        return self._extract(file_ids, dest, progress)

    def _list_all(self):
        return [
            (file_id, domain, rel_path, size or 0, mtime)
            for file_id, domain, rel_path, flags, size, mtime, _birth
            in self._scan(None)
            if flags == 1 and domain and rel_path
        ]

    def _cache_file(self, file_id, cache_dir):
        backup = self._require_backup()
        with backup.manifest_db_cursor() as cur:
            cur.execute(
                "SELECT domain, relativePath, file FROM Files "
                "WHERE fileID=? AND flags=1", (file_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise FileNotFoundError(file_id)
            domain, rel_path, blob = row
            size, mtime = read_file_info(blob)
            return backup.materialize(cur, file_id, domain, rel_path, size,
                                      mtime, cache_dir)

    def _extract(self, file_ids, dest, progress):
        backup = self._require_backup()
        report = ExtractionReport()
        used = set()
        total = len(file_ids)
        last_report = 0.0

        with backup.manifest_db_cursor() as cur:
            for n, file_id in enumerate(file_ids, 1):
                if self._cancel.is_set():
                    report.cancelled = True
                    break
                try:
                    self._extract_one(backup, cur, file_id, dest, used,
                                      report)
                except Exception as exc:
                    # Not listed in the manifest (or the manifest query
                    # itself failed): nothing better to show than the ID.
                    report.errors.append(
                        (file_id, f"{type(exc).__name__}: {exc}")
                    )
                if progress:
                    now = time.monotonic()
                    if n == total or now - last_report >= 0.1:
                        last_report = now
                        progress(n, total)
        return report

    def _extract_one(self, backup, cur, file_id, dest, used, report):
        cur.execute(
            "SELECT domain, relativePath, file FROM Files "
            "WHERE fileID=? AND flags=1", (file_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError("file is not listed in the backup manifest")
        domain, rel_path, blob = row
        label = f"{domain}/{rel_path}"
        try:
            if not domain or not rel_path:
                raise UnsafePathError("entry has no domain or path")
            out_path = fs_path(
                build_output_path(dest, domain, rel_path, file_id, used)
            )
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            size, mtime = read_file_info(blob)
            if size == 0:
                # Empty files have no key and no data in the backup.
                open(out_path, "wb").close()
                if mtime:
                    os.utime(out_path, (mtime, mtime))
            else:
                backup.extract(cur, file_id, domain, rel_path, mtime,
                               out_path)
            report.extracted += 1
        except UnsafePathError as exc:
            report.skipped.append((label, str(exc)))
        except Exception as exc:
            report.errors.append((label, f"{type(exc).__name__}: {exc}"))


class BackupExplorer:
    """Main application class for iOS Backup Explorer."""

    # Where iTunes / Finder / the Apple Devices app keep local backups.
    # Windows has two: the classic installer and the Microsoft Store app.
    BACKUP_PATHS = {
        "Windows": [
            os.path.expandvars(r"%APPDATA%\Apple Computer\MobileSync\Backup"),
            os.path.expandvars(r"%USERPROFILE%\Apple\MobileSync\Backup"),
        ],
        "Darwin": [
            os.path.expanduser(
                "~/Library/Application Support/MobileSync/Backup"
            ),
        ],
    }

    def __init__(self, root, session=None):
        self.root = root
        self.root.title(f"{APP_NAME} v{__version__}")
        self.root.geometry("1200x750")
        self.root.minsize(900, 620)

        self.session = session or BackupSession()
        self.backup_open = False
        self.backup_dir = None       # folder of the backup that is open
        self._opening_dir = None
        self._mount = None           # backup_mount.Mount while mounted
        self._mount_busy = False
        self.mount_btn = None
        self._index_request = 0      # discards out-of-date indexing runs
        self._app_panels = []        # the Messages tab, ...
        self._extracting = False
        self._backup_kind = None     # ENCRYPTED / UNENCRYPTED / None
        self._detect_job = None
        self._fit_job = None
        self._auto_path = None       # folder chosen by auto-detect

        # Worker threads must never call into Tk (it can hang at shutdown),
        # so they hand work to the Tk thread through this queue.
        self._ui_queue = queue.Queue()
        self._poll_job = None

        self._apply_style()
        self._build_ui()
        self.apps = AppContext(
            session=self.session, post=self._post,
            set_status=self.status_var.set, extract=self._extract_files)
        self._auto_detect_backup()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._drain_ui_queue()

    # ── Theming ──────────────────────────────────────────────

    @staticmethod
    def _system_font():
        """Return the best available font family for the current platform."""
        system = platform.system()
        if system == "Darwin":
            return "Helvetica Neue"
        elif system == "Windows":
            return "Segoe UI"
        return "DejaVu Sans"

    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        font = self._system_font()
        self._font_family = font

        # Warm, trustworthy palette
        self.colors = {
            "bg": "#faf7f2",
            "fg": "#2d2d2d",
            "surface": "#ffffff",
            "border": "#e5ddd0",
            "accent": "#d97706",       # warm amber
            "accent_hover": "#b45309",
            "green": "#059669",
            "green_light": "#d1fae5",
            "muted": "#6b7280",
            "heading": "#1f2937",
        }
        c = self.colors

        style.configure(".", background=c["bg"], foreground=c["fg"],
                         fieldbackground=c["surface"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=c["border"],
                        foreground=c["fg"], padding=(16, 6),
                        font=(font, 10, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", c["surface"])],
                  foreground=[("selected", c["accent"])])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"],
                         font=(font, 10))
        style.configure("Title.TLabel", background=c["bg"],
                         foreground=c["accent"], font=(font, 18, "bold"))
        style.configure("Subtitle.TLabel", background=c["bg"],
                         foreground=c["muted"], font=(font, 9))
        style.configure("Status.TLabel", background=c["green_light"],
                         foreground=c["green"], font=(font, 9),
                         padding=6)
        style.configure("TButton", background=c["accent"],
                         foreground="#ffffff", font=(font, 10, "bold"),
                         padding=8)
        style.map("TButton",
                   background=[("disabled", c["border"]),
                               ("active", c["accent_hover"])],
                   foreground=[("disabled", c["muted"]),
                               ("active", "#ffffff")])
        style.configure("Safe.TButton", background=c["green"],
                         foreground="#ffffff")
        style.map("Safe.TButton",
                   background=[("disabled", c["border"]),
                               ("active", "#047857")],
                   foreground=[("disabled", c["muted"])])
        style.configure("TEntry", fieldbackground=c["surface"],
                         foreground=c["fg"], insertcolor=c["fg"],
                         padding=4)
        style.map("TEntry", fieldbackground=[("disabled", c["bg"])],
                   foreground=[("disabled", c["muted"])])
        style.configure("Treeview", background=c["surface"],
                         foreground=c["fg"], fieldbackground=c["surface"],
                         font=(font, 9), rowheight=26)
        style.configure("Treeview.Heading", background=c["bg"],
                         foreground=c["heading"],
                         font=(font, 9, "bold"))
        style.map("Treeview",
                   background=[("selected", c["accent"])],
                   foreground=[("selected", "#ffffff")])
        style.configure("TLabelframe", background=c["bg"],
                         foreground=c["accent"])
        style.configure("TLabelframe.Label", background=c["bg"],
                         foreground=c["accent"],
                         font=(font, 10, "bold"))

    # ── UI Layout ────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=20, pady=(14, 0))
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Your data. Your eyes only.",
                  style="Subtitle.TLabel").pack(side="left", padx=(12, 0),
                                                 pady=(6, 0))

        # Privacy banner
        privacy_frame = ttk.Frame(self.root)
        privacy_frame.pack(fill="x", padx=20, pady=(6, 0))
        privacy_lbl = tk.Label(
            privacy_frame,
            text="  100% Offline  •  No data leaves your computer  "
                 "•  Open source  •  Your password is never stored  ",
            bg=self.colors["green_light"], fg=self.colors["green"],
            font=(self._system_font(), 9), padx=10, pady=4, anchor="w",
        )
        privacy_lbl.pack(fill="x")

        # Connection frame
        conn_frame = ttk.LabelFrame(self.root, text="Open Backup", padding=12)
        conn_frame.pack(fill="x", padx=20, pady=(10, 0))

        # Everything but the status line folds away once a backup is open,
        # to leave the room to what is in it.
        self.conn_body = ttk.Frame(conn_frame)
        self.conn_body.pack(fill="x")
        row1 = ttk.Frame(self.conn_body)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="Backup Folder:").pack(side="left")
        self.path_var = tk.StringVar()
        self.path_var.trace_add("write", lambda *a: self._schedule_detect())
        path_entry = ttk.Entry(row1, textvariable=self.path_var, width=75)
        path_entry.pack(side="left", padx=8)
        ttk.Button(row1, text="Browse...",
                    command=self._browse_folder).pack(side="left")

        row2 = ttk.Frame(self.conn_body)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="Password (encrypted backups):").pack(
            side="left")
        self.pass_var = tk.StringVar()
        self.pass_entry = ttk.Entry(row2, textvariable=self.pass_var,
                                     show="*", width=40)
        self.pass_entry.pack(side="left", padx=8)
        self.pass_entry.bind("<Return>", lambda e: self._decrypt())

        self.decrypt_btn = ttk.Button(row2, text="Open Backup",
                                       command=self._decrypt, style="Safe.TButton")
        self.decrypt_btn.pack(side="left", padx=8)

        self.status_var = tk.StringVar(
            value="Select a backup folder to begin. A password is only "
                  "needed for encrypted backups."
        )
        self._status_bar = ttk.Label(conn_frame, textvariable=self.status_var,
                                     style="Status.TLabel")
        self._status_bar.pack(fill="x", pady=(8, 0))
        self.change_btn = ttk.Button(conn_frame,
                                     text="Open another backup...",
                                     command=self._expand_connection)

        # The Files view, and a tab for each app found in the backup
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=10)
        self.panel = browser_panel.FileBrowserPanel(
            self.notebook, post=self._post, on_extract=self._extract_files,
            on_status=self.status_var.set, page_size=lambda: MAX_ROWS)
        self.notebook.add(self.panel, text="Files")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook.bind("<Configure>", self._schedule_fit_tabs)
        ttk.Button(self.panel.actions, text="Extract Entire Backup",
                   command=self._extract_entire).pack(side="left", padx=6)
        self.mount_btn = ttk.Button(self.panel.actions, text="Mount Backup",
                                    command=self._toggle_mount)
        self.mount_btn.pack(side="left")

    # The Files view's widgets, under the names used elsewhere.
    @property
    def domain_tree(self):
        return self.panel.domain_tree

    @property
    def file_tree(self):
        return self.panel.file_tree

    @property
    def search_var(self):
        return self.panel.search_var

    @property
    def count_var(self):
        return self.panel.count_var

    # ── Background work ──────────────────────────────────────

    def _post(self, func, *args):
        """Queue ``func(*args)`` to run on the Tk thread (thread-safe)."""
        self._ui_queue.put((func, args))

    def _drain_ui_queue(self):
        try:
            while True:
                func, args = self._ui_queue.get_nowait()
                try:
                    func(*args)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
        except queue.Empty:
            pass
        finally:
            self._poll_job = self.root.after(50, self._drain_ui_queue)

    def _when_done(self, future, callback):
        """Run ``callback(future)`` on the Tk thread once *future* is done."""
        future.add_done_callback(lambda fut: self._post(callback, fut))

    # ── Connection box ───────────────────────────────────────

    def _collapse_connection(self):
        self.conn_body.pack_forget()
        self.change_btn.pack(anchor="w", pady=(0, 6), before=self._status_bar)

    def _expand_connection(self):
        self.change_btn.pack_forget()
        self.conn_body.pack(fill="x", before=self._status_bar)

    # ── Auto-detect backup ───────────────────────────────────

    def _auto_detect_backup(self):
        newest = None
        blocked = False
        for base in self.BACKUP_PATHS.get(platform.system(), []):
            if not os.path.isdir(base):
                continue
            try:
                for name in os.listdir(base):
                    path = os.path.join(base, name)
                    if os.path.isdir(path) and (
                            newest is None
                            or os.path.getmtime(path)
                            > os.path.getmtime(newest)):
                        newest = path
            except OSError:
                # macOS blocks listing MobileSync/Backup unless the user
                # picks the folder in a file dialog.
                blocked = True
        if newest:
            # Pick the most recently modified backup
            self._auto_path = newest
            self.path_var.set(newest)
            self.status_var.set(
                f"Auto-detected backup: {os.path.basename(newest)}."
            )
            self._update_backup_kind()
        elif blocked:
            self.status_var.set(
                "The operating system is blocking automatic backup "
                "detection. Click Browse and select the backup folder "
                "(the long hex name inside MobileSync/Backup)."
            )

    # ── Folder browser ───────────────────────────────────────

    def _browse_folder(self):
        initial = next(
            (p for p in self.BACKUP_PATHS.get(platform.system(), [])
             if os.path.isdir(p)), None
        )
        path = filedialog.askdirectory(
            title="Select iPhone/iPad Backup Folder",
            initialdir=initial,
        )
        if path:
            self.path_var.set(path)

    # ── Backup type ──────────────────────────────────────────

    def _schedule_detect(self):
        """Check the chosen folder shortly after the user stops typing."""
        if self._detect_job is not None:
            self.root.after_cancel(self._detect_job)
        self._detect_job = self.root.after(300, self._update_backup_kind)

    def _update_backup_kind(self):
        """Adapt the password field and button to the chosen backup."""
        if self._detect_job is not None:
            self.root.after_cancel(self._detect_job)  # called directly
            self._detect_job = None
        path = self.path_var.get().strip()
        kind, problem = None, None
        if path and os.path.isdir(path):
            try:
                kind = detect_backup(path)
            except BackupFormatError as exc:
                problem = str(exc)
        self._backup_kind = kind

        unencrypted = kind in (UNENCRYPTED, EXTRACTED)
        self.pass_entry.configure(state="disabled" if unencrypted
                                  else "normal")
        self.decrypt_btn.configure(
            text="Decrypt & Open" if kind == ENCRYPTED else "Open Backup"
        )
        if self.decrypt_btn.instate(["disabled"]) or self._extracting:
            return  # an open is in progress; leave its status alone

        prefix = ""
        if path == self._auto_path:
            prefix = f"Auto-detected backup: {os.path.basename(path)}. "
        if kind == ENCRYPTED:
            self.status_var.set(
                prefix + "This backup is encrypted. Enter its password "
                "to decrypt it.")
        elif kind == EXTRACTED:
            self.status_var.set(
                prefix + "This folder is a backup that was already "
                "decrypted and extracted, so no password is needed. Click "
                "Open Backup.")
        elif unencrypted:
            self.status_var.set(
                prefix + "This backup is not encrypted, so no password is "
                "needed. Click Open Backup.")
        elif problem:
            self.status_var.set(problem)

    # ── Decryption ───────────────────────────────────────────

    def _decrypt(self):
        backup_dir = self.path_var.get().strip()
        # Not stripped: a backup password may contain leading/trailing spaces.
        passphrase = self.pass_var.get()

        if not backup_dir or not os.path.isdir(backup_dir):
            messagebox.showerror("Error", "Please select a valid backup folder.")
            return
        if self._mount is not None or self._mount_busy:
            messagebox.showinfo(
                "Info", "Unmount the current backup before opening another.")
            return
        try:
            kind = detect_backup(backup_dir)
        except BackupFormatError as exc:
            messagebox.showerror("Not a usable backup", str(exc))
            return
        if kind == ENCRYPTED and not passphrase:
            messagebox.showerror(
                "Error",
                "This backup is encrypted. Please enter the backup "
                "encryption password.",
            )
            return
        if kind in (UNENCRYPTED, EXTRACTED):
            passphrase = None  # never needed, never passed on

        self.decrypt_btn.configure(state="disabled")
        self.status_var.set(
            "Decrypting... this may take a moment." if kind == ENCRYPTED
            else "Opening backup..."
        )
        self.root.update_idletasks()

        self._opening_dir = backup_dir
        future = self.session.open(backup_dir, passphrase)
        self._when_done(
            future, lambda fut: self._on_open_done(fut, passphrase)
        )

    def _on_open_done(self, future, passphrase):
        error = future.exception()
        if error is not None:
            self._on_decrypt_fail(error, passphrase)
            return
        # Clear password from the UI after successful decryption
        self.pass_var.set("")
        result = future.result()
        self.backup_dir = self._opening_dir
        self._on_decrypt_success(result.domains, result.total,
                                 result.encrypted)

    def _on_decrypt_success(self, domains, total_files, encrypted=True):
        self.decrypt_btn.configure(state="normal")
        self.backup_open = True
        self._collapse_connection()
        self.status_var.set(
            f"{'Decrypted' if encrypted else 'Opened'}! {total_files:,} "
            f"files across {len(domains)} domains. Building the file index..."
        )
        self._start_indexing()

    def _on_decrypt_fail(self, error, passphrase=""):
        self.decrypt_btn.configure(state="normal")
        message = str(error) or type(error).__name__
        # Never echo the password back in an error message.
        if passphrase and len(passphrase) >= 4:
            message = message.replace(passphrase, "****")

        if isinstance(error, ImportError):
            self.status_var.set("Missing dependency. See error above.")
            messagebox.showerror(
                "Missing Dependency",
                "A required package could not be loaded:\n"
                f"  {message}\n\n"
                "Install the requirements by running:\n"
                "  pip install -r requirements.txt",
            )
        elif isinstance(error, BackupFormatError):
            self.status_var.set(f"Error: {message}")
            messagebox.showerror("Not a usable backup", message)
        elif isinstance(error, PassphraseRequiredError):
            self.status_var.set("This backup is encrypted. Enter its password.")
            messagebox.showerror("Password needed", message)
        elif is_wrong_passphrase(error):
            self.status_var.set("Incorrect password. Please try again.")
            messagebox.showerror(
                "Decryption Failed",
                "The password is incorrect. Please try again.\n\n"
                "Tip: This is the password you set when enabling\n"
                "encrypted backups in iTunes or Finder. Check for\n"
                "accidental leading or trailing spaces.",
            )
        else:
            self.status_var.set(f"Error: {message}")
            messagebox.showerror("Error",
                                  f"Failed to load backup:\n{message}")

    # ── Indexing ─────────────────────────────────────────────

    def _start_indexing(self):
        """Read the whole manifest once; browsing then needs no more SQL."""
        self._index_request += 1
        request = self._index_request
        self.panel.set_index(None)
        self._clear_app_tabs()
        self.apps.reset()

        def progress(done, total):
            self._post(self._show_index_progress, request, done, total)

        self._when_done(self.session.scan(progress),
                        lambda fut: self._on_scan_done(fut, request))

    def _show_index_progress(self, request, done, total):
        if request == self._index_request:
            self.status_var.set(
                f"Reading the backup index... {done:,} of {total:,}")

    def _on_scan_done(self, future, request):
        if request != self._index_request:
            return
        error = future.exception()
        if error is not None:
            self.status_var.set(
                f"Could not read the backup index: "
                f"{str(error) or type(error).__name__}")
            return
        rows = future.result()

        def build():
            try:
                index = FileIndex(rows)
            except Exception as exc:
                self._post(self.status_var.set,
                           f"Could not build the file index: {exc}")
                return
            self._post(self._on_index_ready, request, index)

        threading.Thread(target=build, daemon=True,
                         name="build-index").start()

    def _on_index_ready(self, request, index):
        if request != self._index_request:
            return
        self.panel.set_index(index)
        self.apps.index = index
        self.apps.backup_dir = self.backup_dir
        self._add_app_tabs(index)
        self.status_var.set(
            f"{index.file_count:,} files ready. Choose a folder on the "
            "left, or use the search box.")

    # ── App tabs ─────────────────────────────────────────────

    def _add_app_tabs(self, index):
        for entry in app_registry.available_apps(index):
            panel = entry.create(self.notebook, self.apps)
            self.notebook.add(panel, text=entry.title)
            self._app_panels.append(panel)
        self._schedule_fit_tabs()

    TAB_SIZES = ((16, 10), (10, 10), (8, 9), (6, 9), (4, 8))
    """(side padding, font size) for the tabs, from roomy to tight."""

    def _schedule_fit_tabs(self, _event=None):
        if self._fit_job is None:
            self._fit_job = self.root.after_idle(self._fit_tabs)

    def _fit_tabs(self):
        """With many tabs, give each less padding and a smaller font so that
        all of them fit in the window's width."""
        self._fit_job = None
        names = [self.notebook.tab(t, "text") for t in self.notebook.tabs()]
        width = self.notebook.winfo_width()
        if width <= 1 or not names:
            return
        for padding, size in self.TAB_SIZES:
            font = tkfont.Font(family=self._font_family, size=size,
                               weight="bold")
            needed = sum(font.measure(name) + 2 * padding + 6
                         for name in names)
            if needed <= width:
                break
        style = ttk.Style()
        style.configure("TNotebook.Tab", padding=(padding, 6),
                        font=(self._font_family, size, "bold"))

    def _clear_app_tabs(self):
        for panel in self._app_panels:
            panel.close()
            self.notebook.forget(panel)
            panel.destroy()
        self._app_panels = []

    def _on_tab_changed(self, event):
        current = self.notebook.nametowidget(self.notebook.select())
        if current in self._app_panels:
            current.activate()

    # ── Extraction ───────────────────────────────────────────

    def _extract_selected(self):
        self.panel.extract_selected()

    def _extract_all_view(self):
        self.panel.extract_all_in_view()

    def _extract_files(self, file_ids):
        if self._extracting:
            messagebox.showinfo("Info", "An extraction is already running.")
            return
        dest = filedialog.askdirectory(title="Select Output Folder")
        if not dest:
            return
        self._begin_extraction(
            lambda progress: self.session.extract(file_ids, dest, progress),
            dest, f"Extracting {len(file_ids)} files...")

    def _extract_entire(self):
        """Extract every file, straight from the manifest (no row cap).

        The idea for this button comes from Nikhil-42's upstream PR #1.
        """
        if not self.backup_open:
            messagebox.showinfo("Info", "Open a backup first.")
            return
        if self._extracting:
            messagebox.showinfo("Info", "An extraction is already running.")
            return
        dest = filedialog.askdirectory(
            title="Select Output Folder for the Entire Backup")
        if not dest:
            return
        if not messagebox.askyesno(
            "Extract entire backup",
            "This extracts every file in the backup into domain/"
            "relativePath folders (for example HomeDomain/Library/SMS/"
            "sms.db). It can take a long time and use a lot of disk space. "
            "Continue?",
        ):
            return
        self._begin_extraction(
            lambda progress: self.session.extract_all(dest, progress),
            dest, "Extracting the entire backup...")

    def _begin_extraction(self, start, dest, label):
        self._extracting = True
        self.status_var.set(label)
        self.root.update_idletasks()

        def progress(done, total):
            self._post(self._show_progress, done, total)

        future = start(progress)
        self._when_done(future, lambda fut: self._on_extract_done(fut, dest))

    def _show_progress(self, done, total):
        if self._extracting:
            self.status_var.set(f"Extracting... {done:,} of {total:,} files")

    def _on_extract_done(self, future, dest):
        self._extracting = False
        error = future.exception()
        if error is not None:
            msg = f"Extraction failed: {str(error) or type(error).__name__}"
            self.status_var.set(msg)
            messagebox.showerror("Error", msg)
            return

        report = future.result()
        msg = f"Extracted {report.extracted:,} files to {dest}"
        if report.errors:
            msg += f" ({len(report.errors)} errors)"
        if report.skipped:
            msg += f" ({len(report.skipped)} skipped)"
        if report.cancelled:
            msg += " (cancelled)"
        self.status_var.set(msg)

        problems = [f"{label}: {reason}"
                    for label, reason in report.errors + report.skipped]
        if problems:
            shown = "\n".join(problems[:10])
            more = len(problems) - 10
            if more > 0:
                shown += f"\n...and {more} more"
            messagebox.showwarning("Done, with problems",
                                    f"{msg}\n\n{shown}")
        else:
            messagebox.showinfo("Done", msg)

    # ── Mounting ─────────────────────────────────────────────

    def _toggle_mount(self):
        """Mount the open backup as a read-only file system, or unmount it.

        The idea of mounting a backup comes from Nikhil-42's upstream PR #2.
        """
        if self._mount_busy:
            return
        if self._mount is not None:
            self._unmount()
            return
        if not self.backup_open:
            messagebox.showinfo("Info", "Open a backup first.")
            return

        import backup_mount
        try:
            fuse = backup_mount.load_fuse()
        except backup_mount.MountUnavailableError as exc:
            messagebox.showerror("Mounting is not available", str(exc))
            return

        mountpoint = share = None
        if os.name == "nt":
            share = backup_mount.default_share_name(self.backup_dir or "")
            where = backup_mount.unc_path(share)
        else:
            mountpoint = filedialog.askdirectory(
                title="Select an EMPTY folder to mount the backup on")
            if not mountpoint:
                return
            if os.listdir(mountpoint):
                messagebox.showerror(
                    "Error", "The mount point folder must be empty.")
                return
            where = mountpoint
        if not messagebox.askyesno(
            "Mount backup",
            f"Mount this backup, read-only, at:\n\n    {where}\n\n"
            "While it is mounted, programs running as you can read the "
            "backup's decrypted contents. Files from an encrypted backup "
            "are decrypted into a private temporary folder the first time "
            "they are opened; that folder is deleted when you unmount.\n\n"
            "Continue?",
        ):
            return

        self._mount_busy = True
        self.mount_btn.configure(state="disabled")
        self.status_var.set("Reading the backup index...")
        cache_dir = tempfile.mkdtemp(prefix="ios-backup-explorer-")
        future = self.session.list_all()
        self._when_done(future, lambda fut: self._on_mount_rows(
            fut, backup_mount, fuse, mountpoint, share, cache_dir))

    def _on_mount_rows(self, future, backup_mount, fuse, mountpoint, share,
                       cache_dir):
        error = future.exception()
        if error is not None:
            self._mount_failed(cache_dir, error)
            return
        rows = future.result()
        session = self.session
        self.status_var.set("Mounting...")

        def fetch(file_id):
            return session.cache_file(file_id, cache_dir).result()

        def run():
            mount = None
            try:
                tree = backup_mount.BackupTree(rows)
                filesystem = backup_mount.BackupFilesystem(tree, fetch)
                mount = backup_mount.Mount(
                    filesystem, mountpoint=mountpoint, share=share,
                    cache_dir=cache_dir, fuse=fuse)
                mount.on_stopped = lambda: self._post(
                    self._on_mount_stopped, mount)
                mount.start()
            except Exception as exc:
                self._post(self._mount_failed, cache_dir, exc)
                return
            self._post(self._on_mounted, mount)

        threading.Thread(target=run, daemon=True, name="mount-start").start()

    def _mount_failed(self, cache_dir, error):
        shutil.rmtree(cache_dir, ignore_errors=True)
        self._mount_busy = False
        self.mount_btn.configure(state="normal")
        message = str(error) or type(error).__name__
        self.status_var.set("Mounting failed.")
        messagebox.showerror("Mount failed", message)

    def _on_mounted(self, mount):
        self._mount = mount
        self._mount_busy = False
        self.mount_btn.configure(state="normal", text="Unmount Backup")
        self.status_var.set(f"Mounted, read-only, at {mount.display_path}")
        if messagebox.askyesno(
            "Backup mounted",
            f"The backup is mounted at:\n\n    {mount.display_path}\n\n"
            "Open it now?",
        ):
            self._open_location(mount.display_path)

    @staticmethod
    def _open_location(path):
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                import subprocess
                opener = "open" if platform.system() == "Darwin" \
                    else "xdg-open"
                subprocess.Popen([opener, path])
        except Exception:
            pass  # just a convenience

    def _unmount(self):
        mount = self._mount
        self._mount_busy = True
        self.mount_btn.configure(state="disabled")
        self.status_var.set("Unmounting...")

        def run():
            stopped = mount.stop()
            self._post(self._on_unmounted, mount, stopped)

        threading.Thread(target=run, daemon=True, name="unmount").start()

    def _on_unmounted(self, mount, stopped):
        self._mount_busy = False
        self.mount_btn.configure(state="normal")
        if not stopped:
            self.status_var.set("Could not unmount. Close anything using it "
                                "and try again.")
            messagebox.showerror(
                "Unmount failed",
                "The backup could not be unmounted. Close any programs "
                "that are using it and try again.")
            return
        self._mount_gone(mount)

    def _on_mount_stopped(self, mount):
        """The file system ended without us asking (e.g. unmounted by hand)."""
        if self._mount is mount and not self._mount_busy:
            mount.stop()
            self._mount_gone(mount)

    def _mount_gone(self, mount):
        if self._mount is mount:
            self._mount = None
        self.mount_btn.configure(text="Mount Backup")
        self.status_var.set("Backup unmounted.")

    # ── Shutdown ─────────────────────────────────────────────

    def _on_close(self):
        if self._extracting and not messagebox.askyesno(
            "Extraction running", "An extraction is still running. Quit anyway?"
        ):
            return
        self._cancel_timers()
        self.panel.close()
        self._clear_app_tabs()
        self.apps.reset()
        if self._mount is not None:
            self._mount.stop()   # before the session its reads depend on
        self.session.close()
        self.root.destroy()

    def _cancel_timers(self):
        for job in (self._poll_job, self._detect_job, self._fit_job):
            if job is not None:
                self.root.after_cancel(job)
        self._poll_job = self._detect_job = self._fit_job = None
        self.panel.cancel_timers()
        for panel in self._app_panels:
            panel.cancel_timers()


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] in ("--version", "-V"):
        print(f"{APP_NAME} {__version__}")
        return
    root = tk.Tk()
    root.iconname(APP_NAME)
    BackupExplorer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
