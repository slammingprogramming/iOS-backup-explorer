# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting tables of records
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

"""Writes the rows of a :class:`records.Dataset` as a spreadsheet, a web
page, text or JSON, plus whatever extra formats the dataset offers (for
example an iCalendar file for calendar events). No GUI."""

import html
import json
import os
import re

from .export_util import (html_page, iso_utc, safe_filename, write_csv_file,
                          write_text_file)

FORMATS = {
    "csv": "Spreadsheet (CSV)",
    "html": "Web page (open in any browser)",
    "txt": "Text",
    "json": "JSON (for programs)",
}

_CSS = "td.num,th.num{text-align:right}"


def formats_for(dataset):
    """The formats to offer for *dataset*: the usual ones, then its own."""
    result = dict(FORMATS)
    for key, (label, _writer) in dataset.formats.items():
        result[key] = label
    for key, (label, _writer) in dataset.file_formats.items():
        result[key] = label
    return result


def _cell(column, value, row=None):
    return column.show(value, row)


def _json_value(column, value):
    if value is None or value == "":
        return None
    if column.kind == "date":
        return iso_utc(value) or None
    if column.kind == "day":
        return column.show(value) or None
    return value


def write_csv(path, dataset, rows):
    columns = dataset.columns
    return write_csv_file(
        path, [c.heading for c in columns],
        [[_cell(c, r.get(c.key), r) for c in columns] for r in rows])


def write_json(path, dataset, rows):
    data = [{c.key: _json_value(c, r.get(c.key)) for c in dataset.columns}
            for r in rows]
    write_text_file(path, json.dumps(data, ensure_ascii=False, indent=2,
                                     default=str) + "\n")
    return [path]


def write_txt(path, dataset, rows):
    lines = []
    for row in rows:
        parts = [(c.heading, _cell(c, row.get(c.key), row)) for c in
                 dataset.columns]
        lines.append("  ".join(f"{h}: {v}" for h, v in parts if v))
    write_text_file(path, "\n".join(lines) + ("\n" if lines else ""))
    return [path]


def _align(column):
    return ' class="num"' if column.anchor == "e" else ""


def write_html(path, dataset, rows):
    head = "".join(f"<th{_align(c)}>{html.escape(c.heading)}</th>"
                   for c in dataset.columns)
    body = "".join(
        "<tr>" + "".join(
            f"<td{_align(c)}>{html.escape(_cell(c, r.get(c.key), r))}</td>"
            for c in dataset.columns) + "</tr>" for r in rows)
    page = (f"<h1>{html.escape(dataset.title)}</h1><div class=\"meta\">"
            f"{len(rows):,} rows</div><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>")
    write_text_file(path, html_page(dataset.title, page, _CSS))
    return [path]


_WRITERS = {"csv": write_csv, "json": write_json, "txt": write_txt,
            "html": write_html}


def file_stem(dataset):
    return safe_filename(re.sub(r"\s+", "-", dataset.title.strip()).lower(),
                         "data")


def export(dataset, rows, fmt, folder, copy_file=None):
    """Write *rows* of *dataset* as *fmt* into *folder*; returns the paths
    written. *copy_file(backup path, directory, name) -> bool* copies a file
    out of the backup, for the formats that include files."""
    os.makedirs(folder, exist_ok=True)
    if fmt in dataset.file_formats:
        return dataset.file_formats[fmt][1](folder, rows, copy_file)
    base = os.path.join(folder, file_stem(dataset))
    if fmt in dataset.formats:
        return dataset.formats[fmt][1](base, rows)
    if fmt not in _WRITERS:
        raise ValueError(f"unknown format {fmt!r}")
    return _WRITERS[fmt](f"{base}.{fmt}", dataset, rows)
