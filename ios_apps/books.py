# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Books reader
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

"""Reads Apple Books: the library, the purchases the store lists, the
collections, and the highlights and notes made while reading. No GUI.

The backup this reader was written against held the Books databases but no
books, so the library and annotation layouts follow what is documented for
them and the store list and collections follow the tables of that backup;
the reader takes the first of several possible column names for each thing
and is tested on generated databases. Whatever is missing is left empty.
"""

import os

from .common import own_path, apple_time, format_datetime
from .records import Column, Dataset, fetch_dicts, open_copies

IBOOKS = "AppDomainGroup-group.com.apple.iBooks/Documents"
LIBRARY_FOLDER = f"{IBOOKS}/BKLibrary"
ANNOTATION_FOLDER = f"{IBOOKS}/AEAnnotation"
STORE_LIST = (f"{IBOOKS}/BKJaliscoServerSource/"
              "BKJaliscoServerSource-v09182016.sqlite")
COLLECTIONS = (f"{IBOOKS}/BCCloudData-BookDataStoreService/"
               "BCCloudCollections/BCCloudCollections")


def _files(index, folder, prefix):
    node = index.get(folder) if index is not None else None
    if node is None or not node.is_dir:
        return []
    return [f"{folder}/{name}" for name, child in sorted(node.children.items())
            if not child.is_dir and name.startswith(prefix)
            and name.endswith(".sqlite")]


def discover(index):
    """The Books databases of the backup (backup paths), the library
    first."""
    found = _files(index, LIBRARY_FOLDER, "BKLibrary")
    found += _files(index, ANNOTATION_FOLDER, "AEAnnotation")
    for path in (STORE_LIST, COLLECTIONS):
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            found.append(path)
    return found


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _date(value):
    return apple_time(value) if isinstance(value, (int, float)) \
        and value else None


def library_rows(conn):
    rows = []
    for item in fetch_dicts(conn, "ZBKLIBRARYASSET", [
            "ZASSETID", "ZTITLE", "ZAUTHOR", "ZGENRE", "ZLASTOPENDATE",
            "ZREADINGPROGRESS", "ZPURCHASEDATE", "ZISSTOREAUDIOBOOK",
            "ZCONTENTTYPE", "ZPATH", "ZISHIDDEN", "ZISSAMPLE"]):
        progress = item["ZREADINGPROGRESS"]
        rows.append({
            "title": _text(item["ZTITLE"]), "author": _text(item["ZAUTHOR"]),
            "genre": _text(item["ZGENRE"]),
            "progress": round(progress * 100)
            if isinstance(progress, (int, float)) and 0 <= progress <= 1
            else None,
            "opened": _date(item["ZLASTOPENDATE"]),
            "bought": _date(item["ZPURCHASEDATE"]),
            "kind": "Audiobook" if item["ZISSTOREAUDIOBOOK"] else "Book",
            "sample": "sample" if item["ZISSAMPLE"] else "",
            "hidden": "hidden" if item["ZISHIDDEN"] else "",
            "id": _text(item["ZASSETID"])})
    return rows


def store_rows(conn):
    """The books the store says were bought (they may not be on the
    phone)."""
    rows = []
    for item in fetch_dicts(conn, "ZBLJALISCOSERVERITEM", [
            "ZTITLE", "ZARTIST", "ZGENRE", "ZPURCHASEDAT", "ZSTOREID",
            "ZISAUDIOBOOK", "ZISHIDDEN"]):
        rows.append({
            "title": _text(item["ZTITLE"]), "author": _text(item["ZARTIST"]),
            "genre": _text(item["ZGENRE"]), "opened": None,
            "bought": _date(item["ZPURCHASEDAT"]), "progress": None,
            "kind": "Audiobook" if item["ZISAUDIOBOOK"] else "Book",
            "sample": "", "hidden": "hidden" if item["ZISHIDDEN"] else "",
            "id": _text(str(item["ZSTOREID"] or ""))})
    return rows


def collection_rows(conn):
    return [{"name": _text(item["ZNAME"]) or "(no name)",
             "description": _text(item["ZCOLLECTIONDESCRIPTION"]),
             "hidden": "hidden" if item["ZHIDDEN"] else "",
             "changed": _date(item["ZMODIFICATIONDATE"])}
            for item in fetch_dicts(conn, "ZBCCOLLECTIONDETAIL", [
                "ZNAME", "ZCOLLECTIONDESCRIPTION", "ZHIDDEN",
                "ZMODIFICATIONDATE", "ZDELETEDFLAG"])
            if not item["ZDELETEDFLAG"]]


def annotation_rows(conn, titles):
    rows = []
    for item in fetch_dicts(conn, "ZAEANNOTATION", [
            "ZANNOTATIONASSETID", "ZANNOTATIONSELECTEDTEXT",
            "ZANNOTATIONNOTE", "ZANNOTATIONCREATIONDATE",
            "ZANNOTATIONMODIFICATIONDATE", "ZANNOTATIONDELETED"]):
        if item["ZANNOTATIONDELETED"]:
            continue
        text, note = _text(item["ZANNOTATIONSELECTEDTEXT"]), \
            _text(item["ZANNOTATIONNOTE"])
        if not text and not note:
            continue
        asset = _text(item["ZANNOTATIONASSETID"])
        rows.append({
            "book": titles.get(asset, asset), "text": text, "note": note,
            "when": _date(item["ZANNOTATIONCREATIONDATE"])
            or _date(item["ZANNOTATIONMODIFICATIONDATE"])})
    return rows


def _book_details(row):
    lines = [row["title"] or "(no title)"]
    for label, text in (("Author", row["author"]), ("Genre", row["genre"]),
                        ("Kind", row["kind"]),
                        ("Read", f"{row['progress']}%"
                         if row["progress"] is not None else ""),
                        ("Last opened", format_datetime(row["opened"])),
                        ("Bought", format_datetime(row["bought"]))):
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def _note_details(row):
    lines = [row["book"]]
    if row["text"]:
        lines.append(f"“{row['text']}”")
    if row["note"]:
        lines.append(f"Note: {row['note']}")
    if row["when"]:
        lines.append(format_datetime(row["when"]))
    return "\n".join(lines)


def datasets(conn, folder, backup_paths):
    """*backup_paths* are the databases copied beside *conn*."""
    library, store, collections, notes = [], [], [], []
    with open_copies(conn, backup_paths) as found:
        for path in backup_paths:
            other = found.get(path)
            if other is None:
                continue
            name = os.path.basename(path)
            if name.startswith("BKLibrary"):
                library += library_rows(other)
            elif path == STORE_LIST:
                store += store_rows(other)
            elif path == COLLECTIONS:
                collections += collection_rows(other)
        titles = {r["id"]: r["title"] for r in library + store if r["id"]}
        for path in backup_paths:
            other = found.get(path)
            if other is not None and os.path.basename(path).startswith(
                    "AEAnnotation"):
                notes += annotation_rows(other, titles)
    # a purchase the library does not show is added from the store's list
    known = {r["id"] for r in library if r["id"]}
    library += [r for r in store if r["id"] not in known]
    result = []
    if library:
        result.append(Dataset("books", "Books", [
            Column("title", "Title", 320), Column("author", "Author", 200),
            Column("kind", "Kind", 80),
            Column("progress", "Read %", 60, "number", "e"),
            Column("opened", "Last opened", 130, "date"),
            Column("bought", "Bought", 130, "date"),
            Column("hidden", "", 60)],
            library, sort=("title", False), details=_book_details))
    if notes:
        result.append(Dataset("notes", "Highlights and notes", [
            Column("when", "When", 130, "date"),
            Column("book", "Book", 220), Column("text", "Highlight", 380),
            Column("note", "Note", 240)],
            notes, sort=("when", True), details=_note_details))
    if collections:
        result.append(Dataset("collections", "Collections", [
            Column("name", "Collection", 260),
            Column("description", "Description", 360),
            Column("changed", "Changed", 130, "date"),
            Column("hidden", "", 60)],
            collections, sort=("name", False)))
    return result


class BooksReader:
    def __init__(self, conn, index):
        self.conn, self.index = conn, index

    def datasets(self):
        own = own_path(self.conn)
        return datasets(self.conn, os.path.dirname(own),
                        discover(self.index))
