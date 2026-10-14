# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Maps reader
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

"""Reads Apple Maps: the favorites, the places in the guides (collections)
and the history of searches and places looked at. No GUI.

The layout (``MapsSync_0.0.1``) was taken from the tables of a real backup;
that backup had no places in it, so the reader is tested on generated
data. The name and address of a place that was saved from the map (rather
than named by the user) are inside a binary record that is not read: such
a place is listed with its coordinates.
"""

import os
import plistlib
import re

from . import protobuf_wire as pb
from .common import (apple_time, format_datetime, own_path,
                     table_columns)
from .export_util import write_text_file
from .records import Column, Dataset, fetch_dicts, sqlite_rows

DATABASES = (
    "AppDomainGroup-group.com.apple.Maps/Maps/MapsSync_0.0.1",
    "AppDomainGroup-group.com.apple.Maps/Maps/MapsSync_0.0.1_deviceLocalCache.db")
DATABASE = DATABASES[0]
# iOS 12 and earlier: the favorites are a property list holding protocol
# buffer records, not a database
LEGACY = "AppDomain-com.apple.Maps/Library/Maps/GeoBookmarks.plist"


def discover(index):
    found = []
    for path in DATABASES + (LEGACY,):
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            found.append(path)
    return found[:1]


def _stamp(value):
    return apple_time(value) if value else None


def _coordinate(lat, lon):
    """``(lat, lon)`` if both are real coordinates, else ``(None, None)``."""
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) \
            and -90 <= lat <= 90 and -180 <= lon <= 180 \
            and (lat or lon):
        return float(lat), float(lon)
    return None, None


def _place_text(lat, lon):
    return f"{lat:.5f}, {lon:.5f}" if lat is not None else ""


def favorite_rows(conn):
    rows = []
    for item in fetch_dicts(conn, "ZFAVORITEITEM", [
            "Z_PK", "ZCUSTOMNAME", "ZORIGINATINGADDRESSSTRING", "ZLATITUDE",
            "ZLONGITUDE", "ZCREATETIME", "ZHIDDEN"],
            order="Z_PK"):
        lat, lon = _coordinate(item["ZLATITUDE"], item["ZLONGITUDE"])
        rows.append({
            "name": (item["ZCUSTOMNAME"] or "").strip(),
            "address": (item["ZORIGINATINGADDRESSSTRING"] or "").strip(),
            "lat": lat, "lon": lon, "place": _place_text(lat, lon),
            "added": _stamp(item["ZCREATETIME"]),
            "hidden": "hidden" if item["ZHIDDEN"] else ""})
    return rows


def _membership(conn):
    """``(table, guide column, place column)`` of the table that says which
    places are in which guide. Core Data names it, and its columns, after the
    numbers of the two kinds it joins, which differ between iOS versions
    (``Z_5PLACES`` with ``Z_5COLLECTIONS`` and ``Z_6PLACES`` on iOS 16 and
    earlier, ``Z_6PLACES`` with ``Z_6COLLECTIONS`` and ``Z_7PLACES`` after)."""
    for (name,) in sqlite_rows(
            conn, "SELECT name FROM sqlite_master WHERE type = 'table' AND "
                  "name GLOB 'Z_[0-9]*PLACES'"):
        columns = table_columns(conn, name)
        guide = next((c for c in columns if re.fullmatch(
            r"Z_\d+COLLECTIONS", c)), None)
        place = next((c for c in columns if re.fullmatch(
            r"Z_\d+PLACES", c)), None)
        if guide and place:
            return name, guide, place
    return None


def collection_rows(conn):
    """``(collections, places)``: the guides and the places in them."""
    members = {}
    link = _membership(conn)
    for collection, place in (sqlite_rows(
            conn, f"SELECT {link[1]}, {link[2]} FROM {link[0]}")
            if link else ()):
        members.setdefault(collection, []).append(place)
    titles = {r["Z_PK"]: (r["ZTITLE"] or "").strip() for r in fetch_dicts(
        conn, "ZCOLLECTION", ["Z_PK", "ZTITLE"])}
    items = {}
    for item in fetch_dicts(conn, "ZCOLLECTIONITEM", [
            "Z_PK", "ZCUSTOMNAME", "ZLATITUDE", "ZLONGITUDE", "ZCREATETIME"]):
        items[item["Z_PK"]] = item
    places, counts = [], {}
    for collection, pks in members.items():
        for pk in pks:
            item = items.get(pk)
            if item is None:
                continue
            lat, lon = _coordinate(item["ZLATITUDE"], item["ZLONGITUDE"])
            places.append({
                "collection": titles.get(collection) or "(no title)",
                "name": (item["ZCUSTOMNAME"] or "").strip(),
                "lat": lat, "lon": lon, "place": _place_text(lat, lon),
                "added": _stamp(item["ZCREATETIME"])})
            counts[collection] = counts.get(collection, 0) + 1
    collections = [{"collection": title or "(no title)",
                    "places": counts.get(pk, 0)}
                   for pk, title in titles.items()]
    return collections, places


def history_rows(conn):
    rows = []
    for item in fetch_dicts(conn, "ZHISTORYITEM", [
            "Z_PK", "ZQUERY", "ZLOCATIONDISPLAY", "ZLATITUDE", "ZLONGITUDE",
            "ZCREATETIME"], order="ZCREATETIME DESC"):
        lat, lon = _coordinate(item["ZLATITUDE"], item["ZLONGITUDE"])
        rows.append({
            "when": _stamp(item["ZCREATETIME"]),
            "search": (item["ZQUERY"] or "").strip(),
            "name": (item["ZLOCATIONDISPLAY"] or "").strip(),
            "lat": lat, "lon": lon, "place": _place_text(lat, lon)})
    return rows


def _xml(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def write_gpx(base, rows):
    """A GPX file of the places that have coordinates (the format mapping
    programs import)."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="iOS Backup Explorer" '
             'xmlns="http://www.topografix.com/GPX/1/1">']
    for row in rows:
        if row.get("lat") is None:
            continue
        name = row.get("name") or row.get("search") or row.get("address") \
            or row["place"]
        lines.append(f'<wpt lat="{row["lat"]:.7f}" lon="{row["lon"]:.7f}">'
                     f"<name>{_xml(name)}</name></wpt>")
    lines.append("</gpx>")
    path = base + ".gpx"
    write_text_file(path, "\n".join(lines) + "\n")
    return [path]


# ── iOS 12 and earlier ───────────────────────────────────────

# Where the entries of ``GeoBookmarks.plist`` keep what they hold. Apple does
# not publish the layout, so what follows was found on a real iOS 12.4 backup,
# by listing every stored text field with examples and asking its owner what
# each held, and by comparing the result with what the Maps app shows. Each
# entry is a protocol buffer message; the numbers are paths of nested fields.
# The first path that has a text is used.
ENTRY_PATH = (5, 1, 1, 4)           # the repeated entries in a record
PLACE_FIELD = 8                     # an entry that holds a place has this
# An entry's place is of one of several kinds, told apart by which field of
# it is present. These are the kinds that have been identified.
KIND_NAMES = {1: "Place", 30: "Place", 5: "Address", 31: "Address",
              2: "Location"}
SEARCH_KIND = 26                    # a list of searches
SEARCH_PATH = (8, 26, 1)
NAME_PATHS = ((8, 1, 10, 3), (8, 1, 11, 3), (8, 30, 1))
ADDRESS_PATHS = ((8, 5, 1, 3, 11), (8, 31, 1, 101, 2, 11))
CITY_PATHS = ((8, 30, 5),)
PHONE_PATHS = ((8, 1, 2),)
WEB_PATHS = ((8, 1, 6),)
CATEGORY_PATHS = ((8, 1, 12, 4), (8, 30, 2), (9,))
LOCATION_PATH = (8, 2, 1)           # a message of two doubles (lat, lon)


def _first_text(entry, paths):
    for path in paths:
        for text in pb.texts_at(entry, path):
            if text.strip():
                return text.strip()
    return ""


def _location(entry):
    for message in pb.messages_at(entry, LOCATION_PATH):
        numbers = {field: value for field, wire, value in
                   pb.parse(message) or () if wire == pb.FIXED64}
        lat, lon = _coordinate(numbers.get(1), numbers.get(2))
        if lat is not None:
            return lat, lon
    return None, None


def _place_kind(entry):
    """The kind of place an entry holds (the number of the one field the
    place message has), or None if it holds none."""
    place = pb.messages_at(entry, (PLACE_FIELD,))
    fields = pb.parse(place[0]) if place else None
    return fields[0][0] if fields else None


def legacy_rows(path):
    """``(places, searches, empty, unread)`` from a ``GeoBookmarks.plist``:
    a row for each place of a kind that is read (a name, an address or a
    location), the texts of the searches, and how many entries are empty
    (left over from deletions) or are of a kind that is not read yet. Raises
    ``ValueError`` if the file is not a property list."""
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise ValueError(str(error)) from error
    records = ((data.get("MSPBookmarks") or {}).get("records") or {}) \
        if isinstance(data, dict) else {}
    rows, searches, empty, unread = [], [], 0, 0
    for record in records.values():
        contents = record.get("contents") if isinstance(record, dict) else None
        if not isinstance(contents, (bytes, bytearray)):
            continue
        for entry in pb.messages_at(bytes(contents), ENTRY_PATH):
            kind = _place_kind(entry)
            if kind is None:
                empty += 1
                continue
            if kind == SEARCH_KIND:
                searches += [s.strip() for s in pb.texts_at(entry, SEARCH_PATH)
                             if s.strip()]
                continue
            name = _first_text(entry, NAME_PATHS)
            address = _first_text(entry, ADDRESS_PATHS)
            lat, lon = _location(entry)
            if kind not in KIND_NAMES or not (
                    name or address or lat is not None):
                unread += 1
                continue
            rows.append({
                "kind": KIND_NAMES[kind], "name": name, "address": address,
                "city": _first_text(entry, CITY_PATHS),
                "phone": _first_text(entry, PHONE_PATHS),
                "web": _first_text(entry, WEB_PATHS),
                "category": _first_text(entry, CATEGORY_PATHS),
                "lat": lat, "lon": lon, "place": _place_text(lat, lon)})
    return rows, searches, empty, unread


def _plural(count, one, many):
    return f"{count:,} {one if count == 1 else many}"


def legacy_datasets(path):
    """The tables of an iOS 12 (or earlier) ``GeoBookmarks.plist``: the saved
    places and the searches."""
    try:
        rows, searches, empty, unread = legacy_rows(path)
    except ValueError:
        return []
    result = []
    gpx = {"gpx": ("Places (GPX, for mapping programs)", write_gpx)}
    if rows:
        left = []
        if empty:
            left.append(_plural(empty, "empty entry", "empty entries")
                        + " (left over from deletions)")
        if unread:
            left.append(_plural(unread, "entry", "entries")
                        + " of kinds this program does not read yet")
        result.append(Dataset("saved", "Saved places", [
            Column("name", "Name", 220), Column("kind", "Kind", 80),
            Column("address", "Address", 300),
            Column("phone", "Phone", 110), Column("web", "Web address", 180),
            Column("category", "Category", 110),
            Column("place", "Coordinates", 150)],
            rows, sort=("name", False), details=_details, formats=gpx,
            note="The places iOS 12 and earlier keep in the Maps file. It "
                 "holds more than the favorites the Maps app lists: "
                 "addresses and locations too, and nothing in it says which "
                 "is which. Only some store their coordinates; the others "
                 "are known by name and address."
                 + (" Not shown: " + ", ".join(left) + "." if left else "")))
    if searches:
        result.append(Dataset("searches", "Searches", [
            Column("search", "Searched for", 400)],
            [{"search": s} for s in searches],
            details=lambda row: row["search"]))
    return result


def _details(row):
    lines = [row.get("name") or row.get("search") or row.get("collection")
             or "(no name)"]
    for label, key in (("Address", "address"), ("City", "city"),
                       ("Phone", "phone"), ("Web address", "web"),
                       ("Category", "category"), ("Search", "search"),
                       ("Collection", "collection"), ("Place", "place")):
        if row.get(key) and row[key] not in lines:
            lines.append(f"{label}: {row[key]}")
    if row.get("added"):
        lines.append(f"Added: {format_datetime(row['added'])}")
    if row.get("when"):
        lines.append(f"When: {format_datetime(row['when'])}")
    return "\n".join(lines)


def datasets(conn):
    result = []
    gpx = {"gpx": ("Places (GPX, for mapping programs)", write_gpx)}
    favorites = favorite_rows(conn)
    if favorites:
        result.append(Dataset("favorites", "Favorites", [
            Column("name", "Name", 240), Column("address", "Address", 320),
            Column("place", "Coordinates", 150),
            Column("added", "Added", 130, "date"),
            Column("hidden", "", 60)],
            favorites, sort=("added", True), details=_details, formats=gpx))
    collections, places = collection_rows(conn)
    if places:
        result.append(Dataset("places", "Places in guides", [
            Column("collection", "Guide", 220), Column("name", "Place", 280),
            Column("place", "Coordinates", 150),
            Column("added", "Added", 130, "date")],
            places, sort=("collection", False), details=_details,
            formats=gpx))
    if collections:
        result.append(Dataset("collections", "Guides", [
            Column("collection", "Guide", 320),
            Column("places", "Places", 80, "number", "e")],
            collections, sort=("places", True)))
    history = history_rows(conn)
    if history:
        result.append(Dataset("history", "History", [
            Column("when", "When", 140, "date"),
            Column("search", "Searched for", 260),
            Column("name", "Place", 280),
            Column("place", "Coordinates", 150)],
            history, sort=("when", True), details=_details, formats=gpx))
    return result


class MapsReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        own = own_path(self.conn)
        if own.lower().endswith(".plist"):         # iOS 12 and earlier
            return legacy_datasets(own)
        return datasets(self.conn)
