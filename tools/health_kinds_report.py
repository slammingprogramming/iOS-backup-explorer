#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A report on the Health data types a backup has that the program cannot name.

    python tools/health_kinds_report.py "<backup folder>" [--password-window]

Health stores every sample with a number for its kind. A database of iOS 13 or
later names most of them itself; the ones it does not name are shown as
"Type N" in the program. This tool lists those, with just enough to help work
out what each is: how many samples, in which years, whether it is a
measurement or an event, the range of its values and the units used, or (for an
event) which values it takes. Names the program does not know stay unknown; see
``docs/HEALTH.md`` for why none is guessed.

It prints **no date, no source, no name and no individual sample**: counts,
years, the smallest and largest value of each kind, and the distinct values of
an event kind. Those summaries are still your health data, so look at the table
and **delete any row you would rather not share** before posting it (see
``docs/HELPING.md``). An encrypted backup asks for its password
(``--password-prompt`` or ``--password-window``); it is not stored.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import backup_access                                    # noqa: E402

DATABASE = "HealthDomain/Health/healthdb_secure.sqlite"
APPLE_EPOCH = 978307200
EVENT_VALUES = 12             # (up to this many distinct values are listed)


def _year(stamp):
    if stamp is None:
        return None
    return datetime.fromtimestamp(stamp + APPLE_EPOCH, timezone.utc).year


def _round(value):
    return float(f"{value:.4g}") if isinstance(value, (int, float)) else value


def table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = ?", (name,)).fetchone() is not None


def kind_rows(conn):
    """One dict for each kind the database holds but does not name, and the
    counts of how many kinds it holds and names."""
    from ios_apps import health
    names = health.kind_names(conn)
    named_by_database = health.database_names_kinds(conn)
    rows, present = [], 0
    for number, count, first, last in conn.execute(
            "SELECT data_type, COUNT(*), MIN(start_date), MAX(end_date) FROM "
            "samples GROUP BY data_type ORDER BY data_type"):
        present += 1
        if number in names:
            continue
        row = {"number": number, "samples": count,
               "years": (_year(first), _year(last)), "kind": "other",
               "range": "", "units": "", "values": ""}
        if table_exists(conn, "quantity_samples"):
            low, high, units, held = conn.execute(
                "SELECT MIN(q.quantity), MAX(q.quantity), "
                "COUNT(DISTINCT q.original_unit), COUNT(*) FROM "
                "quantity_samples q JOIN samples s ON s.data_id = q.data_id "
                "WHERE s.data_type = ?", (number,)).fetchone()
            if held:
                row["kind"] = "measurement"
                row["range"] = f"{_round(low):g} to {_round(high):g}"
                row["units"] = f"{units} unit{'s' if units != 1 else ''} " \
                    "recorded"
        if row["kind"] == "other" and table_exists(conn, "category_samples"):
            values = [v for (v,) in conn.execute(
                "SELECT DISTINCT c.value FROM category_samples c JOIN "
                "samples s ON s.data_id = c.data_id WHERE s.data_type = ? "
                "ORDER BY c.value LIMIT ?", (number, EVENT_VALUES + 1))]
            if values:
                row["kind"] = "event"
                row["values"] = ", ".join(str(v) for v in values[
                    :EVENT_VALUES]) + (", ..." if len(values) > EVENT_VALUES
                                       else "")
        rows.append(row)
    return rows, present, named_by_database


def markdown(rows, present, named_by_database):
    lines = [f"The database holds {present} kinds; {len(rows)} have no name."]
    if not named_by_database:
        lines.append(
            "This database does not name its kinds itself (iOS 12 or "
            "earlier): the program names those it has in its table of "
            "numbers, and these are the others.")
    lines.append("")
    if not rows:
        return "\n".join(lines + ["Every kind is named.", ""])
    lines += ["| Number | Samples | Years | Looks like | Values | Units | "
              "Event values |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        first, last = row["years"]
        years = f"{first}" if first == last else f"{first}-{last}"
        lines.append(
            f"| {row['number']} | {row['samples']:,} | {years} | "
            f"{row['kind']} | {row['range']} | {row['units']} | "
            f"{row['values']} |")
    lines.append("")
    return "\n".join(lines)


def build(opened):
    """The report text for the open backup."""
    if opened.file_id(DATABASE) is None:
        return ("This backup has no Health database (Health data is only in "
                "encrypted backups).\n")
    with backup_access.scratch_folder() as folder:
        local = opened.copy_to(folder, [DATABASE])
        conn = sqlite3.connect(local[DATABASE])
        try:
            return markdown(*kind_rows(conn))
        finally:
            conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder")
    backup_access.add_password_options(parser)
    options = parser.parse_args(argv)
    password = backup_access.password_from(options)
    try:
        with backup_access.open_backup(os.path.abspath(options.folder),
                                       password) as opened:
            sys.stdout.write(build(opened))
    except Exception as error:
        sys.stdout.write(f"The backup did not open: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
