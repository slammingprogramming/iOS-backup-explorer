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

from .common import apple_time, format_datetime
from .export_util import write_text_file
from .records import Column, Dataset, fetch_dicts, sqlite_rows

DATABASES = (
    "AppDomainGroup-group.com.apple.Maps/Maps/MapsSync_0.0.1",
    "AppDomainGroup-group.com.apple.Maps/Maps/MapsSync_0.0.1_deviceLocalCache.db")
DATABASE = DATABASES[0]


def discover(index):
    found = []
    for path in DATABASES:
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


def collection_rows(conn):
    """``(collections, places)``: the guides and the places in them."""
    members = {}
    for collection, place in sqlite_rows(
            conn, "SELECT Z_5COLLECTIONS, Z_6PLACES FROM Z_5PLACES"):
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


def _details(row):
    lines = [row.get("name") or row.get("search") or row.get("collection")
             or "(no name)"]
    for label, key in (("Address", "address"), ("Search", "search"),
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
        return datasets(self.conn)
