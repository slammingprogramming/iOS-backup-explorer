# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Podcasts reader
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

"""Reads the Podcasts app: the shows and the episodes with their play
state. No GUI.

The library database (``MTLibrary.sqlite``) was not in the backup this
reader was written against, so its tables and columns follow the layout
documented for it and the reader takes the first of several possible
column names for each thing; it is tested on generated databases. Whatever
is missing is simply left empty.
"""

from .common import apple_time, format_datetime
from .records import Column, Dataset, fetch_dicts

DATABASES = (
    "AppDomainGroup-243LU875E5.groups.com.apple.podcasts/Documents/"
    "MTLibrary.sqlite",
    "AppDomain-com.apple.podcasts/Documents/MTLibrary.sqlite",
    "AppDomain-com.apple.podcasts/Library/Documents/MTLibrary.sqlite")

SHOW_COLUMNS = ["Z_PK", "ZTITLE", "ZAUTHOR", "ZFEEDURL", "ZWEBPAGEURL",
                "ZSUBSCRIBED", "ZLASTDATEPLAYED", "ZADDEDDATE"]
EPISODE_COLUMNS = ["Z_PK", "ZPODCAST", "ZTITLE", "ZDURATION", "ZPUBDATE",
                   "ZFIRSTTIMEAVAILABLE", "ZLASTDATEPLAYED", "ZPLAYCOUNT",
                   "ZDOWNLOADDATE", "ZPLAYHEAD", "ZBOOKMARKTIME",
                   "ZHASBEENPLAYED", "ZENCLOSUREURL", "ZASSETURL"]


def discover(index):
    for path in DATABASES:
        node = index.get(path) if index is not None else None
        if node is not None and not node.is_dir:
            return [path]
    return []


def _first(row, *keys):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _date(value):
    return apple_time(value) if isinstance(value, (int, float)) \
        and value else None


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def show_rows(conn):
    shows = fetch_dicts(conn, "ZMTPODCAST", SHOW_COLUMNS)
    episodes = fetch_dicts(conn, "ZMTEPISODE", EPISODE_COLUMNS)
    counts, played = {}, {}
    for episode in episodes:
        counts[episode["ZPODCAST"]] = counts.get(episode["ZPODCAST"], 0) + 1
        if _first(episode, "ZLASTDATEPLAYED") or (
                episode["ZPLAYCOUNT"] or 0) > 0:
            played[episode["ZPODCAST"]] = played.get(
                episode["ZPODCAST"], 0) + 1
    rows = []
    for show in shows:
        rows.append({
            "id": show["Z_PK"], "title": _text(show["ZTITLE"]),
            "author": _text(show["ZAUTHOR"]),
            "feed": _text(show["ZFEEDURL"]),
            "page": _text(show["ZWEBPAGEURL"]),
            "following": "yes" if show["ZSUBSCRIBED"] else "",
            "episodes": counts.get(show["Z_PK"], 0),
            "played": played.get(show["Z_PK"], 0),
            "last": _date(show["ZLASTDATEPLAYED"]),
            "added": _date(show["ZADDEDDATE"])})
    return rows


def episode_rows(conn):
    titles = {s["Z_PK"]: _text(s["ZTITLE"]) for s in fetch_dicts(
        conn, "ZMTPODCAST", ["Z_PK", "ZTITLE"])}
    rows = []
    for episode in fetch_dicts(conn, "ZMTEPISODE", EPISODE_COLUMNS):
        position = _first(episode, "ZPLAYHEAD", "ZBOOKMARKTIME")
        duration = episode["ZDURATION"]
        rows.append({
            "show": titles.get(episode["ZPODCAST"], ""),
            "title": _text(episode["ZTITLE"]),
            "published": _date(_first(episode, "ZPUBDATE",
                                      "ZFIRSTTIMEAVAILABLE")),
            "length": duration if isinstance(duration, (int, float))
            and duration > 0 else None,
            "played": _date(episode["ZLASTDATEPLAYED"]),
            "plays": episode["ZPLAYCOUNT"] or 0,
            "position": position if isinstance(position, (int, float))
            and position > 0 else None,
            "downloaded": "yes" if episode["ZDOWNLOADDATE"]
            or episode["ZASSETURL"] else "",
            "address": _text(_first(episode, "ZENCLOSUREURL") or "")})
    return rows


def _episode_details(row):
    lines = [row["title"] or "(no title)", row["show"]]
    if row["published"]:
        lines.append(f"Published: {format_datetime(row['published'])}")
    if row["played"]:
        lines.append(f"Last played: {format_datetime(row['played'])}")
    if row["position"]:
        from .export_util import describe_duration
        lines.append(f"Stopped at: {describe_duration(row['position'])}")
    if row["address"]:
        lines.append(f"Audio: {row['address']}")
    return "\n".join(line for line in lines if line)


def datasets(conn):
    result = []
    shows = show_rows(conn)
    if shows:
        result.append(Dataset("shows", "Shows", [
            Column("title", "Show", 300), Column("author", "Author", 200),
            Column("episodes", "Episodes", 80, "number", "e"),
            Column("played", "Played", 70, "number", "e"),
            Column("last", "Last played", 130, "date"),
            Column("following", "", 60)],
            shows, sort=("title", False),
            details=lambda r: "\n".join(x for x in (
                r["title"], r["author"], r["page"], r["feed"]) if x)))
    episodes = episode_rows(conn)
    if episodes:
        result.append(Dataset("episodes", "Episodes", [
            Column("published", "Published", 130, "date"),
            Column("show", "Show", 200), Column("title", "Episode", 320),
            Column("length", "Length", 70, "duration", "e"),
            Column("plays", "Plays", 50, "number", "e"),
            Column("played", "Last played", 130, "date"),
            Column("downloaded", "", 60)],
            episodes, sort=("published", True), details=_episode_details))
    return result


class PodcastsReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        return datasets(self.conn)
