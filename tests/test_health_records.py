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

from ios_apps import aea
from ios_apps import health as hl
from ios_apps import health_records as hr
from unittest import mock

from ios_apps import records_view as rv
from tests import aea_builder as ab
from tests import fixture_health as fh
from tests.fixture_apps import database_bytes
from tests.gui_apps import AppGuiCase
from tests.keyed_builder import archive

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


HTML = b"<div>An invented note.</div>"
OTHER_KEY = bytes(range(100, 132))


def key_blob(key):
    return archive({"$class": "HKSymmetricKey", "sym_key": key})


class DownloadedFileTests(unittest.TestCase):
    """The files the phone downloaded for clinical documents, kept
    encrypted in the backup, with their keys in the database."""

    def ident(self, number):
        return bytes([number]) * 16

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-records-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        build(self.conn)
        documents = [number for number, (kind, _raw) in
                     enumerate(RESOURCES, 1) if kind == "DocumentReference"]
        self.report = next(number for number, (kind, _raw) in
                           enumerate(RESOURCES, 1)
                           if kind == "DiagnosticReport")
        self.first, self.second = documents[:2]
        self.conn.executescript("""
            CREATE TABLE objects (data_id INTEGER PRIMARY KEY, uuid BLOB);
            CREATE TABLE clinical_record_samples (data_id INTEGER PRIMARY KEY,
                original_fhir_resource_rowid INTEGER);
            CREATE TABLE attachments (identifier BLOB, type TEXT,
                encryption_key BLOB);
            CREATE TABLE medical_downloadable_attachments (
                data_id INTEGER PRIMARY KEY, clinical_record_uuid BLOB,
                attachment_uuid BLOB, title TEXT);""")
        for number in (self.first, self.second, self.report):
            self.conn.execute("INSERT INTO objects VALUES (?, ?)",
                              (number, self.ident(number)))
            self.conn.execute(
                "INSERT INTO clinical_record_samples VALUES (?, ?)",
                (number, number))
        # file 1 and 2: the first document; 3: the second, under another
        # key than the one recorded; 4: the report, whose file is not in the
        # backup; 5: a file that is not encrypted at all
        self.stored = {}
        self.files = [
            (1, self.first, "com.adobe.pdf", ab.KEY, PDF, "Summary"),
            (2, self.first, "public.html", ab.KEY, HTML, "Note"),
            (3, self.second, "public.rtf", OTHER_KEY, b"{\\rtf1 x}", "Letter"),
            (4, self.report, "com.adobe.pdf", ab.KEY, None, "Scan"),
            (5, self.second, "weird.type", None, b"%PDF-1.7 plain", "Plain")]
        for number, record, uti, key, content, title in self.files:
            ident = self.ident(40 + number)
            self.conn.execute("INSERT INTO attachments VALUES (?, ?, ?)",
                              (ident, uti, key_blob(key) if key else None))
            self.conn.execute(
                "INSERT INTO medical_downloadable_attachments VALUES "
                "(?, ?, ?, ?)", (number, self.ident(record), ident, title))
            name = f"{hr.FILES}/" + str(
                __import__("uuid").UUID(bytes=ident)).upper()
            if content is not None:
                self.stored[name] = (
                    ab.build(content) if key == ab.KEY
                    else ab.build(content, key=ab.KEY) if key else content)
        self.conn.commit()
        self.table = {d.key: d for d in hr.datasets(self.conn)}[
            "clinical_documents"]
        self.rows = {r["type"] or r["title"]: r for r in self.table.rows}

    def downloads_only(self, *names):
        """The rows called *names* without the files inside the record."""
        return [dict(self.rows[name], files=[]) for name in names]

    def copy_file(self, path, directory, name):
        if path not in self.stored:
            return False
        with open(os.path.join(directory, name), "wb") as handle:
            handle.write(self.stored[path])
        return True

    def test_files_are_found_for_their_records(self):
        by = {r["type"] or r["title"]: len(r["attached"])
              for r in self.table.rows}
        self.assertEqual(by["Discharge summary"], 2)
        self.assertEqual(by["Progress note"], 2)      # (3 and 5)
        self.assertEqual(by["Chest X-ray"], 1)
        shown = {r["type"]: self.table.columns[-1].show(r.get("saved"), r)
                 for r in self.table.rows}
        self.assertEqual(shown["Discharge summary"], "2")

    def test_the_details_name_the_kinds_of_file(self):
        text = self.table.details(self.rows["Discharge summary"])
        self.assertIn("Files in the backup: pdf, html", text)

    def test_the_keys_are_read_from_the_database(self):
        keys = [i["key"] for r in self.table.rows for i in r["attached"]]
        self.assertEqual(keys.count(ab.KEY), 3)
        self.assertEqual(keys.count(None), 1)           # (the unencrypted one)

    def test_opened_files_are_saved(self):
        out = os.path.join(self.tmp, "out")
        paths, notes = hr.write_documents(
            out, self.downloads_only("Discharge summary"), self.copy_file)
        self.assertEqual(notes, "")
        names = sorted(os.path.basename(p) for p in paths)
        self.assertEqual(len(names), 2)
        contents = {}
        for path in paths:
            with open(path, "rb") as handle:
                contents[os.path.splitext(path)[1]] = handle.read()
        self.assertEqual(contents, {".pdf": PDF, ".html": HTML})
        self.assertEqual(os.listdir(out).__len__(), 2)

    def test_what_cannot_be_opened_or_is_not_there_is_counted(self):
        out = os.path.join(self.tmp, "out")
        paths, notes = hr.write_documents(
            out, self.downloads_only("Progress note", "Chest X-ray"),
            self.copy_file)
        # the unencrypted file is kept as it is; the one under a key that
        # does not fit is reported; the report's file is not in the backup
        self.assertEqual(len(paths), 1)
        with open(paths[0], "rb") as handle:
            self.assertEqual(handle.read(), b"%PDF-1.7 plain")
        self.assertTrue(paths[0].endswith(".pdf"))        # (by its content)
        self.assertIn("1 downloaded file could not be opened", notes)
        self.assertIn("1 attachment hold no data", notes)

    def test_an_encrypted_file_without_its_key_is_not_written(self):
        item = {"path": f"{hr.FILES}/X", "key": None, "type": ""}
        self.stored[item["path"]] = ab.build(b"secret")
        scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(scratch)
        self.assertEqual(hr._open_attached(item, self.copy_file, scratch),
                         (None, "locked"))
        self.assertEqual(hr._open_attached(
            {"path": "HealthDomain/none", "key": ab.KEY}, self.copy_file,
            scratch), (None, "absent"))
        self.assertEqual(os.listdir(scratch), [])

    def test_a_record_with_both_kinds_of_attachment_counts_each_once(self):
        """The 'Progress note' names its file only by a web address; the
        phone downloaded it, so it is not a missing file."""
        paths, notes = hr.write_documents(
            os.path.join(self.tmp, "out"), [self.rows["Progress note"]],
            self.copy_file)
        self.assertNotIn("hold no data", notes)
        self.assertIn("1 downloaded file could not be opened", notes)

    def test_without_a_way_to_copy_files(self):
        paths, notes = hr.write_documents(
            os.path.join(self.tmp, "out"),
            self.downloads_only("Discharge summary"), None)
        self.assertEqual(paths, [])
        self.assertIn("2 attachments hold no data", notes)

    def test_two_files_with_one_name_do_not_overwrite_each_other(self):
        row = dict(self.rows["Discharge summary"], files=[])
        row["attached"] = [row["attached"][0], row["attached"][0]]
        paths, _ = hr.write_documents(os.path.join(self.tmp, "out"), [row],
                                      self.copy_file)
        self.assertEqual(len({p.lower() for p in paths}), 2)

    def test_the_scratch_folder_is_removed(self):
        before = set(os.listdir(tempfile.gettempdir()))
        hr.write_documents(os.path.join(self.tmp, "out"),
                           [self.rows["Discharge summary"]], self.copy_file)
        left = [n for n in set(os.listdir(tempfile.gettempdir())) - before
                if n.startswith("ibe-health-files-")]
        self.assertEqual(left, [])

    def test_databases_without_the_tables_still_read(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        build(conn)
        table = {d.key: d for d in hr.datasets(conn)}["clinical_documents"]
        self.assertTrue(all(r["attached"] == [] for r in table.rows))
        self.assertEqual(hr.downloaded_files(conn), {})
        self.assertEqual(hr._record_ids(conn), {})


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


FILE_ID = "ABCDEF01-2345-4678-9ABC-DEF012345678"


class DocumentWindowTests(AppGuiCase):
    """Saving the files of clinical documents from the Health tab of a
    backup, through the program's own way of copying files out of it."""

    def database(self, conn):
        fh.build_health(conn)
        build(conn)
        first = next(number for number, (kind, _raw) in
                     enumerate(RESOURCES, 1) if kind == "DocumentReference")
        ident = __import__("uuid").UUID(FILE_ID).bytes
        conn.executescript("""
            ALTER TABLE clinical_record_samples ADD COLUMN
                original_fhir_resource_rowid INTEGER;
            CREATE TABLE attachments (identifier BLOB, type TEXT,
                encryption_key BLOB);
            CREATE TABLE medical_downloadable_attachments (
                data_id INTEGER PRIMARY KEY, clinical_record_uuid BLOB,
                attachment_uuid BLOB, title TEXT);""")
        conn.execute("INSERT INTO objects (data_id, uuid) VALUES (7777, ?)",
                     (bytes([7]) * 16,))
        conn.execute("INSERT INTO clinical_record_samples (data_id, "
                     "original_fhir_resource_rowid) VALUES (7777, ?)",
                     (first,))
        conn.execute("INSERT INTO attachments VALUES (?, 'com.adobe.pdf', ?)",
                     (ident, key_blob(ab.KEY)))
        conn.execute("INSERT INTO medical_downloadable_attachments VALUES "
                     "(1, ?, ?, 'Scan')", (bytes([7]) * 16, ident))
        conn.commit()

    def test_the_files_are_saved_opened(self):
        files = fh.backup_files(health=False) + [
            ("HealthDomain", fh.HEALTH, database_bytes(self.database)),
            ("HealthDomain", f"Health/Files/{FILE_ID}", ab.build(PDF))]
        self.open_files(files)
        tab = self.show_tab("Health")
        self.wait_for(lambda: tab.datasets, "the health tables")
        tab.dataset_var.set("Clinical documents")
        tab.choose_dataset()
        shown = [tab.tree.item(i, "values") for i in tab.tree.get_children()]
        files_column = [c.key for c in tab.dataset.columns].index("saved")
        self.assertEqual(sorted(v[files_column] for v in shown),
                         ["", "", "1"])
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(rv, "ask_export",
                               return_value=("files", "all", out)):
            tab.export()
            self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        contents = {}
        for name in os.listdir(out):
            with open(os.path.join(out, name), "rb") as handle:
                contents[os.path.splitext(name)[1]] = handle.read()
        # the file in the backup (opened) and the one the record carries
        self.assertEqual(contents[".pdf"][:5], b"%PDF-")
        self.assertIn(PDF, list(contents.values()))


if __name__ == "__main__":
    unittest.main()
