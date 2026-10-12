# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The contents of the Health records, read from their FHIR resources. Every
record here is invented."""

import base64
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from ios_apps import health as hl
from ios_apps import health_records as hr
from tests import fixture_health as fh

PDF = b"%PDF-1.4 an invented document"


def resource(kind, **fields):
    return json.dumps({"resourceType": kind, **fields})


RESOURCES = [
    ("Observation", resource(
        "Observation", status="final",
        category=[{"coding": [{"code": "laboratory",
                               "display": "Laboratory"}]}],
        code={"text": "Hemoglobin A1c"},
        effectiveDateTime="2025-03-04T08:15:00Z",
        valueQuantity={"value": 5.4, "unit": "%"},
        referenceRange=[{"low": {"value": 4, "unit": "%"},
                         "high": {"value": 5.6, "unit": "%"}}],
        interpretation=[{"coding": [{"code": "N", "display": "Normal"}]}],
        performer=[{"display": "Example Lab"}],
        note=[{"text": "Fasting."}])),
    ("Observation", resource(
        "Observation", status="final",
        code={"coding": [{"display": "Blood pressure"}]},
        effectiveDateTime="2025-03-05",
        component=[
            {"code": {"text": "Systolic"},
             "valueQuantity": {"value": 120, "unit": "mmHg"}},
            {"code": {"text": "Diastolic"},
             "valueQuantity": {"value": 80, "unit": "mmHg"}}])),
    ("Observation", resource(
        "Observation", status="final", code={"text": "Urine colour"},
        effectiveDateTime="2025-03-06T10:00:00+02:00",
        valueCodeableConcept={"text": "Yellow"})),
    ("Observation", resource(
        "Observation", status="final", code={"text": "Culture"},
        issued="2025-03-07T10:00:00Z", valueString="No growth",
        referenceRange=[{"text": "No growth"}])),
    ("Observation", resource(
        "Observation", status="cancelled", code={"text": "Sample lost"},
        effectiveDateTime="2025-03-08", dataAbsentReason={"text": "Not done"})),
    ("Observation", resource(
        "Observation", status="final", code={"coding": [{"code": "1234-5"}]},
        effectiveDateTime="2025-03-09", valueQuantity={"value": 7.0},
        referenceRange=[{"high": {"value": 10, "unit": "mg"}}, {"low": {
            "value": 1}}, "junk"])),
    ("Immunization", resource(
        "Immunization", status="completed",
        vaccineCode={"text": "Influenza vaccine"},
        occurrenceDateTime="2024-10-01", lotNumber="LOT42",
        performer=[{"actor": {"display": "x"}}],
        manufacturer={"display": "Example Pharma"},
        site={"text": "Left arm"})),
    ("Condition", resource(
        "Condition", code={"text": "Hay fever"},
        clinicalStatus={"coding": [{"code": "active"}]},
        onsetDateTime="2019-05-01", category=[{"text": "Problem list item"}],
        recorder={"display": "Dr Example"})),
    ("Procedure", resource(
        "Procedure", status="completed", code={"text": "Appendectomy"},
        performedPeriod={"start": "2015-06-01T09:00:00Z",
                         "end": "2015-06-01T10:00:00Z"})),
    ("AllergyIntolerance", resource(
        "AllergyIntolerance", code={"text": "Penicillin"},
        clinicalStatus={"coding": [{"display": "Active"}]},
        recordedDate="2020-01-02",
        reaction=[{"manifestation": [{"text": "Rash"}]},
                  {"description": "Hives"}])),
    ("MedicationRequest", resource(
        "MedicationRequest", status="active", intent="order",
        medicationCodeableConcept={"text": "Example tablets 10 mg"},
        authoredOn="2025-02-01T12:00:00Z",
        dosageInstruction=[{"text": "Take one daily"}, {"text": "With food"}],
        requester={"display": "Dr Example"})),
    ("MedicationRequest", resource(
        "MedicationRequest", status="stopped", intent="order",
        medicationReference={"reference": "#med1"},
        contained=[{"resourceType": "Medication", "id": "med1",
                    "code": {"text": "Contained medicine"}}],
        authoredOn="2024-02-01")),
    ("DocumentReference", resource(
        "DocumentReference", status="current", date="2025-04-01T09:00:00Z",
        type={"text": "Discharge summary"}, author=[{"display": "Dr Example"}],
        content=[{"attachment": {
            "contentType": "application/pdf", "title": "Summary",
            "data": base64.b64encode(PDF).decode()}}])),
    ("DocumentReference", resource(
        "DocumentReference", status="current", date="2025-04-02",
        type={"coding": [{"display": "Progress note"}]},
        content=[{"attachment": {"contentType": "text/html",
                                 "url": "https://example.com/doc/1"}}])),
    ("DiagnosticReport", resource(
        "DiagnosticReport", status="final", code={"text": "Chest X-ray"},
        effectiveDateTime="2025-04-03",
        performer=[{"display": "Example Imaging"}],
        presentedForm=[{"contentType": "text/plain", "title": "Report",
                        "data": base64.b64encode(b"Normal.").decode()}])),
    ("Patient", resource("Patient", gender="unknown")),          # not shown
    ("Observation", "{ this is not json"),
    ("Observation", "[1, 2]"),
]


def build(conn, resources=RESOURCES):
    conn.execute("CREATE TABLE original_fhir_resources (ROWID INTEGER PRIMARY "
                 "KEY, type TEXT, raw_content BLOB)")
    for kind, raw in resources:
        conn.execute("INSERT INTO original_fhir_resources (type, raw_content)"
                     " VALUES (?, ?)", (kind, raw.encode("utf-8")))
    conn.commit()


class ReadingTests(unittest.TestCase):
    def test_what_a_concept_says(self):
        self.assertEqual(hr.concept_text({"text": " Words "}), "Words")
        self.assertEqual(hr.concept_text({"coding": [
            {"code": "x"}, {"display": "Shown"}]}), "Shown")
        self.assertEqual(hr.concept_text({"coding": [{"code": "x"}]}), "x")
        self.assertEqual(hr.concept_text([{}, {"text": "second"}]), "second")
        for odd in (None, {}, "text", 5, {"coding": "x"}, {"text": 3}):
            self.assertEqual(hr.concept_text(odd), "")

    def test_dates(self):
        day, precision = hr.parse_moment("2025-03-05")
        self.assertEqual(precision, "day")
        self.assertEqual(day % 86400, 0)
        self.assertEqual(hr.parse_moment("2025")[1], "day")
        self.assertEqual(hr.parse_moment("2025-03")[1], "day")
        stamp, precision = hr.parse_moment("2025-03-06T10:00:00+02:00")
        self.assertEqual(precision, "time")
        self.assertEqual(stamp, hr.parse_moment("2025-03-06T08:00:00Z")[0])
        self.assertEqual(hr.parse_moment("2025-03-06T08:00:00")[0], stamp)
        for bad in (None, "", "yesterday", "2025-13-45", 5):
            self.assertEqual(hr.parse_moment(bad), (None, ""))

    def test_quantities(self):
        self.assertEqual(hr.quantity_text({"value": 5.4, "unit": "%"}), "5.4 %")
        self.assertEqual(hr.quantity_text({"value": 120.0, "code": "mmHg"}),
                         "120 mmHg")
        self.assertEqual(hr.quantity_text({"value": 3, "comparator": "<"}),
                         "<3")
        for odd in (None, {}, {"value": "x"}, {"value": True}, "5"):
            self.assertEqual(hr.quantity_text(odd), "")

    def test_values(self):
        self.assertEqual(hr.value_text({"valueBoolean": True}), "yes")
        self.assertEqual(hr.value_text({"valueBoolean": False}), "no")
        self.assertEqual(hr.value_text({"valueInteger": 4}), "4")
        self.assertEqual(hr.value_text({"valueRange": {
            "low": {"value": 1}, "high": {"value": 2}}}), "1 to 2")
        self.assertEqual(hr.value_text({"valueRatio": {
            "numerator": {"value": 1}, "denominator": {"value": 128}}}),
            "1 / 128")
        self.assertEqual(hr.value_text({}), "")

    def test_reference_ranges(self):
        self.assertEqual(hr.range_text([{"low": {"value": 1}, "high": {
            "value": 2, "unit": "u"}}]), "1 to 2 u")
        self.assertEqual(hr.range_text([{"high": {"value": 2}}]), "at most 2")
        self.assertEqual(hr.range_text([{"low": {"value": 1}}]), "at least 1")
        self.assertEqual(hr.range_text([{"text": "Normal"}, "junk"]),
                         "Normal")
        self.assertEqual(hr.range_text(None), "")


class TableTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        build(self.conn)
        self.sets = {d.key: d for d in hr.datasets(self.conn)}

    def test_the_tables_and_their_order(self):
        self.assertEqual(list(self.sets), [
            "lab_results", "immunizations", "conditions", "prescriptions",
            "clinical_documents"])

    def test_a_lab_result_in_full(self):
        rows = {r["test"]: r for r in self.sets["lab_results"].rows}
        a1c = rows["Hemoglobin A1c"]
        self.assertEqual(a1c["result"], "5.4 %")
        self.assertEqual(a1c["range"], "4 % to 5.6 %")
        self.assertEqual(a1c["flag"], "Normal")
        self.assertEqual(a1c["category"], "Laboratory")
        self.assertEqual(a1c["by"], "Example Lab")
        self.assertEqual(a1c["note"], "Fasting.")
        text = self.sets["lab_results"].details(a1c)
        for expected in ("Hemoglobin A1c", "5.4 %", "Example Lab", "Fasting."):
            self.assertIn(expected, text)

    def test_the_other_kinds_of_result(self):
        rows = {r["test"]: r for r in self.sets["lab_results"].rows}
        self.assertEqual(rows["Blood pressure"]["result"],
                         "Systolic 120 mmHg, Diastolic 80 mmHg")
        self.assertEqual(rows["Urine colour"]["result"], "Yellow")
        self.assertEqual(rows["Culture"]["result"], "No growth")
        self.assertEqual(rows["Culture"]["range"], "No growth")
        self.assertEqual(rows["Sample lost"]["result"], "(Not done)")
        self.assertEqual(rows["1234-5"]["result"], "7")
        self.assertEqual(rows["1234-5"]["range"], "at most 10 mg; at least 1")

    def test_dates_with_and_without_a_time(self):
        table = self.sets["lab_results"]
        rows = {r["test"]: r for r in table.rows}
        day = table.columns[0].show(None, rows["Blood pressure"])
        self.assertEqual(day, "2025-03-05")
        timed = table.columns[0].show(None, rows["Hemoglobin A1c"])
        self.assertIn("2025-03-04", timed)
        self.assertRegex(timed, r"\d\d:\d\d")

    def test_newest_first(self):
        table = self.sets["lab_results"]
        ordered = table.sorted_rows(table.rows)
        stamps = [r["when"] for r in ordered]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_an_immunization(self):
        row, = self.sets["immunizations"].rows
        self.assertEqual((row["vaccine"], row["lot"], row["status"]),
                         ("Influenza vaccine", "LOT42", "completed"))
        self.assertEqual(row["by"], "Example Pharma")
        self.assertIn("Left arm", self.sets["immunizations"].details(row))

    def test_conditions_procedures_and_allergies(self):
        rows = {r["name"]: r for r in self.sets["conditions"].rows}
        self.assertEqual(rows["Hay fever"]["kind"], "Condition")
        self.assertEqual(rows["Hay fever"]["status"], "active")
        self.assertEqual(rows["Appendectomy"]["kind"], "Procedure")
        self.assertIsNotNone(rows["Appendectomy"]["when"])     # from a period
        self.assertEqual(rows["Penicillin"]["kind"], "Allergy")
        self.assertEqual(rows["Penicillin"]["detail"], "Rash, Hives")
        self.assertEqual(rows["Penicillin"]["status"], "Active")

    def test_prescriptions(self):
        rows = {r["name"]: r for r in self.sets["prescriptions"].rows}
        one = rows["Example tablets 10 mg"]
        self.assertEqual(one["instructions"], "Take one daily With food")
        self.assertEqual(one["by"], "Dr Example")
        self.assertEqual(rows["Contained medicine"]["status"], "stopped")

    def test_documents_and_reports(self):
        rows = {r["type"] or r["title"]: r
                for r in self.sets["clinical_documents"].rows}
        self.assertEqual(rows["Discharge summary"]["title"], "Summary")
        self.assertEqual(rows["Progress note"]["kind"], "Document")
        self.assertEqual(rows["Chest X-ray"]["kind"], "Report")

    def test_unreadable_records_are_counted_and_left_out(self):
        tables, skipped = hr.read_resources(self.conn)
        self.assertEqual(skipped, 2)
        self.assertIn("2 records could not be read",
                      self.sets["lab_results"].note)
        self.assertNotIn("Patient", str(tables))


class DocumentFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-records-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        build(conn)
        table = {d.key: d for d in hr.datasets(conn)}["clinical_documents"]
        self.table = table

    def test_the_files_that_the_record_carries_are_saved(self):
        label, writer = self.table.file_formats["files"]
        paths, notes = writer(os.path.join(self.tmp, "out"), self.table.rows,
                              None)
        names = sorted(os.path.basename(p) for p in paths)
        self.assertEqual(len(names), 2)
        self.assertTrue(any(n.endswith("Summary.pdf") for n in names), names)
        self.assertTrue(any(n.endswith("Report.txt") for n in names), names)
        pdf = next(p for p in paths if p.endswith(".pdf"))
        with open(pdf, "rb") as handle:
            self.assertEqual(handle.read(), PDF)
        self.assertIn("1 attachment hold no data", notes)

    def test_names_cannot_leave_the_folder(self):
        row = {"title": "../../evil", "files": [{
            "title": "../../evil\\x", "contentType": "text/plain",
            "data": base64.b64encode(b"x").decode()}]}
        paths, _ = hr.write_documents(os.path.join(self.tmp, "o"), [row],
                                      None)
        self.assertEqual(os.path.dirname(paths[0]),
                         os.path.join(self.tmp, "o"))

    def test_bad_data_is_not_a_file(self):
        row = {"files": [{"data": "!!!not base64"}, {"data": 5}, {}]}
        paths, notes = hr.write_documents(os.path.join(self.tmp, "o"), [row],
                                          None)
        self.assertEqual(paths, [])
        self.assertIn("3 attachments hold no data", notes)


class ReaderTests(unittest.TestCase):
    def test_the_tables_come_with_the_health_reader(self):
        tmp = tempfile.mkdtemp(prefix="ibe-records-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "healthdb_secure.sqlite")
        conn = sqlite3.connect(path)
        fh.build_health(conn)
        build(conn)
        conn.close()
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        keys = [d.key for d in hl.HealthReader(conn).datasets()]
        for key in ("lab_results", "immunizations", "conditions",
                    "prescriptions", "clinical_documents", "records"):
            self.assertIn(key, keys)

    def test_a_database_without_the_table(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(hr.datasets(conn), [])
        conn.execute("CREATE TABLE original_fhir_resources (ROWID INTEGER)")
        self.assertEqual(hr.datasets(conn), [])


if __name__ == "__main__":
    unittest.main()
