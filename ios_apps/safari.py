# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading Safari's history, bookmarks and tabs
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

"""Reads Safari's databases: the pages visited (``History.db``), the
bookmarks and the reading list (``Bookmarks.db``) and the tabs that were
open (``SafariTabs.db``). No GUI."""

import html
from urllib.parse import urlsplit

from .common import apple_time
from .export_util import write_text_file
from .records import Column, Dataset, open_copies, sqlite_rows

HISTORY = "HomeDomain/Library/Safari/History.db"
BOOKMARKS = "HomeDomain/Library/Safari/Bookmarks.db"
TABS = "HomeDomain/Library/Safari/SafariTabs.db"
DATABASES = (HISTORY, BOOKMARKS, TABS)

_FOLDER_NAMES = {"BookmarksBar": "Favorites",
                 "com.apple.ReadingList": "Reading List",
                 "com.apple.FrequentlyVisitedSites": "Frequently Visited",
                 "Local": "This device", "Private": "Private tabs",
                 "pinned": "Pinned tabs", "privatePinned": "Private pinned",
                 "recentlyClosed": "Recently closed",
                 "Recovered": "Recovered tabs"}


def host_of(url):
    """The site of a web address (``example.com``), or ``""``."""
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _stamp(value):
    return apple_time(value) if value else None


# ── History ──────────────────────────────────────────────────

def history_datasets(conn):
    visits = []
    for when, title, url, ok in sqlite_rows(
            conn,
            "SELECT v.visit_time, v.title, i.url, v.load_successful "
            "FROM history_visits v JOIN history_items i "
            "ON i.id = v.history_item"):
        visits.append({"when": apple_time(when), "title": (title or "").strip(),
                       "url": url or "", "site": host_of(url),
                       "failed": "" if ok in (None, 1) else "failed"})
    sites = {}
    for visit in visits:
        entry = sites.setdefault(visit["site"] or "(no site)", {
            "site": visit["site"] or "(no site)", "visits": 0, "last": None,
            "pages": set()})
        entry["visits"] += 1
        entry["pages"].add(visit["url"])
        if visit["when"] and (entry["last"] is None
                              or visit["when"] > entry["last"]):
            entry["last"] = visit["when"]
    site_rows = [{"site": e["site"], "visits": e["visits"],
                  "pages": len(e["pages"]), "last": e["last"]}
                 for e in sites.values()]
    return [
        Dataset("history", "History", [
            Column("when", "When", 140, "date"),
            Column("title", "Title", 300),
            Column("url", "Address", 420),
            Column("site", "Site", 150),
            Column("failed", "", 50)],
            visits, sort=("when", True),
            details=lambda r: f"{r['title'] or '(no title)'}\n{r['url']}"),
        Dataset("sites", "Sites visited", [
            Column("site", "Site", 300),
            Column("visits", "Visits", 80, "number", "e"),
            Column("pages", "Pages", 80, "number", "e"),
            Column("last", "Last visit", 140, "date")],
            site_rows, sort=("visits", True)),
    ] if visits else []


# ── Bookmarks ────────────────────────────────────────────────

def _folder_paths(rows):
    """``{id: "Favorites/Shopping"}`` for the folders of a bookmarks table
    (rows are ``(id, parent, title, uuid)``)."""
    by_id = {r[0]: r for r in rows}

    def path(folder_id, seen=()):
        row = by_id.get(folder_id)
        if row is None or folder_id in seen or row[3] == "Root" \
                or row[2] == "Root":
            return ""
        name = _FOLDER_NAMES.get(row[2], row[2] or "")
        above = path(row[1], seen + (folder_id,))
        return f"{above}/{name}" if above else name

    return {folder_id: path(folder_id) for folder_id in by_id}


def _bookmark_rows(conn, with_dates=True):
    folders = _folder_paths(sqlite_rows(
        conn, "SELECT id, parent, title, external_uuid FROM bookmarks "
              "WHERE type = 1"))
    rows = []
    for title, url, parent, modified in sqlite_rows(
            conn, "SELECT title, url, parent, last_modified FROM bookmarks "
                  "WHERE type = 0 AND url IS NOT NULL AND "
                  "COALESCE(deleted, 0) = 0 ORDER BY id"):
        rows.append({"title": (title or "").strip(), "url": url,
                     "folder": folders.get(parent, ""),
                     "site": host_of(url), "modified": _stamp(modified)})
    return rows


def write_netscape(base, rows):
    """A bookmarks file every browser can import (the Netscape format)."""
    by_folder = {}
    for row in rows:
        by_folder.setdefault(row["folder"], []).append(row)
    lines = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>",
             '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; '
             'charset=UTF-8">', "<TITLE>Bookmarks</TITLE>", "<H1>Bookmarks</H1>",
             "<DL><p>"]
    for folder in sorted(by_folder, key=str.casefold):
        indent = "    "
        if folder:
            lines.append(f"{indent}<DT><H3>{html.escape(folder)}</H3>")
            lines.append(f"{indent}<DL><p>")
            indent *= 2
        for row in by_folder[folder]:
            lines.append(f'{indent}<DT><A HREF="'
                         f'{html.escape(row["url"], quote=True)}">'
                         f'{html.escape(row["title"] or row["url"])}</A>')
        if folder:
            lines.append("    </DL><p>")
    lines.append("</DL><p>")
    path = base + "-import.html"
    write_text_file(path, "\n".join(lines) + "\n")
    return [path]


def bookmark_datasets(conn):
    rows = _bookmark_rows(conn)
    reading = [r for r in rows if r["folder"].startswith("Reading List")]
    marks = [r for r in rows if r not in reading]
    columns = [Column("title", "Title", 300), Column("url", "Address", 420),
               Column("folder", "Folder", 200),
               Column("modified", "Changed", 140, "date")]
    result = []
    if marks:
        result.append(Dataset(
            "bookmarks", "Bookmarks", columns, marks, sort=("folder", False),
            details=lambda r: f"{r['title'] or '(no title)'}\n{r['url']}",
            formats={"netscape": (
                "Bookmarks file for browsers (.html, importable)",
                write_netscape)}))
    if reading:
        result.append(Dataset(
            "reading", "Reading list", columns, reading,
            sort=("modified", True)))
    return result


# ── Open tabs ────────────────────────────────────────────────

def tab_datasets(conn):
    folders = _folder_paths(sqlite_rows(
        conn, "SELECT id, parent, title, external_uuid FROM bookmarks "
              "WHERE type = 1"))
    rows = []
    for title, url, parent, closed in sqlite_rows(
            conn, "SELECT title, url, parent, date_closed FROM bookmarks "
                  "WHERE type = 0 AND url IS NOT NULL ORDER BY id"):
        rows.append({"title": (title or "").strip(), "url": url,
                     "group": folders.get(parent, ""), "site": host_of(url),
                     "closed": _stamp(closed)})
    if not rows:
        return []
    return [Dataset("tabs", "Open tabs", [
        Column("title", "Title", 300), Column("url", "Address", 420),
        Column("group", "Group", 160),
        Column("closed", "Closed", 140, "date")], rows,
        details=lambda r: f"{r['title'] or '(no title)'}\n{r['url']}")]


class SafariReader:
    """Reads the Safari databases that are there."""

    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        found = []
        with open_copies(self.conn, DATABASES) as copies:
            for path, make in ((HISTORY, history_datasets),
                               (BOOKMARKS, bookmark_datasets),
                               (TABS, tab_datasets)):
                if copies.get(path) is not None:
                    found += make(copies[path])
        return found
