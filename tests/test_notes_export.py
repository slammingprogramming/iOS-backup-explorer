# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Exporting notes: text, Markdown, web page, PDF, JSON and CSV."""

import csv
import gc
import io
import json
import logging
import os
import re
import shutil
import tempfile
import unittest
import warnings
from unittest import mock

from ios_apps import imaging
from ios_apps import notes as nt
from ios_apps import notes_export as nx
from ios_apps import pdf_export
from tests import fixture_media as fm
from tests import fixture_notes as fn
from tests.fixture_apps import PNG_BYTES
from tests.test_notes import index_for, make_connection

HAVE_PDF = pdf_export.available()


def slurp(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


def spit(path, data, mode="w"):
    with open(path, mode) as handle:
        handle.write(data)


class NotesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-notesx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        conn = make_connection(self)
        self.index = index_for(fn.backup_files())
        self.reader = nt.NotesReader(conn, nt.media_resolver(self.index))
        self.all = [self.reader.load(n) for n in self.reader.notes()]
        self.notes = {n.pk: n for n in self.all}
        self.folders = self.reader.folders_by_pk

    def fetch_into(self, folder):
        """A stand-in for the backup: writes the attachment bytes."""
        def fetch(wanted):
            target = os.path.join(folder, "attachments")
            os.makedirs(target, exist_ok=True)
            for attachment, name in wanted:
                with open(os.path.join(target, name), "wb") as handle:
                    handle.write(PNG_BYTES if attachment.kind == "image"
                                 else b"audio bytes")
            return [name for _a, name in wanted]
        return fetch

    def export(self, fmt, notes=None, name="out", fetch=True):
        folder = os.path.join(self.tmp, name)
        paths = nx.export(self.all if notes is None else notes, self.folders,
                          fmt, folder, self.fetch_into(folder) if fetch
                          else None)
        return folder, paths

    def relative(self, folder, paths):
        return sorted(os.path.relpath(p, folder).replace("\\", "/")
                      for p in paths)


class TextTests(NotesCase):
    def test_a_note_as_plain_text(self):
        self.assertEqual(nx.note_to_text(self.notes[10]), "\n".join([
            "Shopping list", "Things to get", "[ ] Milk", "[x] Eggs",
            "• Apples", "    • Green ones", "1. Wash up",
            "2. Cook dinner", "Party \U0001F389 time and site",
            "[Image: photo.png]",
            "#home Example site <https://example.com/>", ""]))

    def test_a_locked_note_gives_its_reason(self):
        self.assertIn("locked", nx.note_to_text(self.notes[12]))

    def test_attachment_text(self):
        self.assertEqual(nx.attachment_text(None), "[attachment]")
        link = nt.Attachment("x", kind="url", url="https://e.org/")
        self.assertEqual(nx.attachment_text(link), "https://e.org/")


class MarkdownTests(NotesCase):
    def test_a_note_as_markdown(self):
        files = {"ATT-PHOTO": "../attachments/00001_photo.png"}
        self.assertEqual(nx.note_to_markdown(self.notes[10], files), "\n".join([
            "# Shopping list", "", "## Things to get", "",
            "- [ ] Milk", "- [x] Eggs", "- Apples", "    - Green ones",
            "1. Wash up", "2. Cook dinner", "",
            "Party \U0001F389 **time** and [site](https://example.com/shop)",
            "", "![photo.png](../attachments/00001_photo.png)", "",
            "#home [Example site](https://example.com/)", ""]))

    def test_an_attachment_that_was_not_exported_is_marked(self):
        text = nx.note_to_markdown(self.notes[10])
        self.assertIn("*[Image: photo.png]*", text)

    def test_special_characters_are_escaped(self):
        note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
            nt.Span("a*b_c [d] <e> #f | `g` \\h")])])
        self.assertEqual(nx.note_to_markdown(note).strip(),
                         "a\\*b\\_c \\[d\\] \\<e\\> #f \\| \\`g\\` \\\\h")

    def test_a_paragraph_that_looks_like_a_heading_is_guarded(self):
        for text, expected in (("# not a heading", "\\# not a heading"),
                               ("###### six", "\\###### six"),
                               ("#hashtag", "#hashtag"),
                               ("####### seven", "####### seven")):
            with self.subTest(text=text):
                note = nt.Note(1, "t", paragraphs=[
                    nt.Paragraph(spans=[nt.Span(text)])])
                self.assertEqual(nx.note_to_markdown(note).strip(), expected)

    def test_emphasis_keeps_spaces_outside_the_markers(self):
        note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
            nt.Span("so "), nt.Span(" bold ", bold=True),
            nt.Span("and "), nt.Span("it", italic=True, strike=True)])])
        self.assertEqual(nx.note_to_markdown(note).strip(),
                         "so  **bold** and *~~it~~*")

    def test_a_paragraph_that_looks_like_a_list_item_is_guarded(self):
        for text, expected in (("1. not a list", "1\\. not a list"),
                               ("- not a list", "\\- not a list"),
                               ("2) nor this", "2\\) nor this"),
                               ("-5 degrees", "-5 degrees")):
            with self.subTest(text=text):
                note = nt.Note(1, "t", paragraphs=[
                    nt.Paragraph(spans=[nt.Span(text)])])
                self.assertEqual(nx.note_to_markdown(note).strip(), expected)

    def test_a_paragraph_after_a_list_is_separated_from_it(self):
        note = nt.Note(1, "t", paragraphs=[
            nt.Paragraph(100, spans=[nt.Span("item")]),
            nt.Paragraph(spans=[nt.Span("after")])])
        self.assertEqual(nx.note_to_markdown(note), "- item\n\nafter\n")

    def test_monospaced_paragraphs_become_one_code_block(self):
        note = nt.Note(1, "t", paragraphs=[
            nt.Paragraph(4, spans=[nt.Span("a = 1")]),
            nt.Paragraph(4, spans=[nt.Span("b = *2*")]),
            nt.Paragraph(spans=[nt.Span("done")])])
        self.assertEqual(nx.note_to_markdown(note),
                         "```\na = 1\nb = *2*\n```\ndone\n")

    def test_link_addresses_with_brackets_cannot_break_out(self):
        note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
            nt.Span("x", link="https://e.org/a b)c")])])
        self.assertEqual(nx.note_to_markdown(note).strip(),
                         "[x](https://e.org/a%20b%29c)")


class HtmlTests(NotesCase):
    def body(self, note, files=None):
        return nx.note_to_html_body(note, files)

    def test_structure_of_a_note(self):
        html = self.body(self.notes[10], {
            "ATT-PHOTO": "../attachments/00001_photo.png"})
        for expected in (
                "<h1>Shopping list</h1>", "<h2>Things to get</h2>",
                "<ul class=\"check\"><li><input type=\"checkbox\" disabled> "
                "Milk</li>",
                "<li><input type=\"checkbox\" disabled checked> Eggs</li></ul>",
                "<ul><li>Apples</li><ul><li>Green ones</li></ul></ul>",
                "<ol><li>Wash up</li><li>Cook dinner</li></ol>",
                "<strong>time</strong>",
                "<u>site</u>",
                "href=\"https://example.com/shop\"",
                "<img loading=\"lazy\" src=\"../attachments/00001_photo.png\"",
                "<span class=\"chip\">#home</span>",
                "<a href=\"https://example.com/\" rel=\"noopener "
                "noreferrer\">Example site</a>"):
            with self.subTest(expected=expected):
                self.assertIn(expected, html)

    def test_lists_of_different_kinds_do_not_run_together(self):
        note = nt.Note(1, "t", paragraphs=[
            nt.Paragraph(100, spans=[nt.Span("a")]),
            nt.Paragraph(102, number=1, spans=[nt.Span("b")]),
            nt.Paragraph(103, spans=[nt.Span("c")]),
            nt.Paragraph(103, spans=[nt.Span("d")])])
        html = self.body(note)
        self.assertEqual(html.count("<ul"), 2)
        self.assertEqual(html.count("<ol"), 1)
        self.assertEqual(html.count("</ul>"), 2)
        self.assertEqual(html.count("</ol>"), 1)
        self.assertEqual(html.count("<li>"), 4)

    def test_everything_is_escaped(self):
        note = nt.Note(1, "<script>alert(1)</script>", paragraphs=[
            nt.Paragraph(spans=[nt.Span("<img src=x onerror=alert(1)> & \"q\"")]),
            nt.Paragraph(4, spans=[nt.Span("<b>code</b>")])],
            attachments={"A": nt.Attachment(
                "A", "public.png", "image", 'x"><script>.png',
                path="D/p.png")})
        note.paragraphs.append(nt.Paragraph(spans=[nt.Span(
            "\ufffc", attachment="A")]))
        page = nx.note_to_html(note, {}, {"A": 'a"b<c>.png'})
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<b>code", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn('a"b<c>', page)

    def test_only_ordinary_links_are_clickable(self):
        for link, clickable in (("https://e.org", True), ("http://e.org", True),
                                ("mailto:a@e.org", True), ("tel:+1555", True),
                                ("javascript:alert(1)", False),
                                ("data:text/html,x", False),
                                ("file:///etc/passwd", False),
                                ("  JAVASCRIPT:x", False)):
            with self.subTest(link=link):
                note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
                    nt.Span("go", link=link)])])
                self.assertEqual("<a href" in self.body(note), clickable)
        attachment = nt.Attachment("U", "public.url", "url",
                                   url="javascript:alert(1)", title="Hi")
        note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
            nt.Span("\ufffc", attachment="U")])], attachments={"U": attachment})
        self.assertNotIn("<a href", self.body(note))
        self.assertIn("Hi", self.body(note))

    def test_audio_video_and_unknown_files(self):
        kinds = {"audio": "<audio controls", "video": "<video controls",
                 "file": "<a href=\"../attachments/f.bin\">"}
        for kind, expected in kinds.items():
            with self.subTest(kind=kind):
                attachment = nt.Attachment("A", "", kind, "f.bin", "D/f.bin")
                note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
                    nt.Span("\ufffc", attachment="A")])],
                    attachments={"A": attachment})
                self.assertIn(expected, self.body(
                    note, {"A": "../attachments/f.bin"}))

    def test_a_heic_picture_is_a_link_not_a_broken_image(self):
        attachment = nt.Attachment("A", "public.heic", "image", "p.heic",
                                   "D/p.heic")
        note = nt.Note(1, "t", paragraphs=[nt.Paragraph(spans=[
            nt.Span("\ufffc", attachment="A")])], attachments={"A": attachment})
        html = self.body(note, {"A": "attachments/p.heic"})
        self.assertNotIn("<img", html)
        self.assertIn("href=\"attachments/p.heic\"", html)

    def test_the_page_has_no_scripts_and_loads_nothing_remote(self):
        page = nx.note_to_html(self.notes[10], self.folders,
                               {"ATT-PHOTO": "attachments/p.png"})
        self.assertNotIn("<script", page)
        self.assertNotRegex(page, r"(src|href)=\"https?://[^\"]*\"(?<!>)"
                            r"(?=[^>]*\bsrc)" if False else r"src=\"https?:")
        self.assertNotIn("@import", page)


class ExportTests(NotesCase):
    def test_text_goes_into_folders_named_like_the_notes_folders(self):
        folder, paths = self.export("txt")
        self.assertEqual(self.relative(folder, paths), [
            "Notes/Broken.txt", "Notes/Empty.txt",
            "Notes/No stored title here.txt", "Notes/Secret.txt",
            "Notes/Shopping list.txt", "Recently Deleted/Old idea.txt",
            "Recipes/Pancakes.txt", "Recipes/Soups/Tomato soup.txt"])
        with open(os.path.join(folder, "Notes", "Shopping list.txt"),
                  encoding="utf-8") as handle:
            self.assertEqual(handle.read(), nx.note_to_text(self.notes[10]))
        self.assertFalse(os.path.exists(os.path.join(folder, "attachments")))

    def test_same_titles_get_different_names_even_ignoring_case(self):
        copies = []
        for title in ("Same", "same", "SAME", "Same"):
            note = nt.Note(100 + len(copies), title, folder=2, loaded=True,
                           paragraphs=[nt.Paragraph(spans=[nt.Span("x")])])
            copies.append(note)
        folder, paths = self.export("txt", copies)
        names = self.relative(folder, paths)
        self.assertEqual(len({n.lower() for n in names}), 4)
        self.assertEqual(sorted(names), sorted([
            "Notes/Same.txt", "Notes/same (2).txt", "Notes/SAME (3).txt",
            "Notes/Same (4).txt"]))

    def test_awkward_titles_make_valid_file_names(self):
        notes = [nt.Note(200 + i, title, folder=2, loaded=True)
                 for i, title in enumerate(["CON", "a/b:c?", "", "x" * 300])]
        folder, paths = self.export("txt", notes)
        for path in paths:
            self.assertTrue(os.path.isfile(path))
            name = os.path.basename(path)
            self.assertNotRegex(name, r'[<>:"/\\|?*]')
            self.assertLessEqual(len(name), 90)
        self.assertIn("_CON.txt", [os.path.basename(p) for p in paths])

    def test_notes_with_no_known_folder_go_into_notes(self):
        folder, paths = self.export("txt", [nt.Note(1, "Loose", folder=999,
                                                    loaded=True)])
        self.assertEqual(self.relative(folder, paths), ["Notes/Loose.txt"])

    def test_markdown_with_pictures_linked_from_inside_folders(self):
        folder, paths = self.export("md")
        text = slurp(os.path.join(folder, "Notes", "Shopping list.md"),
                     encoding="utf-8")
        link = re.search(r"!\[photo.png\]\(([^)]+)\)", text).group(1)
        self.assertEqual(link, "../attachments/00001_photo.png")
        self.assertTrue(os.path.isfile(os.path.join(folder, "Notes", link)))

    def test_markdown_links_work_from_nested_folders(self):
        nested = self.notes[17]
        photo = self.notes[10].attachments["ATT-PHOTO"]
        nested.paragraphs.append(nt.Paragraph(spans=[nt.Span(
            "\ufffc", attachment="ATT-PHOTO")]))
        nested.attachments = {"ATT-PHOTO": photo}
        folder, _ = self.export("md", [nested])
        text = slurp(os.path.join(folder, "Recipes", "Soups",
                                 "Tomato soup.md"), encoding="utf-8")
        link = re.search(r"\(([^)]*photo.png)\)", text).group(1)
        self.assertEqual(link, "../../attachments/00001_photo.png")
        self.assertTrue(os.path.isfile(
            os.path.join(folder, "Recipes", "Soups", link)))

    def test_html_has_an_index_and_working_links(self):
        folder, paths = self.export("html")
        index = os.path.join(folder, "index.html")
        self.assertEqual(paths[0], index)
        page = slurp(index, encoding="utf-8")
        self.assertIn("8 notes", page)
        self.assertIn("<h2>Recipes / Soups</h2>", page)
        for link in re.findall(r"href=\"([^\"]+\.html)\"", page):
            self.assertTrue(os.path.isfile(os.path.join(
                folder, *link.replace("%20", " ").split("/"))), link)
        note_page = os.path.join(folder, "Recipes", "Soups", "Tomato soup.html")
        text = slurp(note_page, encoding="utf-8")
        self.assertIn("href=\"../../index.html\"", text)
        shopping = slurp(os.path.join(folder, "Notes", "Shopping list.html"),
                        encoding="utf-8")
        src = re.search(r"<img [^>]*src=\"([^\"]+)\"", shopping).group(1)
        self.assertTrue(os.path.isfile(os.path.join(folder, "Notes", src)))

    def test_the_same_attachment_is_copied_once(self):
        note = nt.Note(1, "again", folder=2, loaded=True, attachments={
            "X1": self.notes[10].attachments["ATT-PHOTO"]})
        folder, _ = self.export("html", [self.notes[10], note])
        self.assertEqual(os.listdir(os.path.join(folder, "attachments")),
                         ["00001_photo.png"])

    def test_json(self):
        folder, paths = self.export("json")
        self.assertEqual(self.relative(folder, paths), ["notes.json"])
        data = json.loads(slurp(paths[0], encoding="utf-8"))
        self.assertEqual(len(data), 8)
        shopping = next(n for n in data if n["title"] == "Shopping list")
        self.assertEqual(shopping["folder"], "Notes")
        self.assertTrue(shopping["pinned"])
        self.assertEqual(shopping["paragraphs"][0],
                         {"style": "title", "indent": 0,
                          "spans": [{"text": "Shopping list"}]})
        checkbox = shopping["paragraphs"][3]
        self.assertEqual((checkbox["style"], checkbox["checked"]),
                         ("checkbox", True))
        self.assertEqual(shopping["paragraphs"][6]["number"], 1)
        bold = [s for p in shopping["paragraphs"] for s in p["spans"]
                if s.get("bold")]
        self.assertEqual([s["text"] for s in bold], ["time"])
        by_kind = {a["kind"]: a for a in shopping["attachments"]}
        self.assertEqual(by_kind["image"]["file"],
                         "attachments/00001_photo.png")
        self.assertEqual(by_kind["inline"]["text"], "#home")
        self.assertEqual(by_kind["url"]["url"], "https://example.com/")
        secret = next(n for n in data if n["title"] == "Secret")
        self.assertTrue(secret["locked"])
        self.assertIn("locked", secret["error"])
        self.assertIn("\U0001F389", shopping["text"])      # real UTF-8

    def test_csv(self):
        folder, paths = self.export("csv")
        raw = slurp(paths[0], "rb")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))      # for Excel
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),
                                           newline="")))
        self.assertEqual(rows[0], list(nx.CSV_COLUMNS))
        self.assertEqual(len(rows), 9)
        shopping = next(r for r in rows if r[0] == "Shopping list")
        self.assertEqual(shopping[1], "Notes")
        self.assertEqual(shopping[4], "yes")
        self.assertIn("\n[ ] Milk\n", shopping[-1])
        trash = next(r for r in rows if r[0] == "Old idea")
        self.assertEqual(trash[6], "yes")

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            nx.export(self.all, self.folders, "doc", self.tmp)

    def test_formats_flag_a_missing_pdf_library(self):
        with mock.patch.object(pdf_export, "available", return_value=False):
            self.assertIn("pip install fpdf2", nx.formats()["pdf"])
        with mock.patch.object(pdf_export, "available", return_value=True):
            self.assertNotIn("pip", nx.formats()["pdf"])
        self.assertEqual(list(nx.formats()), list(nx.FORMATS))

    def test_an_attachment_that_failed_to_arrive_is_not_linked(self):
        folder = os.path.join(self.tmp, "partial")
        nx.export([self.notes[10]], self.folders, "html", folder,
                  lambda wanted: [])
        page = slurp(os.path.join(folder, "Notes", "Shopping list.html"),
                    encoding="utf-8")
        self.assertNotIn("<img", page)
        self.assertIn("not exported", page)


class CallRecordingExportTests(NotesCase):
    def setUp(self):
        super().setUp()
        conn = make_connection(self, fn.build_with_call_recordings)
        index = index_for(fn.backup_files(call_recordings=True))
        reader = nt.NotesReader(conn, nt.media_resolver(index))
        self.note = next(reader.load(n) for n in reader.notes() if n.pk == 19)
        self.folders = reader.folders_by_pk

    def test_text_has_the_words_under_the_recording(self):
        text = nx.note_to_text(self.note)
        self.assertIn("[Recording: Call with Example Co (2:05)]\n"
                      "    Hello, this is a test call.\n"
                      "    Thank you, goodbye.\n", text)

    def test_markdown_quotes_the_words(self):
        text = nx.note_to_markdown(self.note, {
            "ATT-30": "../attachments/00001_call.m4a"})
        self.assertIn("[Recording: Call with Example Co (2:05)]"
                      "(../attachments/00001_call.m4a)\n\n"
                      "> Hello, this is a test call.\n"
                      "> Thank you, goodbye.", text)

    def test_the_web_page_has_a_player_and_the_words(self):
        page = nx.note_to_html_body(self.note, {
            "ATT-30": "../attachments/00001_call.m4a"})
        self.assertIn("<audio controls", page)
        self.assertIn("<details class=\"transcript\"><summary>Words of the "
                      "recording</summary><p>Hello, this is a test call.<br>"
                      "Thank you, goodbye.</p></details>", page)

    def test_the_words_are_escaped(self):
        attachment = self.note.attachments["ATT-30"]
        attachment.text = "<script>alert(1)</script> & more"
        page = nx.note_to_html_body(self.note)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; more", page)

    def test_json_has_the_words_the_length_and_the_file(self):
        folder = os.path.join(self.tmp, "call-json")

        def fetch(wanted):
            target = os.path.join(folder, "attachments")
            os.makedirs(target, exist_ok=True)
            for _a, name in wanted:
                spit(os.path.join(target, name), b"audio", "wb")
            return [name for _a, name in wanted]

        (path,) = nx.export([self.note], self.folders, "json", folder, fetch)
        (data,) = json.loads(slurp(path, encoding="utf-8"))
        call = next(a for a in data["attachments"] if a["id"] == "ATT-30")
        self.assertEqual(call["transcript"], fn.CALL_WORDS)
        self.assertEqual(call["duration_seconds"], 125.0)
        self.assertEqual(call["title"], "Call with Example Co")
        self.assertEqual(call["file"], "attachments/00001_call.m4a")

    def test_a_recording_with_no_words_adds_nothing(self):
        for attachment in self.note.attachments.values():
            attachment.text = ""
        self.assertNotIn("Hello", nx.note_to_text(self.note))
        self.assertNotIn("transcript", nx.note_to_html_body(self.note))

    @unittest.skipUnless(HAVE_PDF, "fpdf2 is not installed")
    def test_the_pdf_works_with_a_recording(self):
        path = os.path.join(self.tmp, "call.pdf")
        pdf_export.write_note_pdf(path, self.note)
        self.assertEqual(slurp(path, "rb")[:5], b"%PDF-")


class HeicTests(NotesCase):
    @unittest.skipUnless(imaging.have_heif(), "pillow-heif is not installed")
    def test_heic_pictures_are_converted_so_browsers_can_show_them(self):
        heic = fm.picture_bytes("HEIF", (40, 30))
        attachment = nt.Attachment("H", "public.heic", "image", "photo.HEIC",
                                   "D/photo.HEIC")
        note = nt.Note(1, "Heic", folder=2, loaded=True, paragraphs=[
            nt.Paragraph(spans=[nt.Span("\ufffc", attachment="H")])],
            attachments={"H": attachment})
        folder = os.path.join(self.tmp, "heic")

        def fetch(wanted):
            target = os.path.join(folder, "attachments")
            os.makedirs(target, exist_ok=True)
            for _attachment, name in wanted:
                spit(os.path.join(target, name), heic, "wb")
            return [name for _a, name in wanted]

        nx.export([note], self.folders, "html", folder, fetch)
        names = os.listdir(os.path.join(folder, "attachments"))
        self.assertIn("00001_photo.jpg", names)
        page = slurp(os.path.join(folder, "Notes", "Heic.html"),
                     encoding="utf-8")
        self.assertIn("<img loading=\"lazy\" src=\"../attachments/"
                      "00001_photo.jpg\"", page)

    def test_without_the_converter_the_original_is_linked(self):
        attachment = nt.Attachment("H", "public.heic", "image", "photo.HEIC",
                                   "D/photo.HEIC")
        note = nt.Note(1, "Heic", folder=2, loaded=True, paragraphs=[
            nt.Paragraph(spans=[nt.Span("\ufffc", attachment="H")])],
            attachments={"H": attachment})
        folder = os.path.join(self.tmp, "heic2")

        def fetch(wanted):
            target = os.path.join(folder, "attachments")
            os.makedirs(target, exist_ok=True)
            for _attachment, name in wanted:
                spit(os.path.join(target, name), b"heic bytes", "wb")
            return [name for _a, name in wanted]

        with mock.patch.object(nx.imaging, "have_heif", return_value=False):
            nx.export([note], self.folders, "html", folder, fetch)
        page = slurp(os.path.join(folder, "Notes", "Heic.html"),
                     encoding="utf-8")
        self.assertNotIn("<img", page)
        self.assertIn("href=\"../attachments/00001_photo.HEIC\"", page)


@unittest.skipUnless(HAVE_PDF, "fpdf2 is not installed")
class PdfTests(NotesCase):
    def setUp(self):
        super().setUp()
        quiet = logging.getLogger("fpdf")      # it warns about missing glyphs
        level = quiet.level
        quiet.setLevel(logging.ERROR)
        self.addCleanup(quiet.setLevel, level)

    @staticmethod
    def writer(**patches):
        """A PDF writer. (fpdf2 leaves the font files it reads open until
        the writer is collected; that is its business, not this test's.)"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            with mock.patch.multiple(pdf_export, create=False,
                                     find_font=patches.get(
                                         "find_font", pdf_export.find_font)):
                writer = pdf_export._Writer()
            gc.collect()
        return writer

    def test_emoji_and_object_characters_are_left_out(self):
        writer = self.writer()
        self.assertEqual(writer.clean("a\U0001F389b\ufffcc\u200d"), "abc")
        self.assertEqual(writer.clean("tab\there"), "tab    here")

    def test_without_a_unicode_font_other_letters_become_question_marks(self):
        writer = self.writer(find_font=lambda: None)
        self.assertEqual(writer.clean("caf\u00e9 \u65e5"), "caf\u00e9 ?")

    def test_every_note_becomes_a_pdf(self):
        folder, paths = self.export("pdf")
        self.assertEqual(len(paths), 8)
        for path in paths:
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(5), b"%PDF-", path)
        # pictures are drawn into the PDF; the copies made for that go away
        self.assertFalse(os.path.exists(os.path.join(folder, "attachments")))

    def test_an_existing_attachments_folder_is_left_alone(self):
        keep = os.path.join(self.tmp, "out", "attachments")
        os.makedirs(keep)
        spit(os.path.join(keep, "mine.txt"), "keep me")
        self.export("pdf", [self.notes[10]])
        self.assertTrue(os.path.isfile(os.path.join(keep, "mine.txt")))

    def test_a_picture_is_drawn_into_the_pdf(self):
        with_picture = os.path.join(self.tmp, "a.pdf")
        without = os.path.join(self.tmp, "b.pdf")
        picture = os.path.join(self.tmp, "p.png")
        spit(picture, PNG_BYTES, "wb")
        attachment = nt.Attachment("A", "public.png", "image", "p.png")
        note = nt.Note(1, "p", folder=2, loaded=True, paragraphs=[
            nt.Paragraph(spans=[nt.Span("\ufffc", attachment="A")])],
            attachments={"A": attachment})
        pdf_export.write_note_pdf(with_picture, note, {"A": picture})
        pdf_export.write_note_pdf(without, note, {})
        self.assertIn(b"/Subtype /Image", slurp(with_picture, "rb"))
        self.assertNotIn(b"/Subtype /Image", slurp(without, "rb"))

    def test_a_picture_that_cannot_be_read_does_not_stop_the_pdf(self):
        broken = os.path.join(self.tmp, "broken.png")
        spit(broken, b"\x89PNG not really", "wb")
        attachment = nt.Attachment("A", "public.png", "image", "broken.png")
        note = nt.Note(1, "p", loaded=True, paragraphs=[
            nt.Paragraph(spans=[nt.Span("\ufffc", attachment="A")])],
            attachments={"A": attachment})
        path = os.path.join(self.tmp, "c.pdf")
        pdf_export.write_note_pdf(path, note, {"A": broken})
        self.assertEqual(slurp(path, "rb")[:5], b"%PDF-")

    def test_any_text_works_with_or_without_a_unicode_font(self):
        note = nt.Note(1, "Привет \u4f60\u597d \U0001F389", loaded=True, paragraphs=[
            nt.Paragraph(0, spans=[nt.Span("Привет \u4f60\u597d \U0001F389 café")]),
            nt.Paragraph(103, checked=True, spans=[nt.Span("done")]),
            nt.Paragraph(102, number=3, indent=2, spans=[
                nt.Span("link", link="https://e.org", bold=True)]),
            nt.Paragraph(4, spans=[nt.Span("mono")])])
        for fonts in (pdf_export.find_font(), None):
            with self.subTest(font=bool(fonts)):
                with mock.patch.object(pdf_export, "find_font",
                                       return_value=fonts):
                    path = os.path.join(self.tmp, f"u{bool(fonts)}.pdf")
                    pdf_export.write_note_pdf(path, note)
                    self.assertEqual(slurp(path, "rb")[:5], b"%PDF-")

    def test_without_the_library_the_error_says_what_to_install(self):
        with mock.patch.object(pdf_export, "FPDF", None):
            with self.assertRaises(RuntimeError) as caught:
                pdf_export.write_note_pdf(os.path.join(self.tmp, "x.pdf"),
                                          self.notes[10])
        self.assertIn("pip install fpdf2", str(caught.exception))

    def test_a_long_note_spans_several_pages(self):
        note = nt.Note(1, "long", loaded=True, paragraphs=[
            nt.Paragraph(spans=[nt.Span(f"line {i} " * 8)])
            for i in range(200)])
        path = os.path.join(self.tmp, "long.pdf")
        pdf_export.write_note_pdf(path, note)
        pages = len(re.findall(rb"/Type\s*/Page\b", slurp(path, "rb")))
        self.assertGreater(pages, 3)


if __name__ == "__main__":
    unittest.main()
