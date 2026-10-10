# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — writing iCalendar (.ics) files
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

"""Just enough of iCalendar (RFC 5545) to write events and to-dos that
calendar programs import: text escaping, lines folded at 75 bytes, UTC and
all-day dates. No GUI."""

import os
from .common import utc_datetime
from .contacts_export import fold


def escape(text):
    return (str(text).replace("\\", "\\\\").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;")
            .replace(",", "\\,"))


def utc(stamp):
    """``20260525T120000Z`` for a Unix time."""
    return utc_datetime(stamp).strftime("%Y%m%dT%H%M%SZ")


def day(stamp):
    """``20260525`` for a date kept as midnight UTC."""
    return utc_datetime(stamp).strftime("%Y%m%d")


def next_day(stamp):
    """The day after *stamp* (a date kept as midnight UTC)."""
    return day(stamp + 86400)


def lines_of(properties):
    """The folded lines for ``[(name, value), ...]`` (a name may carry
    parameters: ``DTSTART;VALUE=DATE``)."""
    out = []
    for name, value in properties:
        out.extend(fold(f"{name}:{value}"))
    return out


def calendar(components, name=""):
    """The text of a whole calendar: *components* are lists of lines
    (``BEGIN:VEVENT`` ... ``END:VEVENT``)."""
    header = ["BEGIN:VCALENDAR", "VERSION:2.0",
              "PRODID:-//iOS Backup Explorer//EN", "CALSCALE:GREGORIAN"]
    if name:
        header.append(f"X-WR-CALNAME:{escape(name)}")
    lines = header + [line for part in components for line in part] \
        + ["END:VCALENDAR"]
    return "".join(line + "\r\n" for line in lines)


def write(path, components, name=""):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(calendar(components, name))
    return [path]

