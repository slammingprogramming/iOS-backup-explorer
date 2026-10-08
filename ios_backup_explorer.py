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
from datetime import datetime

__version__ = "1.0.0"
APP_NAME = "iOS Backup Explorer"

# The file list shows at most this many rows. The status bar says so when
# a query matched more, and the search box queries the whole backup.
MAX_ROWS = 10000

# Rows per "domain IN (...)" query; SQLite builds limit bound variables.
_DOMAIN_CHUNK = 500


# ── Helpers (no GUI) ─────────────────────────────────────────

def format_size(size):
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.2f} GB"


def escape_like(text):
    """Escape SQL LIKE wildcards so *text* matches literally (ESCAPE '\\')."""
    return (text.replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def read_file_info(blob):
    """Return ``(size, mtime)`` from a Manifest.db ``file`` blob.

    Either value is ``None`` when it cannot be read.
    """
    if not blob:
        return None, None
    try:
        meta = plistlib.loads(blob)
    except Exception:
        return None, None
    objects = meta.get("$objects") if isinstance(meta, dict) else None
    if not isinstance(objects, list):
        return None, None

    info = None
    try:
        info = objects[meta["$top"]["root"].data]
    except (KeyError, IndexError, AttributeError, TypeError):
        pass
    if not isinstance(info, dict):
        info = objects[1] if len(objects) > 1 else None
    if not isinstance(info, dict):
        return None, None

    size = info.get("Size")
    mtime = info.get("LastModified")
    return (size if isinstance(size, int) else None,
            mtime if isinstance(mtime, (int, float)) else None)


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

_FILE_ID = re.compile(r"[0-9a-f]{40}\Z")


class BackupFormatError(ValueError):
    """The folder is not an iOS backup this app can open."""


class PassphraseRequiredError(ValueError):
    """The backup is encrypted but no password was given."""


def detect_backup(backup_dir):
    """Return ENCRYPTED or UNENCRYPTED for the backup in *backup_dir*.

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
        raise BackupFormatError(
            "This folder has no Manifest.plist, so it does not look like an "
            "iOS backup. Select the long hex-named folder inside "
            "MobileSync/Backup."
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

    def close(self):
        # Dropping the last reference runs the library's cleanup here, on
        # the thread that owns its SQLite connection, and deletes its
        # temporary decrypted Manifest.db.
        self._lib = None


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

    def query_files(self, domains=None, search="", limit=MAX_ROWS):
        """List files. Future -> (rows, total_matching).

        *domains* is a list of domains, or None for the whole backup.
        Each row is (file_id, domain, relative_path, size_str, mod_str).
        """
        return self._executor.submit(self._query_files, domains, search,
                                     limit)

    def extract(self, file_ids, dest, progress=None):
        """Write files (decrypted if need be) into *dest*.

        Future -> ExtractionReport.
        """
        self._cancel.clear()
        return self._executor.submit(self._extract, list(file_ids), dest,
                                     progress)

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

    def _query_files(self, domains, search, limit):
        backup = self._require_backup()
        if domains is not None and not domains:
            return [], 0

        where = ["flags=1"]
        params = []
        if search:
            where.append("(domain LIKE ? ESCAPE '\\' "
                         "OR relativePath LIKE ? ESCAPE '\\')")
            pattern = "%" + escape_like(search) + "%"
            params += [pattern, pattern]

        chunks = [None] if domains is None else [
            domains[i:i + _DOMAIN_CHUNK]
            for i in range(0, len(domains), _DOMAIN_CHUNK)
        ]
        raw_rows = []
        total = 0
        with backup.manifest_db_cursor() as cur:
            for chunk in chunks:
                clauses = list(where)
                chunk_params = list(params)
                if chunk is not None:
                    clauses.append(
                        "domain IN (%s)" % ",".join("?" * len(chunk))
                    )
                    chunk_params += chunk
                condition = " AND ".join(clauses)

                cur.execute("SELECT COUNT(*) FROM Files WHERE " + condition,
                            chunk_params)
                total += cur.fetchone()[0]

                remaining = limit - len(raw_rows)
                if remaining > 0:
                    cur.execute(
                        "SELECT fileID, domain, relativePath, file "
                        "FROM Files WHERE " + condition +
                        " ORDER BY domain, relativePath LIMIT ?",
                        chunk_params + [remaining],
                    )
                    raw_rows.extend(cur.fetchall())
        return self._display_rows(raw_rows), total

    @staticmethod
    def _display_rows(raw_rows):
        rows = []
        for file_id, domain, rel_path, blob in raw_rows:
            size, mtime = read_file_info(blob)
            size_str = format_size(size) if size else ""
            mod_str = ""
            if mtime:
                try:
                    mod_str = datetime.fromtimestamp(mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                except (OverflowError, OSError, ValueError):
                    pass
            rows.append((file_id, domain or "", rel_path or "", size_str,
                         mod_str))
        return rows

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
        self.root.minsize(900, 550)

        self.session = session or BackupSession()
        self.backup_open = False
        self._scope_domains = None   # None = every domain
        self._scope_set = False
        self._request_id = 0         # discards out-of-date file lists
        self._search_job = None
        self._extracting = False
        self._backup_kind = None     # ENCRYPTED / UNENCRYPTED / None
        self._detect_job = None
        self._auto_path = None       # folder chosen by auto-detect

        # Worker threads must never call into Tk (it can hang at shutdown),
        # so they hand work to the Tk thread through this queue.
        self._ui_queue = queue.Queue()
        self._poll_job = None

        self._apply_style()
        self._build_ui()
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
                   background=[("active", c["accent_hover"])],
                   foreground=[("active", "#ffffff")])
        style.configure("Safe.TButton", background=c["green"],
                         foreground="#ffffff")
        style.map("Safe.TButton",
                   background=[("active", "#047857")])
        style.configure("TEntry", fieldbackground=c["surface"],
                         foreground=c["fg"], insertcolor=c["fg"],
                         padding=4)
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

        row1 = ttk.Frame(conn_frame)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="Backup Folder:").pack(side="left")
        self.path_var = tk.StringVar()
        self.path_var.trace_add("write", lambda *a: self._schedule_detect())
        path_entry = ttk.Entry(row1, textvariable=self.path_var, width=75)
        path_entry.pack(side="left", padx=8)
        ttk.Button(row1, text="Browse...",
                    command=self._browse_folder).pack(side="left")

        row2 = ttk.Frame(conn_frame)
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
        status_bar = ttk.Label(conn_frame, textvariable=self.status_var,
                                style="Status.TLabel")
        status_bar.pack(fill="x", pady=(8, 0))

        # Main content
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=20, pady=10)

        # Left: categories
        left_frame = ttk.LabelFrame(paned, text="Categories", padding=6)
        paned.add(left_frame, weight=1)

        self.domain_tree = ttk.Treeview(left_frame, show="tree",
                                         selectmode="browse")
        domain_scroll = ttk.Scrollbar(left_frame, orient="vertical",
                                       command=self.domain_tree.yview)
        self.domain_tree.configure(yscrollcommand=domain_scroll.set)
        self.domain_tree.pack(side="left", fill="both", expand=True)
        domain_scroll.pack(side="right", fill="y")
        self.domain_tree.bind("<<TreeviewSelect>>", self._on_domain_select)

        # Right: file list
        right_frame = ttk.LabelFrame(paned, text="Files", padding=6)
        paned.add(right_frame, weight=3)

        toolbar = ttk.Frame(right_frame)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._schedule_search())
        ttk.Entry(toolbar, textvariable=self.search_var, width=35).pack(
            side="left", padx=8)
        self.count_var = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.count_var,
                  style="Subtitle.TLabel").pack(side="right")
        ttk.Button(toolbar, text="Extract Selected",
                    command=self._extract_selected).pack(side="right", padx=6)
        ttk.Button(toolbar, text="Extract All in View",
                    command=self._extract_all_view).pack(side="right", padx=2)

        cols = ("domain", "path", "size", "modified")
        self.file_tree = ttk.Treeview(right_frame, columns=cols,
                                       show="headings", selectmode="extended")
        self.file_tree.heading("domain", text="Domain")
        self.file_tree.heading("path", text="Relative Path")
        self.file_tree.heading("size", text="Size")
        self.file_tree.heading("modified", text="Modified")
        self.file_tree.column("domain", width=160, minwidth=100)
        self.file_tree.column("path", width=400, minwidth=200)
        self.file_tree.column("size", width=80, minwidth=60)
        self.file_tree.column("modified", width=140, minwidth=100)

        fy = ttk.Scrollbar(right_frame, orient="vertical",
                            command=self.file_tree.yview)
        fx = ttk.Scrollbar(right_frame, orient="horizontal",
                            command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=fy.set, xscrollcommand=fx.set)
        # Pack order matters: bottom scrollbar first, then right, then tree
        fx.pack(side="bottom", fill="x")
        fy.pack(side="right", fill="y")
        self.file_tree.pack(side="left", fill="both", expand=True)

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

        unencrypted = kind == UNENCRYPTED
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
        if kind == UNENCRYPTED:
            passphrase = None  # never needed, never passed on

        self.decrypt_btn.configure(state="disabled")
        self.status_var.set(
            "Decrypting... this may take a moment." if kind == ENCRYPTED
            else "Opening backup..."
        )
        self.root.update_idletasks()

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
        self._on_decrypt_success(result.domains, result.total,
                                 result.encrypted)

    def _on_decrypt_success(self, domains, total_files, encrypted=True):
        self.decrypt_btn.configure(state="normal")
        self.backup_open = True
        self._scope_set = False
        self._scope_domains = None
        self._request_id += 1
        self.file_tree.delete(*self.file_tree.get_children())
        self.count_var.set("")
        self.status_var.set(
            f"{'Decrypted' if encrypted else 'Opened'}! {total_files:,} "
            f"files across {len(domains)} domains."
        )
        self.domain_tree.delete(*self.domain_tree.get_children())

        categories = {}
        friendly = {
            "CameraRollDomain": "Camera Roll / Photos",
            "MediaDomain": "Media (Music, Videos)",
            "HomeDomain": "Home / Settings",
            "HealthDomain": "Health Data",
            "KeychainDomain": "Keychain",
            "WirelessDomain": "Wireless / Network",
            "ManagedPreferencesDomain": "Managed Preferences",
            "RootDomain": "Root / System",
            "SystemPreferencesDomain": "System Preferences",
            "DatabaseDomain": "Databases",
            "InstallDomain": "Installed Apps",
            "SysContainerDomain": "System Containers",
            "SysSharedContainerDomain": "Shared Containers",
        }

        self.domain_tree.insert("", "end", iid="__ALL__",
                                 text=f"All Files ({total_files:,})")

        for domain in domains:
            base = domain.split("-")[0] if "-" in domain else domain
            name = friendly.get(domain, friendly.get(base, None))

            if base.startswith("AppDomain"):
                cat = "Apps"
            elif base.startswith("SysContainerDomain") or \
                    base.startswith("SysSharedContainer"):
                cat = "System Containers"
            elif name:
                cat = name
            else:
                cat = "Other"

            categories.setdefault(cat, []).append(domain)

        for cat in sorted(categories):
            cat_id = f"__CAT__{cat}"
            self.domain_tree.insert(
                "", "end", iid=cat_id,
                text=f"{cat} ({len(categories[cat])})",
            )
            for domain in sorted(categories[cat]):
                self.domain_tree.insert(cat_id, "end", iid=domain,
                                         text=domain)

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

    # ── File loading ─────────────────────────────────────────

    def _on_domain_select(self, event):
        sel = self.domain_tree.selection()
        if not sel or not self.backup_open:
            return
        selected = sel[0]
        if selected == "__ALL__":
            self._scope_domains = None
        elif selected.startswith("__CAT__"):
            self._scope_domains = list(self.domain_tree.get_children(selected))
        else:
            self._scope_domains = [selected]
        self._scope_set = True
        self._refresh_files()

    def _schedule_search(self):
        """Re-query shortly after the user stops typing."""
        if not self.backup_open:
            return
        if self._search_job is not None:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(300, self._refresh_files)

    def _refresh_files(self):
        self._search_job = None
        if not self.backup_open:
            return
        if not self._scope_set:
            # Searching before choosing a category searches the whole backup.
            self._scope_domains = None
            self._scope_set = True

        self._request_id += 1
        request_id = self._request_id
        self.status_var.set(
            "Waiting for the running extraction to finish..."
            if self._extracting else "Loading files..."
        )
        future = self.session.query_files(
            self._scope_domains, self.search_var.get().strip(), MAX_ROWS
        )
        self._when_done(
            future, lambda fut: self._on_files_loaded(fut, request_id)
        )

    def _on_files_loaded(self, future, request_id):
        if request_id != self._request_id:
            return  # a newer selection or search superseded this one
        error = future.exception()
        if error is not None:
            self.status_var.set(
                f"Error loading: {str(error) or type(error).__name__}"
            )
            return
        rows, total = future.result()
        self._populate_files(rows, total)

    def _populate_files(self, rows, total):
        self.file_tree.delete(*self.file_tree.get_children())
        for file_id, domain, rel_path, size_str, mod_str in rows:
            self.file_tree.insert("", "end", iid=file_id,
                                   values=(domain, rel_path, size_str, mod_str))

        if total > len(rows):
            self.count_var.set(f"{len(rows):,} of {total:,} files")
            self.status_var.set(
                f"Showing the first {len(rows):,} of {total:,} matching "
                "files. Narrow the category or use the search box to "
                "see the rest."
            )
        else:
            self.count_var.set(f"{len(rows):,} files")
            self.status_var.set(f"Loaded {len(rows):,} files.")

    # ── Extraction ───────────────────────────────────────────

    def _extract_selected(self):
        items = self.file_tree.selection()
        if not items:
            messagebox.showinfo("Info", "Select files to extract first.")
            return
        self._extract_files(items)

    def _extract_all_view(self):
        items = self.file_tree.get_children()
        if not items:
            messagebox.showinfo("Info", "No files to extract.")
            return
        if len(items) > 100:
            if not messagebox.askyesno(
                "Confirm", f"Extract {len(items):,} files?"
            ):
                return
        self._extract_files(items)

    def _extract_files(self, file_ids):
        if self._extracting:
            messagebox.showinfo("Info", "An extraction is already running.")
            return
        dest = filedialog.askdirectory(title="Select Output Folder")
        if not dest:
            return
        self._extracting = True
        self.status_var.set(f"Extracting {len(file_ids)} files...")
        self.root.update_idletasks()

        def progress(done, total):
            self._post(self._show_progress, done, total)

        future = self.session.extract(file_ids, dest, progress)
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

    # ── Shutdown ─────────────────────────────────────────────

    def _on_close(self):
        if self._extracting and not messagebox.askyesno(
            "Extraction running", "An extraction is still running. Quit anyway?"
        ):
            return
        self._cancel_timers()
        self.session.close()
        self.root.destroy()

    def _cancel_timers(self):
        for job in (self._poll_job, self._search_job, self._detect_job):
            if job is not None:
                self.root.after_cancel(job)
        self._poll_job = self._search_job = self._detect_job = None


def main():
    root = tk.Tk()
    root.iconname(APP_NAME)
    BackupExplorer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
