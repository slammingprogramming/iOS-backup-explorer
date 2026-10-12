# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The medications you track in the Health app, and the doses you logged.

Where it is stored (iOS 16 and later):

* a medication is a *user domain concept* (``user_domain_concepts``, listed in
  ``medication_user_domain_concepts``); its words (name, strength, form...)
  are rows of ``user_domain_concept_localized_strings`` and
  ``user_domain_concept_properties``, each with a property number;
* its schedules are ``medication_schedules`` (one row for each schedule, with
  the dates it runs between);
* each time a dose was due or logged is a row of
  ``medication_dose_event_samples``: the dose planned and the dose taken, the
  time it was scheduled for (the sample's own dates are when it was logged),
  and a status number.

What is **checked**: the fields below were identified by the owner of the
backups looking at their own medications (the name, the full product name, the
active ingredients and the form each sit in a field of their own, the same two
medications in iOS 16 backups). The two statuses named were read from the data
(entries that never got a dose logged, and entries that all did); a status
number beyond those is shown as "Status N", never guessed.

No GUI.
"""

from .common import apple_time, table_columns
from .records import Column, Dataset, sqlite_rows

# The strings a medication is described by ("L<number>" is a localized
# string, "P<number>" a property): the name it is tracked under, the full
# product name (with the strength, when it has one), the active ingredients
# and the form (tablet, capsule...).
NAME_KEYS = ("L160007",)
PRODUCT_KEYS = ("L160012",)
INGREDIENT_KEYS = ("L160009",)
FORM_KEYS = ("L160010",)

# the meaning of a dose event's status number: 1 is an entry that never got a
# dose logged, 4 one that did (every one of them has an amount)
STATUSES = {1: "Not answered", 4: "Taken"}
ORIGINS = {}


def _strings(conn, udc_ids):
    """``{udc_id: {"L<n>" / "P<n>": text}}`` for the medications."""
    found = {u: {} for u in udc_ids}
    if "udc_id" in table_columns(conn, "user_domain_concept_localized_strings"):
        for udc, number, text in sqlite_rows(
                conn, "SELECT udc_id, property_type, string_value FROM "
                      "user_domain_concept_localized_strings ORDER BY ROWID"):
            if udc in found and text:
                key = f"L{number}"
                found[udc].setdefault(key, text)
    if "udc_id" in table_columns(conn, "user_domain_concept_properties"):
        for udc, number, text in sqlite_rows(
                conn, "SELECT udc_id, property_type, string_value FROM "
                      "user_domain_concept_properties WHERE string_value IS "
                      "NOT NULL"):
            if udc in found and text:
                found[udc].setdefault(f"P{number}", text)
    return found


def _pick(strings, keys):
    for key in keys:
        if strings.get(key):
            return strings[key]
    return ""


def medication_rows(conn):
    """``(rows, names)``: one row for each medication, and ``{uuid: name}``."""
    if "udc_id" not in table_columns(conn, "medication_user_domain_concepts"):
        return [], {}
    concepts = sqlite_rows(
        conn, "SELECT m.udc_id, u.uuid, u.deleted, u.creation_date FROM "
              "medication_user_domain_concepts m JOIN user_domain_concepts u "
              "ON u.udc_id = m.udc_id ORDER BY u.creation_date")
    strings = _strings(conn, [c[0] for c in concepts])
    doses = {}
    if "medication_uuid" in table_columns(
            conn, "medication_dose_event_samples"):
        for uuid, status, count, last in sqlite_rows(
                conn, "SELECT d.medication_uuid, d.status, COUNT(*), "
                      "MAX(s.start_date) FROM medication_dose_event_samples d"
                      " LEFT JOIN samples s ON s.data_id = d.data_id "
                      "GROUP BY d.medication_uuid, d.status"):
            doses.setdefault(bytes(uuid) if uuid else b"", {})[status] = (
                count, last)
    schedules = {}
    if "medication_uuid" in table_columns(conn, "medication_schedules"):
        for uuid, count in sqlite_rows(
                conn, "SELECT medication_uuid, COUNT(*) FROM "
                      "medication_schedules WHERE COALESCE(deleted, 0) = 0 "
                      "GROUP BY medication_uuid"):
            schedules[bytes(uuid) if uuid else b""] = count
    rows, names = [], {}
    for udc, uuid, deleted, created in concepts:
        key = bytes(uuid) if uuid else b""
        name = _pick(strings[udc], NAME_KEYS) or f"Medication {udc}"
        names[key] = name
        mine = doses.get(key, {})
        taken = mine.get(4, (0, None))
        rows.append({
            "name": name,
            "product": _pick(strings[udc], PRODUCT_KEYS),
            "ingredients": _pick(strings[udc], INGREDIENT_KEYS),
            "form": _pick(strings[udc], FORM_KEYS),
            "added": apple_time(created), "removed": bool(deleted),
            "schedules": schedules.get(key, 0),
            "taken": taken[0], "last_taken": apple_time(taken[1])
            if taken[1] is not None else None,
            "logged": sum(count for count, _last in mine.values()),
            "strings": dict(strings[udc])})
    return rows, names


def dose_rows(conn, names):
    columns = table_columns(conn, "medication_dose_event_samples")
    if "status" not in columns:
        return []
    # iOS 26 records the unit of the amounts ("tablet"); earlier ones do not
    unit = "d.unit_string" if "unit_string" in columns else "NULL"
    rows = []
    for (uuid, planned, taken, scheduled, status, origin, start,
         unit) in sqlite_rows(
            conn, "SELECT d.medication_uuid, d.scheduled_dose_quantity, "
                  "d.dose_quantity, d.scheduled_date, d.status, "
                  f"d.log_origin, s.start_date, {unit} FROM "
                  "medication_dose_event_samples d LEFT JOIN samples s ON "
                  "s.data_id = d.data_id ORDER BY d.scheduled_date, "
                  "s.start_date"):
        rows.append({
            "scheduled": apple_time(scheduled), "logged": apple_time(start),
            "medication": names.get(bytes(uuid) if uuid else b"",
                                    "(a medication that is gone)"),
            "planned": planned, "taken": taken,
            "unit": str(unit).strip() if unit else "",
            "status": STATUSES.get(status, f"Status {status}"),
            "origin": ORIGINS.get(origin, f"Origin {origin}"
                                  if origin is not None else "")})
    return rows


def _amount(value, unit=""):
    if value is None:
        return ""
    return f"{value:g} {unit}" if unit else f"{value:g}"


def datasets(conn):
    medications, names = medication_rows(conn)
    result = []
    if medications:
        result.append(Dataset(
            "medications", "Medications", [
                Column("name", "Medication", 200),
                Column("product", "Product", 260),
                Column("ingredients", "Active ingredients", 220),
                Column("form", "Form", 70),
                Column("added", "Added", 130, "date"),
                Column("schedules", "Schedules", 80, "number", "e"),
                Column("taken", "Doses taken", 90, "number", "e"),
                Column("last_taken", "Last taken", 130, "date"),
                Column("logged", "Log entries", 90, "number", "e")],
            medications, sort=("added", False),
            note="The medications you track in the Health app. Doses are "
                 "counted from the log, where each due dose is an entry.",
            details=lambda row: row["name"] + (
                "  (removed)" if row["removed"] else "") + "\n" + "\n".join(
                    f"{key}: {text}" for key, text in sorted(
                        row["strings"].items()))))
    doses = dose_rows(conn, names)
    if doses:
        result.append(Dataset(
            "medication_doses", "Medication log", [
                Column("scheduled", "Scheduled for", 140, "date"),
                Column("medication", "Medication", 240),
                Column("status", "Status", 120),
                Column("planned", "Planned dose", 90, "text", "e",
                       format=lambda r: _amount(r["planned"], r["unit"])),
                Column("taken", "Dose taken", 90, "text", "e",
                       format=lambda r: _amount(r["taken"], r["unit"])),
                Column("logged", "Logged at", 140, "date")],
            doses, sort=("scheduled", True),
            note="Each row is a dose that was due or that you logged. A "
                 "status shown as 'Status N' is one whose meaning has not "
                 "been checked."))
    return result
