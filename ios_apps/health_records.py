# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The contents of the Health records (labs, immunizations, conditions...).

Health keeps the records it downloads from a clinic or hospital exactly as
they were sent, as **FHIR** resources (an open standard for health records,
https://hl7.org/fhir): ``original_fhir_resources.raw_content`` holds each as
JSON. Because FHIR names its fields in the standard, this reader does not need
to guess what anything means: an ``Observation`` has a ``code`` (what was
measured), a ``valueQuantity`` (the result and unit), a ``referenceRange``
and an ``interpretation``.

Tables made (each only if there is something to show):

* **Lab results** (``Observation``)
* **Immunizations** (``Immunization``)
* **Conditions and procedures** (``Condition``, ``Procedure``,
  ``AllergyIntolerance``)
* **Prescriptions from providers** (``MedicationRequest`` and the other
  ``Medication...`` resources)
* **Clinical documents** (``DocumentReference``, ``DiagnosticReport``),
  with the files they carry when the record holds them

A resource that cannot be read is skipped and counted, never guessed at.
No GUI.
"""

import base64
import binascii
import json
import os
import re
from datetime import datetime, timezone

from .common import format_datetime, table_columns
from .export_util import safe_filename
from .records import Column, Dataset, format_day, sqlite_rows

TABLE = "original_fhir_resources"
_NAME_CHARS = re.compile(r"[^\w\-. ]+")


# ── Reading FHIR values ──────────────────────────────────────

def concept_text(concept):
    """The words of a ``CodeableConcept``: its text, else the display of its
    first coding that has one, else the first code."""
    if isinstance(concept, list):
        for item in concept:
            found = concept_text(item)
            if found:
                return found
        return ""
    if not isinstance(concept, dict):
        return ""
    text = concept.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    codings = concept.get("coding")
    for coding in codings if isinstance(codings, list) else ():
        if isinstance(coding, dict):
            display = coding.get("display")
            if isinstance(display, str) and display.strip():
                return display.strip()
    for coding in codings if isinstance(codings, list) else ():
        if isinstance(coding, dict) and coding.get("code"):
            return str(coding["code"])
    return ""


def parse_moment(text):
    """``(unix seconds, precision)`` for a FHIR date or date-time; precision
    is ``"day"`` for a date without a time (kept as midnight UTC) and
    ``"time"`` otherwise. ``(None, "")`` if it is not a date."""
    if not isinstance(text, str) or len(text) < 4:
        return None, ""
    text = text.strip()
    try:
        if re.fullmatch(r"\d{4}", text):
            moment, precision = datetime(int(text), 1, 1), "day"
        elif re.fullmatch(r"\d{4}-\d\d", text):
            moment, precision = datetime(int(text[:4]), int(text[5:7]), 1), \
                "day"
        elif re.fullmatch(r"\d{4}-\d\d-\d\d", text):
            moment, precision = datetime.strptime(text, "%Y-%m-%d"), "day"
        else:
            cleaned = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp(), "time"
    except ValueError:
        return None, ""
    return moment.replace(tzinfo=timezone.utc).timestamp(), precision


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _show_number(value):
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}" if isinstance(value, float) else str(value)


def quantity_text(quantity):
    """``12.5 mg/dL`` for a ``Quantity`` (with its comparator, if any)."""
    if not isinstance(quantity, dict):
        return ""
    number = _number(quantity.get("value"))
    if number is None:
        return ""
    unit = quantity.get("unit") or quantity.get("code") or ""
    comparator = quantity.get("comparator") or ""
    return f"{comparator}{_show_number(number)}" + (f" {unit}" if unit
                                                     else "")


def value_text(resource):
    """The result an ``Observation`` (or one of its components) holds."""
    if "valueQuantity" in resource:
        return quantity_text(resource["valueQuantity"])
    if "valueCodeableConcept" in resource:
        return concept_text(resource["valueCodeableConcept"])
    for key in ("valueString", "valueInteger", "valueBoolean", "valueDateTime",
                "valueTime"):
        if key in resource and resource[key] is not None:
            value = resource[key]
            return ("yes" if value is True else "no" if value is False
                    else str(value))
    if isinstance(resource.get("valueRatio"), dict):
        ratio = resource["valueRatio"]
        return (quantity_text(ratio.get("numerator")) + " / "
                + quantity_text(ratio.get("denominator"))).strip(" /")
    if isinstance(resource.get("valueRange"), dict):
        low = quantity_text(resource["valueRange"].get("low"))
        high = quantity_text(resource["valueRange"].get("high"))
        return f"{low} to {high}".strip()
    return ""


def range_text(ranges):
    """The reference ranges of an ``Observation`` as words."""
    parts = []
    for item in ranges if isinstance(ranges, list) else ():
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
            continue
        low, high = quantity_text(item.get("low")), \
            quantity_text(item.get("high"))
        if low and high:
            parts.append(f"{low} to {high}")
        elif low:
            parts.append(f"at least {low}")
        elif high:
            parts.append(f"at most {high}")
    return "; ".join(parts)


def _display(reference):
    if isinstance(reference, list):
        reference = reference[0] if reference else None
    if isinstance(reference, dict):
        return str(reference.get("display") or "")
    return ""


def _note_text(notes):
    return " ".join(n.get("text", "") for n in notes
                    if isinstance(n, dict)) if isinstance(notes, list) else ""


def _first(resource, *keys):
    for key in keys:
        if resource.get(key):
            return resource[key]
    return None


def _when(resource, *keys):
    for key in keys:
        stamp, precision = parse_moment(resource.get(key))
        if stamp is not None:
            return stamp, precision
    return None, ""


# ── One table row for each kind of resource ──────────────────

def observation_row(resource):
    components = resource.get("component")
    result = value_text(resource)
    if not result and isinstance(components, list):
        # a panel such as blood pressure: "Systolic 120 mmHg, Diastolic 80"
        result = ", ".join(
            f"{concept_text(c.get('code'))} {value_text(c)}".strip()
            for c in components if isinstance(c, dict) and value_text(c))
    if not result and resource.get("dataAbsentReason"):
        result = "(" + (concept_text(resource["dataAbsentReason"])
                        or "no result") + ")"
    when, precision = _when(resource, "effectiveDateTime", "issued")
    if when is None and isinstance(resource.get("effectivePeriod"), dict):
        when, precision = _when(resource["effectivePeriod"], "start", "end")
    return {
        "when": when, "precision": precision,
        "category": concept_text(resource.get("category")),
        "test": concept_text(resource.get("code")),
        "result": result,
        "range": range_text(resource.get("referenceRange")),
        "flag": concept_text(resource.get("interpretation")),
        "status": str(resource.get("status") or ""),
        "note": _note_text(resource.get("note")) or str(
            resource.get("comments") or ""),
        "by": _display(resource.get("performer"))}


def immunization_row(resource):
    when, precision = _when(resource, "occurrenceDateTime",
                            "occurrenceString", "date")
    return {
        "when": when, "precision": precision,
        "vaccine": concept_text(resource.get("vaccineCode")),
        "status": str(resource.get("status") or ""),
        "lot": str(resource.get("lotNumber") or ""),
        "by": _display(resource.get("performer"))
        or _display(resource.get("manufacturer")),
        "site": concept_text(resource.get("site")),
        "note": _note_text(resource.get("note"))}


def condition_row(resource):
    kind = resource.get("resourceType")
    when, precision = _when(resource, "onsetDateTime", "performedDateTime",
                            "recordedDate", "assertedDate", "date")
    if when is None and isinstance(resource.get("performedPeriod"), dict):
        when, precision = _when(resource["performedPeriod"], "start", "end")
    status = resource.get("clinicalStatus") or resource.get("status")
    return {
        "when": when, "precision": precision,
        "kind": {"Condition": "Condition", "Procedure": "Procedure",
                 "AllergyIntolerance": "Allergy"}.get(kind, str(kind)),
        "name": concept_text(resource.get("code")),
        "status": concept_text(status) if isinstance(status, dict)
        else str(status or ""),
        "detail": _reaction_text(resource)
        or concept_text(resource.get("category")),
        "by": _display(resource.get("recorder"))
        or _display(resource.get("asserter"))}


def _reaction_text(resource):
    found = []
    for reaction in resource.get("reaction") or ():
        if isinstance(reaction, dict):
            found.append(concept_text(reaction.get("manifestation"))
                         or str(reaction.get("description") or ""))
    return ", ".join(x for x in found if x)


def prescription_row(resource):
    medication = concept_text(resource.get("medicationCodeableConcept"))
    if not medication and isinstance(resource.get("medicationReference"),
                                     dict):
        wanted = str(resource["medicationReference"].get("reference") or "")
        for item in resource.get("contained") or ():
            if isinstance(item, dict) and (
                    wanted == "#" + str(item.get("id", "\0"))
                    or wanted.endswith("/" + str(item.get("id", "\0")))):
                medication = concept_text(item.get("code"))
        medication = medication or _display(resource["medicationReference"])
    when, precision = _when(resource, "authoredOn", "dateAsserted",
                            "effectiveDateTime", "whenHandedOver",
                            "whenPrepared")
    instructions = []
    for dosage in resource.get("dosageInstruction") or \
            resource.get("dosage") or ():
        if isinstance(dosage, dict):
            instructions.append(str(dosage.get("text") or ""))
    return {
        "when": when, "precision": precision, "name": medication,
        "kind": str(resource.get("resourceType") or ""),
        "instructions": " ".join(x for x in instructions if x),
        "status": str(resource.get("status") or ""),
        "intent": str(resource.get("intent") or ""),
        "by": _display(resource.get("requester"))
        or _display(resource.get("recorder")) or _display(
            resource.get("informationSource"))}


def document_row(resource):
    kind = resource.get("resourceType")
    when, precision = _when(resource, "date", "effectiveDateTime", "issued")
    files = []
    for content in resource.get("content") or ():
        attachment = content.get("attachment") if isinstance(content, dict) \
            else None
        if isinstance(attachment, dict):
            files.append(attachment)
    for attachment in resource.get("presentedForm") or ():
        if isinstance(attachment, dict):
            files.append(attachment)
    return {
        "when": when, "precision": precision,
        "kind": "Report" if kind == "DiagnosticReport" else "Document",
        "type": concept_text(resource.get("type"))
        or concept_text(resource.get("code")),
        "title": next((str(a.get("title")) for a in files
                       if a.get("title")), "") or str(
            resource.get("description") or ""),
        "status": str(resource.get("status") or ""),
        "by": _display(resource.get("author"))
        or _display(resource.get("performer")),
        "files": files}


ROWS = {
    "Observation": ("labs", observation_row),
    "Immunization": ("immunizations", immunization_row),
    "Condition": ("conditions", condition_row),
    "Procedure": ("conditions", condition_row),
    "AllergyIntolerance": ("conditions", condition_row),
    "MedicationRequest": ("prescriptions", prescription_row),
    "MedicationStatement": ("prescriptions", prescription_row),
    "MedicationDispense": ("prescriptions", prescription_row),
    "MedicationAdministration": ("prescriptions", prescription_row),
    "DocumentReference": ("documents", document_row),
    "DiagnosticReport": ("documents", document_row),
}


def read_resources(conn):
    """``({table key: [rows]}, skipped)`` from the stored FHIR resources.
    *skipped* counts those that could not be read as JSON."""
    if "raw_content" not in table_columns(conn, TABLE):
        return {}, 0
    tables, skipped = {}, 0
    for kind, raw in sqlite_rows(
            conn, f"SELECT type, raw_content FROM {TABLE} ORDER BY ROWID"):
        route = ROWS.get(kind)
        if route is None:
            continue
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = bytes(raw).decode("utf-8")
            resource = json.loads(raw)
            if not isinstance(resource, dict):
                raise ValueError("not an object")
            row = route[1](resource)
        except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
            skipped += 1
            continue
        row["resource"] = resource
        tables.setdefault(route[0], []).append(row)
    return tables, skipped


# ── Showing them ─────────────────────────────────────────────

def _when_text(row):
    if row.get("when") is None:
        return ""
    return format_day(row["when"]) if row.get("precision") == "day" \
        else format_datetime(row["when"])


def _when_column(heading="Date", width=140):
    return Column("when", heading, width, "text", format=_when_text)


def _lines(row, pairs):
    return "\n".join(f"{label}: {row[key]}" for label, key in pairs
                     if row.get(key))


def _details(heading, pairs):
    def details(row):
        return f"{heading}\n" + _lines(row, pairs)
    return details


def _decoded(attachment):
    """The bytes of an attachment that the record carries inline, or None."""
    data = attachment.get("data") if isinstance(attachment, dict) else None
    if not isinstance(data, str):
        return None
    try:
        return base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError):
        return None


def _file_name(row, attachment, index):
    stem = attachment.get("title") or row.get("title") or row.get("type") \
        or "document"
    stem = _NAME_CHARS.sub("", str(stem)).strip(" .") or "document"
    mime = str(attachment.get("contentType") or "").lower()
    ext = {"application/pdf": ".pdf", "text/plain": ".txt",
           "text/html": ".html", "text/rtf": ".rtf", "application/rtf": ".rtf",
           "application/xml": ".xml", "text/xml": ".xml",
           "image/jpeg": ".jpg", "image/png": ".png",
           "application/json": ".json"}.get(mime.split(";")[0], ".bin")
    if os.path.splitext(stem)[1].lower() == ext:
        ext = ""
    return safe_filename(f"{index:03d} {stem}{ext}")


def write_documents(folder, rows, _copy_file):
    """Save the files the selected documents carry (the ones whose data is in
    the record). Returns ``(paths, notes)``."""
    os.makedirs(folder, exist_ok=True)
    paths, missing = [], 0
    for number, row in enumerate(rows, 1):
        for attachment in row.get("files") or ():
            data = _decoded(attachment)
            if not data:
                missing += 1
                continue
            path = os.path.join(folder, _file_name(row, attachment, number))
            with open(path, "wb") as handle:
                handle.write(data)
            paths.append(path)
    notes = (f"{missing:,} attachment{'s' if missing != 1 else ''} hold no "
             "data in the record itself (the clinic's file was never "
             "downloaded to the phone, or is not in the backup)."
             if missing else "")
    return paths, notes


def datasets(conn):
    tables, skipped = read_resources(conn)
    result = []
    note = (f" {skipped:,} record{'s' if skipped != 1 else ''} could not be "
            "read and are left out." if skipped else "")
    if tables.get("labs"):
        result.append(Dataset(
            "lab_results", "Lab results", [
                _when_column(),
                Column("category", "Kind", 110),
                Column("test", "Test", 240),
                Column("result", "Result", 160),
                Column("range", "Reference range", 150),
                Column("flag", "Flag", 90),
                Column("status", "Status", 80)],
            tables["labs"], sort=("when", True),
            note="Read from the records exactly as the provider sent them "
                 "(FHIR)." + note,
            details=_details("Result", (
                ("Test", "test"), ("Result", "result"),
                ("Reference range", "range"), ("Flag", "flag"),
                ("Kind", "category"), ("Status", "status"),
                ("Performed by", "by"), ("Notes", "note")))))
    if tables.get("immunizations"):
        result.append(Dataset(
            "immunizations", "Immunizations", [
                _when_column(),
                Column("vaccine", "Vaccine", 300),
                Column("status", "Status", 90),
                Column("lot", "Lot", 100),
                Column("by", "Given by", 200)],
            tables["immunizations"], sort=("when", True),
            details=_details("Immunization", (
                ("Vaccine", "vaccine"), ("Status", "status"),
                ("Lot number", "lot"), ("Given by", "by"),
                ("Site", "site"), ("Notes", "note")))))
    if tables.get("conditions"):
        result.append(Dataset(
            "conditions", "Conditions, allergies and procedures", [
                _when_column(),
                Column("kind", "Kind", 90),
                Column("name", "Name", 300),
                Column("status", "Status", 100),
                Column("detail", "Detail", 220)],
            tables["conditions"], sort=("when", True),
            details=_details("Record", (
                ("Kind", "kind"), ("Name", "name"), ("Status", "status"),
                ("Detail", "detail"), ("Recorded by", "by")))))
    if tables.get("prescriptions"):
        result.append(Dataset(
            "prescriptions", "Prescriptions from providers", [
                _when_column(),
                Column("name", "Medication", 260),
                Column("instructions", "Instructions", 280),
                Column("status", "Status", 80),
                Column("by", "Prescribed by", 180)],
            tables["prescriptions"], sort=("when", True),
            note="What clinics sent to the Health app. The medications "
                 "you track yourself are in Medications."
                 + note,
            details=_details("Prescription", (
                ("Medication", "name"), ("Instructions", "instructions"),
                ("Status", "status"), ("Kind of record", "kind"),
                ("Intent", "intent"), ("Prescribed by", "by")))))
    if tables.get("documents"):
        result.append(Dataset(
            "clinical_documents", "Clinical documents", [
                _when_column(),
                Column("kind", "Kind", 80),
                Column("type", "Type", 220),
                Column("title", "Title", 240),
                Column("by", "From", 200)],
            tables["documents"], sort=("when", True),
            file_formats={"files": (
                "The documents' files (those that are in the record)",
                write_documents)},
            note="Reports and documents that clinics sent. Some carry the "
                 "file itself (a PDF, for example); export \"The documents' "
                 "files\" to save them." + note,
            details=_details("Document", (
                ("Kind", "kind"), ("Type", "type"), ("Title", "title"),
                ("Status", "status"), ("From", "by")))))
    return result
