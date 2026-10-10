# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — a backup that was already extracted to folders
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

"""Opening a backup that has already been decrypted and extracted.

Tools that decrypt a backup (and this app's own *Extract Entire Backup*)
leave a folder with one sub-folder per domain
(``HomeDomain/Library/SMS/sms.db``, ``AppDomain-com.example.app/...``) and
no ``Manifest.db``. :class:`FolderBackend` presents such a folder to the
rest of the app the way a real backup looks: it builds an index in memory
(the same ``Files`` table a ``Manifest.db`` has) from what is on disk and
reads the files from where they are. The folder is never written to.
"""

import contextlib
import hashlib
import os
import plistlib
import shutil
import sqlite3
import tempfile

_SUFFIXES = ("Domain", "DomainGroup", "DomainPlugin")


def looks_like_domain(name):
    """Whether a folder name is a backup domain: ``HomeDomain``,
    ``AppDomain-com.apple.mobilesafari``, ``AppDomainGroup-group...``,
    ``SysSharedContainerDomain-systemgroup...``."""
    return name.split("-", 1)[0].endswith(_SUFFIXES)


def looks_extracted(path):
    """Whether *path* holds an extracted backup: sub-folders named like
    backup domains, and no ``Manifest`` files of a real backup."""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    if any(n in ("Manifest.db", "Manifest.mbdb", "Manifest.plist")
           for n in names):
        return False
    return any(looks_like_domain(n) and os.path.isdir(os.path.join(path, n))
               for n in names)


def file_record(size, mtime, birth=None):
    """A ``file`` blob like the ones in ``Manifest.db`` (an archived
    dictionary), holding what the app reads from it."""
    record = {"Size": int(size), "Mode": 0o100644}
    if mtime:
        record["LastModified"] = int(mtime)
    if birth:
        record["Birth"] = int(birth)
    return plistlib.dumps(
        {"$archiver": "NSKeyedArchiver", "$objects": ["$null", record],
         "$top": {"root": plistlib.UID(1)}, "$version": 100000},
        fmt=plistlib.FMT_BINARY)


def file_id_for(domain, relative_path):
    """The ID a real backup would give the file: SHA-1 of ``domain-path``."""
    return hashlib.sha1(f"{domain}-{relative_path}".encode("utf-8",
                                                          "surrogateescape")
                        ).hexdigest()


class FolderBackend:
    """An extracted backup folder, read-only."""

    def __init__(self, root, fs_path=lambda path: path):
        self._root = os.path.abspath(root)
        self._fs = fs_path
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, "
            "relativePath TEXT, flags INTEGER, file BLOB)")
        self._conn.execute("CREATE INDEX by_domain ON Files (domain)")
        self._populate()

    # -- the index --------------------------------------------

    def _populate(self):
        rows = []
        for name in sorted(os.listdir(self._fs(self._root))):
            top = os.path.join(self._root, name)
            if looks_like_domain(name) and os.path.isdir(self._fs(top)):
                self._walk(name, top, "", rows)
        self._conn.executemany("INSERT OR IGNORE INTO Files VALUES "
                               "(?, ?, ?, ?, ?)", rows)
        self._conn.commit()

    def _walk(self, domain, folder, prefix, rows):
        try:
            entries = list(os.scandir(self._fs(folder)))
        except OSError:
            return                      # unreadable folder: leave it out
        for entry in entries:
            relative = prefix + entry.name
            try:
                if entry.is_symlink():
                    continue            # (never follow a link out of the tree)
                if entry.is_dir(follow_symlinks=False):
                    rows.append((file_id_for(domain, relative), domain,
                                 relative, 2, file_record(0, 0)))
                    self._walk(domain, os.path.join(folder, entry.name),
                               relative + "/", rows)
                elif entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    birth = getattr(stat, "st_birthtime", None) or (
                        stat.st_ctime if os.name == "nt" else None)
                    rows.append((file_id_for(domain, relative), domain,
                                 relative, 1,
                                 file_record(stat.st_size, stat.st_mtime,
                                             birth)))
            except OSError:
                continue

    @contextlib.contextmanager
    def manifest_db_cursor(self):
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    # -- the files --------------------------------------------

    def _source(self, domain, rel_path):
        """Where a file is on disk. *domain* and *rel_path* come from the
        index built from the disk, but are checked all the same."""
        parts = [domain] + rel_path.split("/")
        separators = [x for x in (os.sep, os.altsep) if x]
        if any(p in ("", ".", "..") or any(x in p for x in separators)
               for p in parts):
            raise ValueError("unsafe path in the extracted backup")
        return os.path.join(self._root, *parts)

    def extract(self, cur, file_id, domain, rel_path, mtime, out_path):
        source = self._fs(self._source(domain, rel_path))
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
        """A path to the file's data. Nothing is copied: the file is
        already where it is."""
        if size == 0:
            path = os.path.join(cache_dir, file_id)
            if not os.path.exists(path):
                os.makedirs(cache_dir, exist_ok=True)
                open(path, "wb").close()
            return path
        source = self._source(domain, rel_path)
        if not os.path.isfile(self._fs(source)):
            raise FileNotFoundError(source)
        return source

    def close(self):
        self._conn.close()
