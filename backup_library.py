# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the backups on this computer, and looking after them
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

"""Finding every backup on the computer, saying what each one is (which
device, which iOS, when, encrypted or not, finished or interrupted, how big)
and managing them: copy one to another drive, move it, check that its files
are all there, delete it. The same on Windows, macOS and Linux, with or
without iTunes, Finder or the Apple Devices app, and for backups kept
anywhere, not only where those programs keep theirs.

No GUI and no device here, and nothing is ever changed by looking: only
:func:`copy_backup`, :func:`move_backup` and :func:`delete_backup` write, and
each refuses anything that does not look like a backup of this program's
kind.
"""

import dataclasses
import datetime
import os
import pathlib
import plistlib
import shutil
import sqlite3
import stat
import sys

import file_index

APP_FOLDER_NAME = "iOS Backup Explorer"


class Cancelled(Exception):
    """The person stopped a copy or a check."""


class NotABackup(ValueError):
    """A folder that is not a backup (or not one to be touched)."""


# ── Where backups are ─────────────────────────────────────────

def own_backup_folder(system, environ, home):
    """Where this program puts backups it makes itself, unless the person
    chooses another place: a folder of its own in the user's data folder,
    so nothing of Apple's is ever touched without being asked."""
    if system == "Windows":
        base = environ.get("LOCALAPPDATA") or os.path.join(
            home, "AppData", "Local")
        return os.path.join(base, APP_FOLDER_NAME, "Backups")
    if system == "Darwin":
        return os.path.join(home, "Library", "Application Support",
                            APP_FOLDER_NAME, "Backups")
    base = environ.get("XDG_DATA_HOME") or os.path.join(
        home, ".local", "share")
    return os.path.join(base, "ios-backup-explorer", "Backups")


def default_locations(system, environ, home):
    """The folders that usually hold backups on this kind of computer, as
    ``[(path, who keeps them)]``: where iTunes, Finder and the Apple Devices
    app keep them, and this program's own folder (the place on Linux, where
    nothing else has one)."""
    found = []
    if system == "Windows":
        appdata = environ.get("APPDATA") or os.path.join(
            home, "AppData", "Roaming")
        profile = environ.get("USERPROFILE") or home
        found.append((os.path.join(appdata, "Apple Computer", "MobileSync",
                                   "Backup"), "iTunes"))
        found.append((os.path.join(profile, "Apple", "MobileSync", "Backup"),
                      "Apple Devices app, Microsoft Store iTunes"))
    elif system == "Darwin":
        found.append((os.path.join(home, "Library", "Application Support",
                                   "MobileSync", "Backup"), "Finder"))
    found.append((own_backup_folder(system, environ, home),
                  f"{APP_FOLDER_NAME}"))
    return found


# ── What a backup is ──────────────────────────────────────────

@dataclasses.dataclass
class BackupEntry:
    """One backup folder and what its own files say about it."""
    path: str
    location: str = ""
    udid: str = ""
    device_name: str = ""
    model: str = ""
    version: str = ""
    build: str = ""
    serial: str = ""
    made: object = None            # datetime or None
    encrypted: object = None       # True / False / None (not known)
    complete: object = None        # True / False / None (not known)
    full: object = None
    size: object = None            # bytes, filled by folder_size

    @property
    def folder_name(self):
        return os.path.basename(self.path.rstrip("\\/"))

    @property
    def title(self):
        return self.device_name or self.folder_name


def _plist(path):
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError, EOFError):
        return None
    except Exception:       # a damaged file: any parser error
        return None
    return data if isinstance(data, dict) else None


def _date(value):
    return value if isinstance(value, datetime.datetime) else None


def looks_like_backup(path):
    """Does *path* hold the files that make a folder an iPhone backup?"""
    return os.path.isdir(path) and any(
        os.path.isfile(os.path.join(path, name))
        for name in ("Manifest.plist", "Info.plist", "Status.plist"))


def inspect_backup(path, location=""):
    """A :class:`BackupEntry` for the backup in *path*, or None when it is
    not one. Reads only the three small property lists."""
    if not looks_like_backup(path):
        return None
    entry = BackupEntry(path=os.path.abspath(path), location=location)
    info = _plist(os.path.join(path, "Info.plist")) or {}
    manifest = _plist(os.path.join(path, "Manifest.plist")) or {}
    status = _plist(os.path.join(path, "Status.plist")) or {}

    def text(*keys, source=info):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    entry.udid = text("Unique Identifier", "Target Identifier") \
        or entry.folder_name
    entry.device_name = text("Device Name", "Display Name")
    entry.model = text("Product Type")
    entry.version = text("Product Version")
    entry.build = text("Build Version")
    entry.serial = text("Serial Number")
    entry.made = (_date(status.get("Date")) or _date(manifest.get("Date"))
                  or _date(info.get("Last Backup Date")))
    encrypted = manifest.get("IsEncrypted")
    entry.encrypted = encrypted if isinstance(encrypted, bool) else None
    state = status.get("SnapshotState")
    if isinstance(state, str):
        entry.complete = state == "finished"
    full = status.get("IsFullBackup")
    entry.full = full if isinstance(full, bool) else None
    return entry


def find_backups(locations):
    """Every backup in *locations* (folders that hold backups; a location
    that is itself a backup counts too), newest first. *locations* is a list
    of paths or of ``(path, who)``. A folder that cannot be listed is
    skipped."""
    found, seen = [], set()
    for item in locations:
        location, who = item if isinstance(item, tuple) else (item, "")
        if not location or not os.path.isdir(location):
            continue
        candidates = [location] if looks_like_backup(location) else []
        try:
            names = sorted(os.listdir(location))
        except OSError:
            names = []
        candidates += [os.path.join(location, n) for n in names]
        for path in candidates:
            key = os.path.normcase(os.path.realpath(path))
            if key in seen or os.path.islink(path):
                continue
            entry = inspect_backup(path, who or location)
            if entry:
                seen.add(key)
                found.append(entry)
    found.sort(key=lambda e: e.made or datetime.datetime.min, reverse=True)
    return found


def folder_size(path, cancel=None):
    """The bytes of every file under *path* (links are not followed)."""
    total = 0
    stack = [path]
    while stack:
        if cancel and cancel():
            raise Cancelled()
        try:
            with os.scandir(stack.pop()) as scan:
                for item in scan:
                    try:
                        if item.is_symlink():
                            continue
                        if item.is_dir(follow_symlinks=False):
                            stack.append(item.path)
                        else:
                            total += item.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


# ── Writing: copy, move, delete ───────────────────────────────

def _require_backup(path):
    if os.path.islink(path) or not looks_like_backup(path):
        raise NotABackup(f"{path} is not a backup folder.")


def _is_inside(inner, outer):
    inner = os.path.normcase(os.path.realpath(inner))
    outer = os.path.normcase(os.path.realpath(outer))
    return inner == outer or inner.startswith(outer.rstrip(os.sep) + os.sep)


def copy_backup(source, destination_folder, progress=None, cancel=None):
    """Copy the backup *source* into *destination_folder* (which may be on
    another drive). It is copied under a temporary name and renamed when
    complete, so an interrupted copy never looks like a backup; it is
    checked (same files, same sizes) before that. Returns the new path.
    *progress(done_bytes, total_bytes)* is called as it goes; *cancel()*
    returning true stops it and removes what was copied."""
    _require_backup(source)
    if _is_inside(destination_folder, source):
        raise NotABackup("A backup cannot be copied into itself.")
    name = os.path.basename(os.path.abspath(source).rstrip("\\/"))
    target = os.path.join(destination_folder, name)
    if os.path.lexists(target):
        raise FileExistsError(
            f"{target} already exists. Choose another folder.")
    os.makedirs(destination_folder, exist_ok=True)
    partial = target + ".copying"
    if os.path.lexists(partial):
        shutil.rmtree(partial, ignore_errors=True)
    total = folder_size(source, cancel)
    done = 0
    copied_files = copied_bytes = 0
    try:
        os.makedirs(partial)
        for root, dirs, files in os.walk(source):
            relative = os.path.relpath(root, source)
            where = partial if relative == "." else os.path.join(partial,
                                                                 relative)
            os.makedirs(where, exist_ok=True)
            dirs[:] = [d for d in dirs
                       if not os.path.islink(os.path.join(root, d))]
            for name_ in files:
                if cancel and cancel():
                    raise Cancelled()
                src = os.path.join(root, name_)
                if os.path.islink(src):
                    continue
                dst = os.path.join(where, name_)
                shutil.copyfile(src, dst)
                shutil.copystat(src, dst, follow_symlinks=False)
                size = os.path.getsize(dst)
                done += size
                copied_files += 1
                copied_bytes += size
                if progress:
                    progress(done, total)
        if copied_bytes != total:
            raise OSError(f"The copy has {copied_bytes:,} bytes where the "
                          f"backup has {total:,}.")
        os.replace(partial, target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return target


def delete_backup(path, locations):
    """Delete the backup folder *path*. Only a folder that is a backup, that
    sits directly in one of *locations* and is not a link may go, so a wrong
    path can never reach anything else. This does not use the recycle bin: a
    backup is often tens of gigabytes."""
    _require_backup(path)
    parent = os.path.dirname(os.path.abspath(path).rstrip("\\/"))
    allowed = [os.path.normcase(os.path.realpath(
        l[0] if isinstance(l, tuple) else l)) for l in locations]
    if os.path.normcase(os.path.realpath(parent)) not in allowed:
        raise NotABackup(
            f"{path} is not in one of the folders this program manages.")

    def writable(function, target, _exc):
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        function(target)

    # (Python 3.12 renamed the hook; this one ignores what differs)
    hook = "onexc" if sys.version_info >= (3, 12) else "onerror"
    shutil.rmtree(path, **{hook: writable})


def move_backup(source, destination_folder, locations, progress=None,
                cancel=None):
    """Move a backup to another folder: copied and checked first, and only
    then removed from where it was. Returns the new path."""
    target = copy_backup(source, destination_folder, progress, cancel)
    try:
        delete_backup(source, locations)
    except NotABackup:
        pass                      # (copied; the original stays where it was)
    return target


# ── Checking ──────────────────────────────────────────────────

@dataclasses.dataclass
class CheckReport:
    """What a check found. ``ok`` is true when nothing is wrong *that could
    be looked at*; ``complete_check`` says whether every file could be.
    ``wrong_size`` only counts files whose size differs from the list, which
    is not a fault (see :func:`check_backup`)."""
    ok: bool = True
    complete_check: bool = True
    files: int = 0
    missing: int = 0
    wrong_size: int = 0
    problems: list = dataclasses.field(default_factory=list)
    note: str = ""

    def problem(self, text):
        self.ok = False
        if len(self.problems) < 50:
            self.problems.append(text)


def check_backup(path, progress=None, cancel=None):
    """Are the files of the backup all there? For an unencrypted backup this
    reads the list of files (``Manifest.db``) and looks for each one's data,
    at the size the list gives; an encrypted backup's list cannot be read
    without its password, so only the parts that can be seen are checked
    (the three property lists, that the list is there, that the interrupted
    state is not recorded) and the report says so."""
    _require_backup(path)
    report = CheckReport()
    entry = inspect_backup(path)
    for name in ("Manifest.plist", "Manifest.db"):
        if not os.path.isfile(os.path.join(path, name)):
            report.problem(f"{name} is missing.")
    if entry.complete is False:
        report.problem("The backup was interrupted: the device did not "
                       "finish it. Make a new backup to complete it.")
    if entry.encrypted:
        report.complete_check = False
        report.note = ("The backup is encrypted, so its list of files "
                       "cannot be compared with the folder without its "
                       "password. Open it in the program to use it.")
        return report
    manifest = os.path.join(path, "Manifest.db")
    if not os.path.isfile(manifest):
        report.complete_check = False
        return report
    conn = sqlite3.connect(pathlib.Path(manifest).as_uri()
                           + "?mode=ro&immutable=1", uri=True)
    try:
        rows = conn.execute("SELECT fileID, flags, file FROM Files")
    except sqlite3.DatabaseError as error:
        conn.close()
        report.problem(f"Manifest.db cannot be read ({error}).")
        report.complete_check = False
        return report
    try:
        for count, (file_id, flags, blob) in enumerate(rows, 1):
            if cancel and cancel():
                raise Cancelled()
            if flags != 1 or not file_id:       # folders, links
                continue
            report.files += 1
            data = os.path.join(path, file_id[:2], file_id)
            try:
                actual = os.path.getsize(data)
            except OSError:
                report.missing += 1
                report.problem(f"Missing: {file_id[:2]}/{file_id}")
                continue
            expected, _mtime = _size_and_time(blob)
            if expected is not None and expected != actual:
                # not an error: a phone lists the size a database had before
                # it compacted it for the backup, so healthy backups have
                # many such files
                report.wrong_size += 1
            if progress and count % 500 == 0:
                progress(count)
    except sqlite3.DatabaseError as error:
        report.problem(f"Manifest.db is damaged ({error}).")
    finally:
        conn.close()
    if report.wrong_size and not report.missing:
        report.note = (f"{report.wrong_size:,} files are not the size the "
                       "list gives. That is normal for databases, which the "
                       "phone compacts as it backs them up.")
    return report


def _size_and_time(blob):
    size, mtime, _birth = file_index.read_file_details(blob)
    return size, mtime
