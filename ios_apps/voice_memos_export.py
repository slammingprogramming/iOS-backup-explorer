# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting voice recordings
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

"""Copies voice recordings out of the backup: as audio files named by date
and title, on a web page with a player for each, or listed in a
spreadsheet. The audio is never converted; the files are the recordings
exactly as the phone made them (usually .m4a, which nearly every player
opens). No GUI.
"""

import html
import os
from datetime import datetime

from .common import format_datetime
from .export_util import (describe_duration, describe_size, href, html_page,
                          iso_utc, safe_filename, safe_name_with_extension,
                          write_csv_file, write_text_file)

FORMATS = {
    "audio": "Audio files (as recorded, named by date and title)",
    "html": "Web page with a player for each recording",
    "csv": "A list of the recordings (CSV, nothing is copied)",
}

CSV_COLUMNS = ("title", "date", "date_utc", "length_seconds", "length",
               "size_bytes", "file_name", "backup_path")


def friendly_name(memo):
    """``2026-09-01 100000 - Interview with Sam.m4a``."""
    ext = safe_name_with_extension(
        "x" + os.path.splitext(memo.name)[1].lower())[1:]
    stamp = ""
    if memo.when is not None:
        try:
            stamp = datetime.fromtimestamp(memo.when).strftime(
                "%Y-%m-%d %H%M%S") + " - "
        except (OverflowError, OSError, ValueError):
            pass
    return stamp + safe_filename(memo.display_title, "Recording", 100) + ext


def write_csv(path, memos):
    rows = [[m.display_title, format_datetime(m.when, seconds=True),
             iso_utc(m.when), f"{m.duration:g}" if m.duration else "",
             describe_duration(m.duration) if m.duration else "", m.size,
             m.name, m.path] for m in memos]
    return write_csv_file(path, CSV_COLUMNS, rows)


def _touch(path, memo):
    if memo.when:
        try:
            os.utime(path, (memo.when, memo.when))
        except (OSError, OverflowError, ValueError):
            pass


def _page(entries):
    items = []
    for memo, relative in entries:
        target = html.escape(href(relative), quote=True)
        meta = [html.escape(format_datetime(memo.when))]
        if memo.duration:
            meta.append(html.escape(describe_duration(memo.duration)))
        if memo.size:
            meta.append(html.escape(describe_size(memo.size)))
        items.append(
            f"<li><div><strong>{html.escape(memo.display_title)}</strong>"
            f"<div class=\"meta\">{' &middot; '.join(m for m in meta if m)}"
            f"</div></div><audio controls preload=\"none\" src=\"{target}\">"
            f"</audio> <a href=\"{target}\">download</a></li>")
    body = (f"<h1>Voice memos</h1><div class=\"meta\">{len(entries):,} "
            f"recordings</div><ul class=\"list\">{''.join(items)}</ul>")
    return html_page("Voice memos", body, "ul.list audio{width:100%;"
                     "margin-top:6px}ul.list li{padding:12px 14px}")


def export(memos, fmt, folder, copy_file=None, progress=None):
    """Write *memos* as *fmt* into *folder*. Returns ``(paths, notes)``:
    the files written and a text about what went wrong (empty when
    nothing did). *copy_file(backup path, directory, name)* copies a file
    out of the backup and says whether it was there."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    os.makedirs(folder, exist_ok=True)
    if fmt == "csv":
        return write_csv(os.path.join(folder, "voice-memos.csv"), memos), ""
    directory = os.path.join(folder, "recordings") if fmt == "html" \
        else folder
    os.makedirs(directory, exist_ok=True)
    used, paths, entries, missing = set(), [], [], []
    for done, memo in enumerate(memos, 1):
        name = friendly_name(memo)
        base, ext = os.path.splitext(name)
        number = 1
        while name.casefold() in used:
            number += 1
            name = f"{base} ({number}){ext}"
        used.add(name.casefold())
        if copy_file(memo.path, directory, name):
            path = os.path.join(directory, name)
            _touch(path, memo)
            paths.append(path)
            entries.append((memo, f"recordings/{name}"))
        else:
            missing.append(memo.display_title)
        if progress:
            progress(done, len(memos))
    if fmt == "html":
        index = os.path.join(folder, "index.html")
        write_text_file(index, _page(entries))
        paths.insert(0, index)
    notes = ""
    if missing:
        notes = (f"{len(missing):,} recording(s) are not in the backup and "
                 "were skipped: " + ", ".join(missing[:5])
                 + (", ..." if len(missing) > 5 else ""))
    return paths, notes
