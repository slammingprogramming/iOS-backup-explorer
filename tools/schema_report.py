#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A layout report: how the databases in a backup are built, without what is in
them.

    python tools/schema_report.py "<backup folder>" [--password-window]
        report on every database the program reads (the default)
    python tools/schema_report.py "<backup folder>" --path "HomeDomain/Library/SMS/sms.db"
        report on one file (repeat --path for more)
    python tools/schema_report.py "<backup folder>" --find notes
        list the database files whose path contains a word, to find where an
        app keeps its data (a path can name an app you have installed: look
        before you post it)
    add --sql to print each database's CREATE statements (the layout as SQLite
        itself writes it), for a test fixture

For each SQLite database it prints the tables with their columns and **how many
rows** each has; for a Core Data database also the names of its entities. For a
property list it prints the names and kinds of the **top-level** keys only. It
never prints a row, a value, a text, a name, a number or a date from the
backup; the report is meant to be pasted into an issue (see
``docs/HELPING.md``). An encrypted backup asks for its password
(``--password-prompt`` on the terminal or ``--password-window`` in a small
window); it is used to open the backup and is not stored.
"""

import argparse
import os
import plistlib
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import backup_access                                    # noqa: E402

SQLITE_MAGIC = b"SQLite format 3\x00"
DATABASE_EXTENSIONS = (".sqlite", ".db", ".sqlitedb", ".storedata", ".sqlite3")


def known_paths(index):
    """The files the program reads, that the backup holds: the paths named
    by each tab's module, and those its ``discover`` finds."""
    from ios_apps import registry
    modules = [getattr(registry, name) for name in (
        "accounts", "books", "calendar_events", "calls", "contacts", "health",
        "icloud_drive", "installed_apps", "keychain", "maps", "messages",
        "network", "notes", "photos", "podcasts", "privacy", "recents",
        "reminders", "safari", "screentime", "voicemail", "voice_memos")]
    found, missing = [], []

    def consider(path):
        if not isinstance(path, str) or "/" not in path:
            return
        node = index.get(path)
        bucket = found if node is not None and not node.is_dir else missing
        if path not in found and path not in missing:
            bucket.append(path)

    for module in modules:
        for attribute in ("DATABASE", "DATABASES", "PATH", "SOURCES"):
            value = getattr(module, attribute, None)
            for path in ((value,) if isinstance(value, str)
                         else value if isinstance(value, (tuple, list))
                         else ()):
                consider(path)
        discover = getattr(module, "discover", None)
        if callable(discover):
            try:
                for path in discover(index) or ():
                    consider(path)
            except Exception:                         # (a reader's problem,
                pass                                  # not the report's)
    return found, missing


def find_paths(index, word):
    """Database-like files whose path contains *word* (any case)."""
    word = word.lower()
    result = []

    def walk(node, path):
        for name, child in sorted(node.children.items()):
            here = f"{path}/{name}" if path else name
            if child.is_dir:
                walk(child, here)
            elif word in here.lower() and name.lower().endswith(
                    DATABASE_EXTENSIONS + (".plist",)):
                result.append(here)
    walk(index.root, "")
    return result


# ── Describing one file ──────────────────────────────────────

def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def describe_sqlite(path):
    """``{"tables": [(name, rows, [(column, type)])], "entities": [...],
    "sql": [...]}`` for the SQLite database at *path*; never any row."""
    # (a copy in a temporary folder, with its journal files beside it, so
    # that what the phone had not yet written to the main file is seen)
    conn = sqlite3.connect(path)
    try:
        tables, sql = [], []
        for name, statement in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            try:
                rows = conn.execute(
                    f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0]
            except sqlite3.Error:           # (a virtual table, say)
                rows = None
            columns = [(c[1], c[2]) for c in conn.execute(
                f"PRAGMA table_info({_quote(name)})")]
            tables.append((name, rows, columns))
            if statement:
                sql.append(statement.strip() + ";")
        for statement, in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('index', "
                "'view', 'trigger') AND sql IS NOT NULL ORDER BY name"):
            sql.append(statement.strip() + ";")
        entities = []
        if any(t[0] == "Z_PRIMARYKEY" for t in tables):
            # Core Data: the number of each kind of record and its name; the
            # numbers differ between iOS versions
            try:
                entities = [(n, name) for n, name in conn.execute(
                    "SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY ORDER BY Z_ENT")]
            except sqlite3.Error:
                pass
        return {"tables": tables, "entities": entities, "sql": sql}
    finally:
        conn.close()


def _kind(value):
    if isinstance(value, dict):
        return f"dictionary of {len(value)}"
    if isinstance(value, list):
        return f"list of {len(value)}"
    if isinstance(value, (bytes, bytearray)):
        return f"{len(value)} bytes"
    if isinstance(value, str):
        return f"text of {len(value)}"
    return type(value).__name__


def describe_plist(path):
    """``{"keys": [(key, kind)]}``: only the top level of a property list."""
    with open(path, "rb") as handle:
        data = plistlib.load(handle)
    if isinstance(data, dict):
        return {"keys": [(str(k), _kind(v)) for k, v in sorted(
            data.items(), key=lambda item: str(item[0]))]}
    return {"keys": [("(the file itself)", _kind(data))]}


def describe(path):
    """A description of the file at *path*, or ``{"other": reason}``."""
    with open(path, "rb") as handle:
        head = handle.read(16)
    try:
        if head == SQLITE_MAGIC:
            return describe_sqlite(path)
        if head[:6] == b"bplist" or head[:5] == b"<?xml":
            return describe_plist(path)
    except (sqlite3.Error, plistlib.InvalidFileException, ValueError,
            OSError) as error:
        return {"other": f"could not be read ({type(error).__name__})"}
    return {"other": "neither a SQLite database nor a property list"}


# ── The report ───────────────────────────────────────────────

def _size(number):
    if number is None:
        return "?"
    return f"{number / 1024:,.0f} KB" if number >= 1024 else f"{number} B"


def markdown(entries, missing=(), sql=False):
    """The report text. *entries* is ``[(backup path, size, description)]``."""
    lines = []
    for path, size, info in entries:
        lines.append(f"### `{path}` ({_size(size)})")
        if "other" in info:
            lines += ["", f"This file {info['other']}.", ""]
            continue
        if "keys" in info:
            lines += ["", "| Key | Kind |", "|---|---|"]
            lines += [f"| {key} | {kind} |" for key, kind in info["keys"]]
            lines.append("")
            continue
        if info["entities"]:
            lines += ["", "Entities: " + ", ".join(
                f"{number} {name}" for number, name in info["entities"]), ""]
        lines += ["", "| Table | Rows | Columns |", "|---|---|---|"]
        for name, rows, columns in info["tables"]:
            shown = "?" if rows is None else f"{rows:,}"
            cols = ", ".join(f"{c} {t}".strip() for c, t in columns)
            lines.append(f"| {name} | {shown} | {cols} |")
        lines.append("")
        if sql:
            lines += ["<details><summary>CREATE statements</summary>", "",
                      "```sql"] + info["sql"] + ["```", "", "</details>", ""]
    if missing:
        lines += ["### Known files this backup does not have", ""]
        lines += [f"- `{path}`" for path in missing]
        lines.append("")
    return "\n".join(lines)


def build(opened, paths=None, sql=False):
    """The report for the open backup: the files in *paths*, or every file
    the program reads. Returns the Markdown text."""
    if paths:
        wanted, missing = list(paths), []
    else:
        wanted, missing = known_paths(opened.index)
    with backup_access.scratch_folder() as folder:
        local = opened.copy_to(folder, wanted)
        entries = []
        for path in wanted:
            if path not in local:
                missing.append(path)
                continue
            entries.append((path, opened.size(path), describe(local[path])))
    return markdown(entries, missing, sql)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder")
    parser.add_argument("--path", action="append", default=[],
                        help="report on this file (Domain/path); repeat for "
                        "more")
    parser.add_argument("--find", help="list database files whose path "
                        "contains this word")
    parser.add_argument("--sql", action="store_true",
                        help="also print the CREATE statements")
    backup_access.add_password_options(parser)
    options = parser.parse_args(argv)
    password = backup_access.password_from(options)
    try:
        with backup_access.open_backup(os.path.abspath(options.folder),
                                       password) as opened:
            if options.find:
                paths = find_paths(opened.index, options.find)
                sys.stdout.write("\n".join(f"- `{p}`" for p in paths)
                                 + ("\n" if paths else "No such file.\n"))
            else:
                sys.stdout.write(build(opened, options.path, options.sql))
    except Exception as error:                  # a message, not a traceback
        sys.stdout.write(f"The backup did not open: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
