# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — helpers shared by the exporters
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

"""Small things every exporter needs: safe file names, sizes, times, links,
a web page frame and a spreadsheet writer. No GUI."""

import csv
import html
import os
import re
import urllib.parse
from datetime import datetime, timezone

_FILENAME_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = ("CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10)))


def safe_filename(text, fallback="untitled", limit=80):
    """*text* as a name that is valid on every platform."""
    name = _FILENAME_BAD.sub("_", text or "").strip(" .")
    name = name[:limit].rstrip(" .")
    if not name or name.split(".")[0].upper() in _RESERVED:
        name = f"_{name}" if name else fallback
    return name


def safe_name_with_extension(name, fallback="untitled", limit=150):
    """A whole file name (extension included) valid on every platform; the
    extension survives even when the rest has to be shortened."""
    base, ext = os.path.splitext(name or "")
    ext = _FILENAME_BAD.sub("_", ext)[:12]
    return safe_filename(base, fallback, max(1, limit - len(ext))) + ext


def numbered_filename(number, title, extension):
    """``003 - Shopping list.html``: numbered, so names never collide."""
    return f"{number:03d} - {safe_filename(title)}.{extension}"


def iso_utc(stamp):
    if stamp is None:
        return ""
    try:
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat(
            timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def describe_size(size):
    if not size:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" \
                else f"{size:.1f} {unit}"
        size /= 1024


def describe_duration(seconds):
    """``1:05`` or ``1:02:03`` for a length in seconds; ``""`` if unknown."""
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours \
        else f"{minutes}:{secs:02d}"


def href(relative):
    """A relative file path as a safe link target."""
    return urllib.parse.quote(relative.replace("\\", "/"), safe="/")


def html_page(title, body, css=""):
    """A complete standalone page: everything escaped by the caller, no
    scripts, nothing loaded from the internet."""
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,"
            "initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{BASE_CSS}{css}"
            f"</style></head><body><main>{body}</main></body></html>\n")


BASE_CSS = """
:root{--bg:#fff;--fg:#1c1c1e;--muted:#6b7280;--card:#f5f5f7;--line:#d1d5db}
@media (prefers-color-scheme:dark){:root{--bg:#000;--fg:#f2f2f7;
--muted:#9ca3af;--card:#1c1c1e;--line:#3a3a3c}}
body{font:16px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;margin:0;
background:var(--bg);color:var(--fg)}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:1.4rem;margin:.2em 0}.meta{color:var(--muted);font-size:.85rem}
ul.list{list-style:none;padding:0}
ul.list li{background:var(--card);margin:8px 0;padding:10px 14px;
border-radius:12px}
ul.list a{color:inherit;font-weight:600;text-decoration:none}
a{color:#0b84fe}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;
vertical-align:top}
"""


def write_csv_file(path, header, rows):
    """A spreadsheet that Excel opens correctly (UTF-8 with a byte-order
    mark). Returns ``[path]``."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return [path]


def write_text_file(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path
