# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Reminders reader
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

"""Reads the Reminders app. The phone keeps one database for each account
(``Data-<id>.sqlite``) in one folder; the reminders, their lists and the
accounts are all rows of a few tables whose kind is a number that the same
file explains. No GUI."""

from . import ics
from .common import apple_time
from .export_util import write_text_file
from .records import Column, Dataset, fetch_dicts, open_copies, sqlite_rows

FOLDER = "HomeDomain/Library/Reminders/Container_v1/Stores"
PRIORITIES = {1: "High", 5: "Medium", 9: "Low"}


def discover(index):
    """The reminder databases in the backup (backup paths), the one most
    likely to hold reminders first."""
    folder = index.get(FOLDER) if index is not None else None
    if folder is None or not folder.is_dir:
        return []
    names = sorted(n for n, node in folder.children.items()
                   if not node.is_dir and n.startswith("Data-")
                   and n.endswith(".sqlite"))
    names.sort(key=lambda n: -folder.children[n].size)
    return [f"{FOLDER}/{n}" for n in names]


def _entity(conn, name):
    """The number this store uses for the kind of row called *name*."""
    rows = sqlite_rows(conn, "SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = ?",
                       (name,))
    return rows[0][0] if rows else None


def _rows_of(conn, kind, columns):
    """The rows of one kind (``REMCDList``...) as dicts. They are in a table
    of their own or, in the way these databases are laid out, among the
    rows of ``ZREMCDOBJECT`` told apart by their kind."""
    table = "Z" + kind.upper()
    rows = fetch_dicts(conn, table, columns)
    if rows:
        return rows
    entity = _entity(conn, kind)
    if entity is None:
        return []
    return fetch_dicts(conn, "ZREMCDOBJECT", columns,
                       where=f"Z_ENT = {int(entity)}")


def _first(row, keys):
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def store_rows(conn, store):
    """``(reminders, lists, accounts)`` of one database; each a list of
    dicts. *store* tells the databases apart in the keys."""
    accounts = {}
    for row in _rows_of(conn, "REMCDAccount", ["Z_PK", "ZNAME", "ZNAME1",
                                               "ZNAME2", "ZMARKEDFORDELETION"]):
        if not row["ZMARKEDFORDELETION"]:
            accounts[row["Z_PK"]] = _first(row, ("ZNAME", "ZNAME1", "ZNAME2"))
    lists = {}
    for row in _rows_of(conn, "REMCDList", ["Z_PK", "ZNAME", "ZNAME1",
                                            "ZNAME2", "ZACCOUNT",
                                            "ZPARENTACCOUNT",
                                            "ZMARKEDFORDELETION"]):
        if row["ZMARKEDFORDELETION"]:
            continue
        account = accounts.get(row["ZACCOUNT"]) or accounts.get(
            row["ZPARENTACCOUNT"]) or next(iter(accounts.values()), "")
        lists[row["Z_PK"]] = {
            "list": _first(row, ("ZNAME2", "ZNAME1", "ZNAME")) or "(no name)",
            "account": account, "store": store}
    items = _rows_of(conn, "REMCDReminder", [
        "Z_PK", "ZTITLE", "ZNOTES", "ZCOMPLETED", "ZFLAGGED", "ZPRIORITY",
        "ZLIST", "ZPARENTREMINDER", "ZALLDAY", "ZMARKEDFORDELETION",
        "ZDUEDATE", "ZCREATIONDATE", "ZCOMPLETIONDATE", "ZLASTMODIFIEDDATE",
        "ZSTARTDATE"])
    titles = {r["Z_PK"]: (r["ZTITLE"] or "").strip() for r in items}
    reminders = []
    for row in items:
        where = lists.get(row["ZLIST"], {})
        reminders.append({
            "key": f"{store}:{row['Z_PK']}",
            "title": (row["ZTITLE"] or "").strip(),
            "notes": (row["ZNOTES"] or "").strip(),
            "list": where.get("list", ""),
            "account": where.get("account", ""),
            "done": bool(row["ZCOMPLETED"]),
            "flagged": bool(row["ZFLAGGED"]),
            "priority": PRIORITIES.get(row["ZPRIORITY"], ""),
            "deleted": bool(row["ZMARKEDFORDELETION"]),
            "all_day": bool(row["ZALLDAY"]),
            "due": apple_time(row["ZDUEDATE"]) if row["ZDUEDATE"] else None,
            "start": apple_time(row["ZSTARTDATE"])
            if row["ZSTARTDATE"] else None,
            "created": apple_time(row["ZCREATIONDATE"])
            if row["ZCREATIONDATE"] else None,
            "completed": apple_time(row["ZCOMPLETIONDATE"])
            if row["ZCOMPLETIONDATE"] else None,
            "changed": apple_time(row["ZLASTMODIFIEDDATE"])
            if row["ZLASTMODIFIEDDATE"] else None,
            "parent": titles.get(row["ZPARENTREMINDER"], "")
            if row["ZPARENTREMINDER"] else "",
            "is_subtask": bool(row["ZPARENTREMINDER"]),
        })
        reminders[-1]["status"] = _status(reminders[-1])
    return reminders, list(lists.values()), list(accounts.values())


def all_rows(conn, index):
    """Reminders and lists from every database of the backup (*conn* is the
    first of them)."""
    paths = discover(index) or []
    reminders, lists = [], []
    with open_copies(conn, paths) as found:
        for number, path in enumerate(paths):
            other = found.get(path)
            if other is None:
                continue
            more, kinds, _accounts = store_rows(other, number)
            reminders += more
            lists += kinds
    return reminders, lists


def _due_text(row):
    from .common import format_datetime
    from .records import format_day
    if row["due"] is None:
        return ""
    return format_day(row["due"]) if row["all_day"] \
        else format_datetime(row["due"])


def _status(row):
    if row["deleted"]:
        return "Deleted"
    return "Done" if row["done"] else ""


def _details(row):
    from .common import format_datetime
    lines = [row["title"] or "(no title)"]
    for label, text in (
            ("List", row["list"]), ("Account", row["account"]),
            ("Due", _due_text(row)),
            ("Priority", row["priority"]),
            ("Flagged", "yes" if row["flagged"] else ""),
            ("Subtask of", row["parent"]),
            ("Completed", format_datetime(row["completed"])),
            ("Created", format_datetime(row["created"])),
            ("Changed", format_datetime(row["changed"]))):
        if text:
            lines.append(f"{label}: {text}")
    if row["notes"]:
        lines += ["", row["notes"]]
    return "\n".join(lines)


def _todo_lines(row):
    """The lines of one ``VTODO``."""
    props = [("UID", ics.escape(f"reminder-{row['key']}"))]
    stamp = row["changed"] or row["created"] or row["due"] or 0
    props.append(("DTSTAMP", ics.utc(stamp)))
    if row["created"]:
        props.append(("CREATED", ics.utc(row["created"])))
    if row["due"] is not None:
        if row["all_day"]:
            props.append(("DUE;VALUE=DATE", ics.day(row["due"])))
        else:
            props.append(("DUE", ics.utc(row["due"])))
    props.append(("SUMMARY", ics.escape(row["title"] or "(no title)")))
    if row["notes"]:
        props.append(("DESCRIPTION", ics.escape(row["notes"])))
    if row["list"]:
        props.append(("CATEGORIES", ics.escape(row["list"])))
    ics_priority = {"High": 1, "Medium": 5, "Low": 9}.get(row["priority"])
    if ics_priority:
        props.append(("PRIORITY", str(ics_priority)))
    if row["done"]:
        props.append(("STATUS", "COMPLETED"))
        if row["completed"]:
            props.append(("COMPLETED", ics.utc(row["completed"])))
    else:
        props.append(("STATUS", "NEEDS-ACTION"))
    return ["BEGIN:VTODO"] + ics.lines_of(props) + ["END:VTODO"]


def write_ics(base, rows):
    """An iCalendar file of the reminders (to-dos) that calendar and task
    programs import."""
    return ics.write(base + ".ics", [_todo_lines(r) for r in rows
                                     if not r["deleted"]], "Reminders")


def datasets(conn, index):
    reminders, lists = all_rows(conn, index)
    if not reminders and not lists:
        return []
    counts = {}
    for row in reminders:
        if row["deleted"]:
            continue
        entry = counts.setdefault((row["account"], row["list"]), [0, 0])
        entry[0] += 1
        entry[1] += 0 if row["done"] else 1
    list_rows = [{"list": item["list"], "account": item["account"],
                  "total": counts.get((item["account"], item["list"]),
                                      [0, 0])[0],
                  "open": counts.get((item["account"], item["list"]),
                                     [0, 0])[1]}
                 for item in lists]
    return [
        Dataset("reminders", "Reminders", [
            Column("due", "Due", 130, "date", format=_due_text),
            Column("title", "Reminder", 320),
            Column("list", "List", 150),
            Column("priority", "Priority", 70),
            Column("status", "Status", 70),
            Column("created", "Created", 130, "date")],
            reminders, sort=("due", False), details=_details,
            formats={"ics": ("To-do file (.ics, importable)", write_ics)}),
        Dataset("lists", "Lists", [
            Column("list", "List", 260),
            Column("account", "Account", 160),
            Column("total", "Reminders", 80, "number", "e"),
            Column("open", "Not done", 80, "number", "e")],
            list_rows, sort=("total", True)),
    ]


class RemindersReader:
    def __init__(self, conn, index):
        self.conn, self.index = conn, index

    def datasets(self):
        return datasets(self.conn, self.index)
