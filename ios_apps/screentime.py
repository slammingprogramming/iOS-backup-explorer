# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Screen Time reader
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

"""Reads Screen Time. The phone keeps a small property list for each day,
week and hour of use (``<start>.plist``, named by the start time) with the
time spent in each app and on each website, how often the phone was picked
up and how many notifications arrived. No GUI.

The hours are many (a file each), so only the most recent ones are read.
"""

import os
import plistlib
from datetime import datetime, timezone

from .appnames import app_name
from .common import own_path, utc_datetime
from .records import Column, Dataset

FOLDER = ("SysSharedContainerDomain-systemgroup.com.apple.DeviceActivity/"
          "Library/com.apple.DeviceActivity/Cloud")
KINDS = ("Daily", "Weekly", "Hourly")
HOURS_KEPT = 24 * 31            # the most recent hours that are read

def kind_of(path):
    parts = path.split("/")
    for kind in KINDS:
        if kind in parts:
            return kind
    return ""


def local_name(path):
    """The name a working copy gets, so the files of the same name from
    the days, weeks and hours (and from several devices) do not meet."""
    parts = path.split("/")
    device = parts[-4][:8] if len(parts) >= 4 else "device"
    return f"{kind_of(path) or 'x'}-{device}-{parts[-1]}"


def _start_of(name):
    try:
        return float(name[:-len(".plist")])
    except ValueError:
        return None


def discover(index):
    """The files to copy (backup paths): every day and week, and the most
    recent hours, of every device."""
    root = index.get(FOLDER) if index is not None else None
    if root is None or not root.is_dir:
        return []
    found = {kind: [] for kind in KINDS}
    for zone in root.children.values():
        if not zone.is_dir:
            continue
        for device in zone.children.values():
            if not device.is_dir:
                continue
            for kind in KINDS:
                folder = device.children.get(kind)
                segments = folder.children.get("ActivitySegments") \
                    if folder is not None and folder.is_dir else None
                if segments is None or not segments.is_dir:
                    continue
                for name, node in segments.children.items():
                    start = _start_of(name)
                    if node.is_dir or start is None:
                        continue
                    found[kind].append(
                        (start, f"{FOLDER}/{zone.name}/{device.name}/{kind}/"
                                f"ActivitySegments/{name}"))
    hours = sorted(found["Hourly"], reverse=True)[:HOURS_KEPT]
    paths = []
    for kind, items in (("Daily", found["Daily"]),
                        ("Weekly", found["Weekly"]), ("Hourly", hours)):
        paths += [p for _s, p in sorted(items, reverse=True)]
    return paths


def read_record(path):
    """The record inside one file (a dict), or None."""
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
    except Exception:             # damaged or not a property list
        return None
    value = data.get("value") if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return None
    interval = value.get("dateInterval")
    if not isinstance(interval, dict) \
            or not isinstance(interval.get("start"), datetime):
        return None
    return value


def _number(value):
    return float(value) if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else 0.0


def _stamp(value):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def summarize(record):
    """Totals and per-app, per-site numbers of one record."""
    apps, sites = {}, {}
    for category in record.get("categoryActivities") or ():
        if not isinstance(category, dict):
            continue
        for item in category.get("applicationActivities") or ():
            if not isinstance(item, dict) or not item.get("bundleIdentifier"):
                continue
            entry = apps.setdefault(item["bundleIdentifier"],
                                    {"time": 0.0, "pickups": 0, "alerts": 0})
            entry["time"] += _number(item.get("totalActivityDuration"))
            entry["pickups"] += int(_number(item.get("numberOfPickups")))
            entry["alerts"] += int(_number(item.get("numberOfNotifications")))
        for item in category.get("webDomainActivities") or ():
            if isinstance(item, dict) and item.get("domain"):
                sites[item["domain"]] = sites.get(item["domain"], 0.0) \
                    + _number(item.get("totalActivityDuration"))
    return apps, sites


def _zone_offset(starts):
    """Seconds that local time is ahead of UTC, from when the days begin
    (a day starts at local midnight)."""
    if not starts:
        return 0
    counts = {}
    for stamp in starts:
        rest = int(stamp) % 86400
        counts[rest] = counts.get(rest, 0) + 1
    rest = max(counts, key=counts.get)
    return -rest if rest <= 43200 else 86400 - rest


def load_files(folder):
    """``{kind: [(device, record), ...]}`` from the working copies."""
    result = {kind: [] for kind in KINDS}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return result
    for name in names:
        kind, _, rest = name.partition("-")
        device, _, _ = rest.partition("-")
        if kind not in result or not name.endswith(".plist"):
            continue
        record = read_record(os.path.join(folder, name))
        if record is not None:
            result[kind].append((device, record))
    return result


def _day_label(stamp, offset):
    """The date of a day or week that starts at *stamp* (local midnight)."""
    return utc_datetime(stamp + offset).strftime("%Y-%m-%d")


def build(files):
    """The rows of every table, from :func:`load_files`."""
    daily = files["Daily"]
    starts = [_stamp(r["dateInterval"]["start"]) for _d, r in daily]
    offset = _zone_offset([s for s in starts if s is not None])
    days, apps, sites, weeks, hours = [], {}, {}, [], []
    for (device, record), start in zip(daily, starts):
        if start is None:
            continue
        day_apps, day_sites = summarize(record)
        top = max(day_apps.items(), key=lambda kv: kv[1]["time"],
                  default=None)
        pickups = int(_number(record.get("totalPickupsWithoutApplicationActivity"))) \
            + sum(a["pickups"] for a in day_apps.values())
        label = _day_label(start, offset)
        days.append({
            "day": label, "device": device, "start": start,
            "total": _number(record.get("totalActivityDuration")),
            "pickups": pickups,
            "alerts": sum(a["alerts"] for a in day_apps.values()),
            "apps": len([a for a in day_apps.values() if a["time"] > 0]),
            "top_app": app_name(top[0]) if top else "",
            "top_time": top[1]["time"] if top else None})
        for bundle, entry in day_apps.items():
            row = apps.setdefault(bundle, {
                "bundle": bundle, "app": app_name(bundle), "time": 0.0,
                "days": set(), "pickups": 0, "alerts": 0, "last": ""})
            row["time"] += entry["time"]
            row["pickups"] += entry["pickups"]
            row["alerts"] += entry["alerts"]
            if entry["time"] > 0:
                row["days"].add(label)
            if entry["time"] > 0:
                row["last"] = max(row["last"], label)
        for domain, seconds in day_sites.items():
            row = sites.setdefault(domain, {"site": domain, "time": 0.0,
                                            "days": set()})
            row["time"] += seconds
            row["days"].add(label)
    for device, record in files["Weekly"]:
        start = _stamp(record["dateInterval"]["start"])
        if start is None:
            continue
        week_apps, _ = summarize(record)
        total = _number(record.get("totalActivityDuration"))
        weeks.append({
            "week": _day_label(start, offset), "device": device,
            "total": total, "per_day": total / 7,
            "pickups": int(_number(record.get(
                "totalPickupsWithoutApplicationActivity")))
            + sum(a["pickups"] for a in week_apps.values())})
    for device, record in files["Hourly"]:
        start = _stamp(record["dateInterval"]["start"])
        if start is None:
            continue
        hour_apps, _ = summarize(record)
        local = utc_datetime(start + offset)
        top = max(hour_apps.items(), key=lambda kv: kv[1]["time"],
                  default=None)
        hours.append({
            "hour": local.strftime("%Y-%m-%d %H:00"), "device": device,
            "start": start, "total": _number(record.get(
                "totalActivityDuration")),
            "pickups": int(_number(record.get(
                "totalPickupsWithoutApplicationActivity")))
            + sum(a["pickups"] for a in hour_apps.values()),
            "top_app": app_name(top[0]) if top else ""})
    for row in apps.values():
        row["days_used"] = len(row["days"])
        row["per_day"] = row["time"] / row["days_used"] \
            if row["days_used"] else None
    for row in sites.values():
        row["days_used"] = len(row["days"])
    return days, list(apps.values()), list(sites.values()), weeks, hours, \
        offset


def _day_details(row):
    from .export_util import describe_duration
    lines = [row["day"], f"Screen time: {describe_duration(row['total'])}",
             f"Pickups: {row['pickups']:,}",
             f"Notifications: {row['alerts']:,}",
             f"Apps used: {row['apps']:,}"]
    if row["top_app"]:
        lines.append(f"Most used: {row['top_app']} "
                     f"({describe_duration(row['top_time'])})")
    return "\n".join(lines)


def datasets(folder):
    files = load_files(folder)
    days, apps, sites, weeks, hours, offset = build(files)
    multiple = len({r["device"] for r in days + weeks + hours}) > 1
    result = []
    device_column = [Column("device", "Device", 80)] if multiple else []
    if days:
        result.append(Dataset(
            "days", "Days", [
                Column("day", "Day", 100),
                Column("total", "Screen time", 100, "duration", "e"),
                Column("pickups", "Pickups", 70, "number", "e"),
                Column("alerts", "Notifications", 90, "number", "e"),
                Column("apps", "Apps", 50, "number", "e"),
                Column("top_time", "In it", 80, "duration", "e"),
                Column("top_app", "Most used app", 280)] + device_column,
            days, sort=("day", True), details=_day_details,
            note="Each day starts at midnight where the phone was."))
    if weeks:
        result.append(Dataset(
            "weeks", "Weeks", [
                Column("week", "Week starting", 110),
                Column("total", "Screen time", 100, "duration", "e"),
                Column("per_day", "Per day", 90, "duration", "e"),
                Column("pickups", "Pickups", 70, "number", "e")]
            + device_column, weeks, sort=("week", True)))
    if apps:
        result.append(Dataset(
            "apps", "Apps", [
                Column("app", "App", 300),
                Column("time", "Total time", 100, "duration", "e"),
                Column("days_used", "Days used", 80, "number", "e"),
                Column("per_day", "Per day used", 100, "duration", "e"),
                Column("pickups", "Pickups", 70, "number", "e"),
                Column("alerts", "Notifications", 90, "number", "e"),
                Column("last", "Last used", 100)],
            apps, sort=("time", True),
            details=lambda r: f"{r['app']}\n{r['bundle']}"
            if r["app"] != r["bundle"] else r["bundle"]))
    if sites:
        result.append(Dataset(
            "sites", "Websites", [
                Column("site", "Website", 360),
                Column("time", "Total time", 100, "duration", "e"),
                Column("days_used", "Days", 70, "number", "e")],
            sites, sort=("time", True)))
    if hours:
        result.append(Dataset(
            "hours", "Recent hours", [
                Column("hour", "Hour", 130),
                Column("total", "Screen time", 100, "duration", "e"),
                Column("pickups", "Pickups", 70, "number", "e"),
                Column("top_app", "Most used", 260)] + device_column,
            hours, sort=("hour", True),
            note=f"Only the most recent {HOURS_KEPT // 24} days are read "
                 "by hour."))
    return result


class ScreenTimeReader:
    def __init__(self, conn):
        self.conn = conn

    def datasets(self):
        own = own_path(self.conn)
        return datasets(os.path.dirname(own))
