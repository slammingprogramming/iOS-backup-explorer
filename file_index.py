# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the backup as a browsable folder tree
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

"""The backup as a folder tree you can navigate, sort and search.

Pure Python: no GUI and no SQLite, so it is fast to test and safe to use
from any thread once built. An iOS backup is a flat table of
``(domain, relativePath)`` entries; this turns it into
``domain / folder / folder / file`` with sizes, dates and totals.
"""

import os
import plistlib
import re
from datetime import datetime

# ── Reading the metadata blob ────────────────────────────────

def read_file_details(blob):
    """Return ``(size, mtime, birth)`` from a Manifest.db ``file`` blob.

    Any of them is ``None`` when it cannot be read. ``birth`` is the
    creation time iOS recorded, when it recorded one.
    """
    if not blob:
        return None, None, None
    try:
        meta = plistlib.loads(blob)
    except Exception:
        return None, None, None
    objects = meta.get("$objects") if isinstance(meta, dict) else None
    if not isinstance(objects, list):
        return None, None, None

    info = None
    try:
        info = objects[meta["$top"]["root"].data]
    except (KeyError, IndexError, AttributeError, TypeError):
        pass
    if not isinstance(info, dict):
        info = objects[1] if len(objects) > 1 else None
    if not isinstance(info, dict):
        return None, None, None

    def number(key, kind=(int, float)):
        value = info.get(key)
        return value if isinstance(value, kind) \
            and not isinstance(value, bool) else None

    return number("Size", int), number("LastModified"), number("Birth")


# ── Display helpers ──────────────────────────────────────────

def format_size(size):
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.2f} GB"


def format_time(stamp):
    """A local ``YYYY-MM-DD HH:MM`` string, or ``""`` if unknown."""
    if not stamp:
        return ""
    try:
        return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


_CATEGORY_NAMES = {
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


def category_for(domain):
    """The friendly group a domain is listed under (Apps, Photos, ...)."""
    base = domain.split("-")[0] if "-" in domain else domain
    if base.startswith("AppDomain"):
        return "Apps"
    if base.startswith("SysContainerDomain") or \
            base.startswith("SysSharedContainer"):
        return "System Containers"
    return _CATEGORY_NAMES.get(domain) or _CATEGORY_NAMES.get(base) \
        or "Other"


_KINDS = {
    "jpg": "JPEG image", "jpeg": "JPEG image", "png": "PNG image",
    "heic": "HEIC image", "heif": "HEIF image", "gif": "GIF image",
    "webp": "WebP image", "tiff": "TIFF image", "dng": "RAW image",
    "mov": "QuickTime movie", "mp4": "MP4 video", "m4v": "M4V video",
    "m4a": "M4A audio", "mp3": "MP3 audio", "aac": "AAC audio",
    "caf": "CAF audio", "wav": "WAV audio", "amr": "AMR audio",
    "txt": "Text document", "pdf": "PDF document", "rtf": "Rich text",
    "html": "HTML document", "json": "JSON file", "xml": "XML file",
    "csv": "CSV file", "log": "Log file",
    "plist": "Property list", "strings": "Strings file",
    "sqlite": "Database", "sqlite3": "Database", "db": "Database",
    "sqlitedb": "Database", "storedata": "Database",
    "sqlite-wal": "Database journal", "sqlite-shm": "Database journal",
    "db-wal": "Database journal", "db-shm": "Database journal",
    "vcf": "vCard contact", "ics": "Calendar event",
    "zip": "ZIP archive", "gz": "GZ archive",
}


def kind_of(node):
    """A short description of a node, like a file manager's Type column."""
    if node.is_dir:
        return "Folder"
    extension = os.path.splitext(node.name)[1].lstrip(".").lower()
    if not extension:
        return "File"
    return _KINDS.get(extension, f"{extension.upper()} file")


# ── The tree ─────────────────────────────────────────────────

class Node:
    """A folder or a file. Folders have ``children``; files have ``file_id``."""

    __slots__ = ("name", "parent", "children", "file_id", "size", "mtime",
                 "birth", "count", "total")

    def __init__(self, name, parent=None, directory=False):
        self.name = name
        self.parent = parent
        self.children = {} if directory else None
        self.file_id = None
        self.size = 0        # files: bytes
        self.mtime = None    # modification time (epoch seconds) or None
        self.birth = None    # creation time (epoch seconds) or None
        self.count = 0       # folders: files inside, recursively
        self.total = 0       # folders: bytes inside, recursively

    @property
    def is_dir(self):
        return self.children is not None

    @property
    def weight(self):
        """The size shown for it: a folder's is everything inside it."""
        return self.total if self.is_dir else self.size

    def __repr__(self):
        return f"<Node {'dir' if self.is_dir else 'file'} {self.name!r}>"


class FileIndex:
    """The whole backup as a tree of :class:`Node`.

    *rows* are ``(file_id, domain, relative_path, flags, size, mtime,
    birth)``: flags 1 are files, 2 are folders (other kinds are ignored).
    *progress*, if given, is called as ``progress(done)`` now and then.
    """

    def __init__(self, rows, progress=None):
        self.root = Node("", None, True)
        self.file_count = 0
        self.total_size = 0
        for done, row in enumerate(rows, 1):
            file_id, domain, rel_path, flags, size, mtime, birth = row
            if not domain:
                continue
            parts = [domain] + [p for p in (rel_path or "").split("/") if p]
            if flags == 1 and len(parts) > 1:
                self._add_file(file_id, parts, size or 0, mtime, birth)
            elif flags == 2:
                node = self._directory(parts)
                node.mtime, node.birth = mtime, birth
            if progress is not None and done % 5000 == 0:
                progress(done)
        self.domains = sorted(self.root.children.values(),
                              key=lambda n: n.name.lower())

    def _directory(self, parts):
        node = self.root
        for part in parts:
            child = node.children.get(part)
            if child is not None and not child.is_dir:
                # A file already has this name: put the folder beside it.
                part = f"{part} (folder)"
                child = node.children.get(part)
            if child is None:
                child = Node(part, node, True)
                node.children[part] = child
            node = child
        return node

    def _add_file(self, file_id, parts, size, mtime, birth):
        parent = self._directory(parts[:-1])
        name = parts[-1]
        if name in parent.children:
            name = f"{name} ({file_id[:8]})"
        node = Node(name, parent, False)
        node.file_id, node.size = file_id, size
        node.mtime, node.birth = mtime, birth
        parent.children[name] = node
        self.file_count += 1
        self.total_size += size
        while parent is not None:
            parent.count += 1
            parent.total += size
            parent = parent.parent

    # -- looking things up ------------------------------------

    @staticmethod
    def path_of(node):
        parts = []
        while node is not None and node.name:
            parts.append(node.name)
            node = node.parent
        return "/".join(reversed(parts))

    @staticmethod
    def domain_of(node):
        while node.parent is not None and node.parent.name:
            node = node.parent
        return node.name

    def get(self, path):
        """The node at ``Domain/folder/...`` (``""`` is the top), or None."""
        node = self.root
        for part in path.split("/"):
            if not part:
                continue
            if not node.is_dir:
                return None
            node = node.children.get(part)
            if node is None:
                return None
        return node

    @staticmethod
    def walk_files(scope):
        """Every file inside *scope*, depth first."""
        stack = [scope]
        while stack:
            node = stack.pop()
            if node.is_dir:
                stack.extend(reversed(list(node.children.values())))
            else:
                yield node

    def search(self, scope, text):
        """Files under *scope* whose ``Domain/path`` contains every word of
        *text*, ignoring case."""
        words = text.lower().split()
        found = []
        # The top and a category pseudo-folder have no parent and add
        # nothing to the path; a real folder's path is its prefix.
        stack = [(scope, self.path_of(scope).lower()
                  if scope.parent is not None else "")]
        while stack:
            node, prefix = stack.pop()
            for child in node.children.values():
                path = f"{prefix}/{child.name.lower()}" if prefix \
                    else child.name.lower()
                if child.is_dir:
                    stack.append((child, path))
                elif all(word in path for word in words):
                    found.append(child)
        return found

    def listing(self, scope, recursive=False, text=""):
        """What to show for *scope*: its folders and files, or (when
        *recursive* or searching) every file beneath it."""
        if text.strip():
            return self.search(scope, text)
        if recursive:
            return list(self.walk_files(scope))
        return list(scope.children.values())

    def category_scope(self, name):
        """A pseudo-folder holding the domains of one category."""
        scope = Node(name, None, True)
        for domain in self.domains:
            if category_for(domain.name) == name:
                scope.children[domain.name] = domain
        return scope

    def categories(self):
        """``{category: [domain nodes]}`` in display order."""
        groups = {}
        for domain in self.domains:
            groups.setdefault(category_for(domain.name), []).append(domain)
        return dict(sorted(groups.items()))


# ── Sorting ──────────────────────────────────────────────────

SORT_KEYS = ("name", "kind", "size", "modified", "created", "location")

_DIGITS = re.compile(r"(\d+)")


def natural_key(text):
    """Sort ``IMG_2`` before ``IMG_10``, ignoring case."""
    return [(0, int(part)) if part.isdigit() else (1, part)
            for part in _DIGITS.split(text.casefold()) if part]


def sort_nodes(nodes, key="name", descending=False, folders_first=True):
    """*nodes* ordered like a file manager would.

    Ties fall back to the name. Items with an unknown date always go last,
    whichever way the column is sorted.
    """
    if key not in SORT_KEYS:
        raise ValueError(f"cannot sort by {key!r}")
    ordered = sorted(nodes, key=lambda n: natural_key(n.name))   # tie-break
    if key == "name":
        if descending:
            ordered.reverse()
    elif key in ("modified", "created"):
        attr = "mtime" if key == "modified" else "birth"
        known = [n for n in ordered if getattr(n, attr) is not None]
        unknown = [n for n in ordered if getattr(n, attr) is None]
        known.sort(key=lambda n: getattr(n, attr), reverse=descending)
        ordered = known + unknown
    elif key == "size":
        ordered.sort(key=lambda n: n.weight, reverse=descending)
    elif key == "kind":
        ordered.sort(key=lambda n: kind_of(n).casefold(), reverse=descending)
    else:   # location
        cache = {}

        def where(node):
            parent = node.parent
            if id(parent) not in cache:
                cache[id(parent)] = natural_key(FileIndex.path_of(parent))
            return cache[id(parent)]

        ordered.sort(key=where, reverse=descending)
    if folders_first:
        ordered = ([n for n in ordered if n.is_dir]
                   + [n for n in ordered if not n.is_dir])
    return ordered
