# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading the camera roll
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

"""Lists the pictures and videos of the camera roll. No GUI.

The pictures themselves are found by looking in the backup's ``DCIM``
folders, so a camera roll is listed even if its library database is missing
or unreadable. When ``Photos.sqlite`` is there it adds what the files alone
do not say: when the picture was taken, favourites, hidden and recently
deleted items, the size in pixels, the length of a video, the place, and the
albums an item belongs to.
"""

import os
import re
import sqlite3
from dataclasses import dataclass, field

from .common import apple_time, table_columns
from .export_util import safe_name_with_extension

DCIM = "CameraRollDomain/Media/DCIM"
DATABASE = "CameraRollDomain/Media/PhotoData/Photos.sqlite"
_MEDIA_ROOT = "CameraRollDomain/Media/"

PICTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif",
                      ".tif", ".tiff", ".dng", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".3gp"}

PHOTO, VIDEO = "photo", "video"

_ASSET_JOIN = re.compile(r"^Z_\d+ASSETS$")


def kind_of(name):
    """``photo``, ``video`` or None (not a camera roll item)."""
    ext = os.path.splitext(name)[1].lower()
    if ext in PICTURE_EXTENSIONS:
        return PHOTO
    if ext in VIDEO_EXTENSIONS:
        return VIDEO
    return None


@dataclass
class MediaItem:
    path: str                      # in the backup, Domain/Media/DCIM/...
    name: str
    directory: str = ""            # DCIM/100APPLE
    file_id: str = ""
    size: int = 0
    taken: float = None            # when it was taken (or the file's date)
    taken_from: str = "file"       # "library" when Photos.sqlite said so
    kind: str = PHOTO
    favorite: bool = False
    hidden: bool = False
    trashed: bool = False
    width: int = 0
    height: int = 0
    duration: float = 0.0
    latitude: float = None
    longitude: float = None
    albums: list = field(default_factory=list)

    @property
    def extension(self):
        return os.path.splitext(self.name)[1].lower()

    @property
    def dimensions(self):
        return f"{self.width} × {self.height}" if self.width and self.height \
            else ""

    @property
    def location(self):
        if self.latitude is None or self.longitude is None:
            return ""
        return f"{self.latitude:.5f}, {self.longitude:.5f}"

    @property
    def type_label(self):
        ext = self.extension.lstrip(".").upper()
        return f"{'Video' if self.kind == VIDEO else 'Photo'} ({ext})"


def scan(index):
    """Every picture and video in the DCIM folders of the backup, from the
    file index alone. Date taken is the file's own date."""
    root = index.get(DCIM)
    if root is None or not root.is_dir:
        return []
    items = []
    for node in index.walk_files(root):
        kind = kind_of(node.name)
        if kind is None:
            continue
        path = index.path_of(node)
        directory = os.path.dirname(path)[len(_MEDIA_ROOT):]
        stamp = node.birth or node.mtime
        items.append(MediaItem(
            path, node.name, directory, node.file_id, node.size,
            float(stamp) if stamp else None, "file", kind))
    items.sort(key=lambda i: (i.directory.casefold(), i.name.casefold()))
    return items


def _item_key(directory, name):
    return f"{directory}/{name}".casefold()


def enrich(items, conn):
    """Add what ``Photos.sqlite`` knows to *items* (in place). Raises
    ``sqlite3.DatabaseError`` if the file is not a database. Items the
    library does not mention are left as they are."""
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    cols = table_columns(conn, "ZASSET")
    if not {"ZDIRECTORY", "ZFILENAME"} <= cols:
        return items
    by_key = {_item_key(i.directory, i.name): i for i in items}

    def col(name):
        return name if name in cols else "NULL"

    by_pk = {}
    for (pk, directory, name, date, kind, favorite, hidden, trashed, width,
         height, duration, latitude, longitude) in conn.execute(
            f"SELECT Z_PK, ZDIRECTORY, ZFILENAME, {col('ZDATECREATED')}, "
            f"{col('ZKIND')}, {col('ZFAVORITE')}, {col('ZHIDDEN')}, "
            f"{col('ZTRASHEDSTATE')}, {col('ZWIDTH')}, {col('ZHEIGHT')}, "
            f"{col('ZDURATION')}, {col('ZLATITUDE')}, {col('ZLONGITUDE')} "
            "FROM ZASSET"):
        item = by_key.get(_item_key(directory or "", name or ""))
        if item is None:
            continue
        by_pk[pk] = item
        taken = apple_time(date)
        if taken is not None:
            item.taken, item.taken_from = taken, "library"
        if kind in (0, 1):
            item.kind = VIDEO if kind == 1 else PHOTO
        item.favorite = bool(favorite)
        item.hidden = bool(hidden)
        item.trashed = bool(trashed)
        item.width, item.height = int(width or 0), int(height or 0)
        item.duration = float(duration or 0)
        if latitude is not None and longitude is not None \
                and -90 <= latitude <= 90 and -180 < longitude <= 180 \
                and (latitude or longitude):
            item.latitude, item.longitude = float(latitude), float(longitude)
    _read_albums(conn, by_pk)
    return items


def _read_albums(conn, by_pk):
    album_cols = table_columns(conn, "ZGENERICALBUM")
    if not {"ZTITLE"} <= album_cols:
        return
    trashed = "ZTRASHEDSTATE" if "ZTRASHEDSTATE" in album_cols else "0"
    titles = {pk: title for pk, title in conn.execute(
        f"SELECT Z_PK, ZTITLE FROM ZGENERICALBUM WHERE ZTITLE IS NOT NULL "
        f"AND ZTITLE != '' AND COALESCE({trashed}, 0) = 0")}
    for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        if not _ASSET_JOIN.match(table):
            continue
        join_cols = table_columns(conn, table)
        albums = next((c for c in join_cols if c.endswith("ALBUMS")), None)
        assets = next((c for c in join_cols if c.endswith("ASSETS")), None)
        if not albums or not assets:
            continue
        for album, asset in conn.execute(f"SELECT {albums}, {assets} "
                                         f"FROM {table}"):
            item = by_pk.get(asset)
            if item is not None and album in titles \
                    and titles[album] not in item.albums:
                item.albums.append(titles[album])


# ── Views of the list ────────────────────────────────────────

ALL, PHOTOS, VIDEOS, FAVORITES, HIDDEN, DELETED = (
    "all", "photos", "videos", "favorites", "hidden", "deleted")
SMART_ALBUMS = {ALL: "All items", PHOTOS: "Photos", VIDEOS: "Videos",
                FAVORITES: "Favorites", HIDDEN: "Hidden",
                DELETED: "Recently Deleted"}


def in_album(item, album):
    """Whether *item* belongs to the album *album*: one of the smart albums
    above, ``("album", title)`` or ``("folder", directory)``."""
    if album == ALL:           # everything except what was deleted or hidden
        return not item.trashed and not item.hidden
    if album == PHOTOS:
        return item.kind == PHOTO and not item.trashed and not item.hidden
    if album == VIDEOS:
        return item.kind == VIDEO and not item.trashed and not item.hidden
    if album == FAVORITES:
        return item.favorite and not item.trashed
    if album == HIDDEN:
        return item.hidden and not item.trashed
    if album == DELETED:
        return item.trashed
    kind, name = album
    if kind == "album":
        return name in item.albums and not item.trashed
    return item.directory == name and not item.trashed


SORTS = {
    "Date taken, newest first": (lambda i: i.taken or 0, True),
    "Date taken, oldest first": (lambda i: i.taken or 0, False),
    "Name": (lambda i: (i.name.casefold(), i.directory.casefold()), False),
    "Size, largest first": (lambda i: i.size, True),
    "Type": (lambda i: (i.kind, i.extension, i.name.casefold()), False),
}


def sort_items(items, how):
    key, descending = SORTS[how]
    return sorted(items, key=key, reverse=descending)


def search_items(items, text):
    """Items whose name, folder, album or place contains every word."""
    words = text.casefold().split()
    found = []
    for item in items:
        haystack = " ".join((item.name, item.directory, *item.albums,
                             item.location)).casefold()
        if all(w in haystack for w in words):
            found.append(item)
    return found


def albums_of(items):
    """``[(("album", title), count)]`` and ``[(("folder", dir), count)]`` for
    the user albums and DCIM folders that have items (the deleted ones
    are not counted)."""
    albums, folders = {}, {}
    for item in items:
        if item.trashed:
            continue
        for title in item.albums:
            albums[title] = albums.get(title, 0) + 1
        folders[item.directory] = folders.get(item.directory, 0) + 1
    return (
        [(("album", t), n) for t, n in sorted(albums.items(),
                                             key=lambda kv: kv[0].casefold())],
        [(("folder", d), n) for d, n in sorted(folders.items(),
                                              key=lambda kv: kv[0].casefold())])


def unique_names(items):
    """``{item.path: file name}`` with no two the same, even ignoring case: a
    picture called IMG_0001.JPG in two folders gets the folder's name in
    front of the second one."""
    used, names = set(), {}
    for item in items:
        name = safe_name_with_extension(item.name, "item")
        if name.casefold() in used:
            name = safe_name_with_extension(
                f"{item.directory.replace('/', '_')}_{item.name}", "item")
        base, ext = os.path.splitext(name)
        number = 1
        while name.casefold() in used:
            number += 1
            name = f"{base} ({number}){ext}"
        used.add(name.casefold())
        names[item.path] = name
    return names
