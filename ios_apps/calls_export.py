# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting the call history
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

"""Writes calls as text, a spreadsheet, JSON or a web page. No GUI."""

import html
import json
import os

from .calls import summarize
from .common import format_datetime
from .export_util import (describe_duration, html_page, iso_utc,
                          write_csv_file, write_text_file)

FORMATS = {
    "csv": "Spreadsheet (CSV)",
    "html": "Web page (open in any browser)",
    "txt": "Text",
    "json": "JSON (for programs)",
}

CSV_COLUMNS = ("date", "date_utc", "name", "number", "direction", "type",
               "duration_seconds", "duration", "location", "country",
               "service")


def _row(call):
    return [format_datetime(call.when, seconds=True), iso_utc(call.when),
            call.name, call.address, call.direction_label, call.kind_label,
            int(call.duration), describe_duration(call.duration),
            call.location, call.country, call.service]


def write_csv(path, calls):
    return write_csv_file(path, CSV_COLUMNS, [_row(c) for c in calls])


def write_json(path, calls):
    data = [{
        "date": iso_utc(c.when), "name": c.name or None,
        "number": c.address or None, "direction": c.direction,
        "type": c.kind, "duration_seconds": c.duration,
        "location": c.location or None, "country": c.country or None,
        "service": c.service or None, "id": c.rowid} for c in calls]
    write_text_file(path, json.dumps(data, ensure_ascii=False, indent=2)
                    + "\n")
    return [path]


def write_txt(path, calls):
    lines = []
    for call in calls:
        who = call.display_name
        if call.address and call.address != who:
            who += f" ({call.address})"
        parts = [format_datetime(call.when), call.direction_label,
                 call.kind_label, who]
        if call.duration:
            parts.append(describe_duration(call.duration))
        if call.location:
            parts.append(call.location)
        lines.append("  ".join(parts))
    write_text_file(path, "\n".join(lines) + ("\n" if lines else ""))
    return [path]


_CSS = """
td.num,th.num{text-align:right}
.missed{color:#c0392b}
.summary{margin:.5em 0 1em}
"""


def write_html(path, calls):
    totals = summarize(calls)
    rows = []
    for call in calls:
        who = html.escape(call.display_name)
        if call.address and call.address != call.display_name:
            who += (f"<div class=\"meta\">{html.escape(call.address)}</div>")
        css = " class=\"missed\"" if call.direction == "missed" else ""
        rows.append(
            f"<tr{css}><td>{html.escape(format_datetime(call.when))}</td>"
            f"<td>{who}</td><td>{html.escape(call.direction_label)}</td>"
            f"<td>{html.escape(call.kind_label)}</td>"
            f"<td class=\"num\">{html.escape(describe_duration(call.duration))}"
            f"</td><td>{html.escape(call.location)}</td></tr>")
    body = ("<h1>Call history</h1><div class=\"summary meta\">"
            f"{totals['total']:,} calls &middot; {totals['missed']:,} missed "
            f"&middot; {html.escape(describe_duration(totals['talk_seconds']))}"
            " talk time</div><table><thead><tr><th>Date</th><th>Who</th>"
            "<th>Direction</th><th>Type</th><th class=\"num\">Duration</th>"
            "<th>Place</th></tr></thead><tbody>" + "".join(rows)
            + "</tbody></table>")
    write_text_file(path, html_page("Call history", body, _CSS))
    return [path]


def export(calls, fmt, folder):
    """Write *calls* as *fmt* into *folder*. Returns the paths written."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"calls.{fmt}")
    return {"csv": write_csv, "json": write_json, "txt": write_txt,
            "html": write_html}[fmt](path, calls)
