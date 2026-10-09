# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reading the Notes database: text, formatting, folders, attachments."""

import os
import shutil
import sqlite3
import tempfile
import unittest

from file_index import FileIndex
from ios_apps import notes as nt
from ios_apps.common import APPLE_EPOCH
from tests import fixture_notes as fn
from tests.fixture_apps import database_bytes


def make_connection(testcase, builder=fn.build):
    folder = tempfile.mkdtemp(prefix="ibe-notes-")
    testcase.addCleanup(shutil.rmtree, folder, True)
    path = os.path.join(folder, "NoteStore.sqlite")
    with open(path, "wb") as handle:
        handle.write(database_bytes(builder))
    conn = sqlite3.connect(path)
    testcase.addCleanup(conn.close)
    return conn


def index_for(files):
    rows = [(f"{n:040x}", domain, path, 1, len(data), 0, 0)
            for n, (domain, path, data) in enumerate(files, 1)]
    return FileIndex(rows)


class DecodeTests(unittest.TestCase):
    def decode(self, runs, **kw):
        return nt.decode_note_data(fn.blob(runs, **kw))

    def test_paragraphs_styles_and_indentation(self):
        paragraphs = self.decode([
            fn.run("Title\n", style=0), fn.run("Big\n", style=1),
            fn.run("Small\n", style=2), fn.run("code\n", style=4),
            fn.run("plain\n"), fn.run("nested\n", style=100, indent=2)])
        self.assertEqual([(p.style, p.indent, p.text) for p in paragraphs], [
            (0, 0, "Title"), (1, 0, "Big"), (2, 0, "Small"),
            (4, 0, "code"), (-1, 0, "plain"), (100, 2, "nested")])

    def test_the_default_style_is_stored_as_minus_one(self):
        # protobuf stores -1 as a ten-byte number; it must come back as -1
        self.assertEqual(self.decode([fn.run("x\n")])[0].style, -1)

    def test_checklists(self):
        paragraphs = self.decode([fn.run("a\n", style=103, done=False),
                                  fn.run("b\n", style=103, done=True)])
        self.assertEqual([p.checked for p in paragraphs], [False, True])

    def test_numbered_lists_count_and_restart(self):
        paragraphs = self.decode([
            fn.run("one\n", style=102), fn.run("two\n", style=102),
            fn.run("inner\n", style=102, indent=1),
            fn.run("three\n", style=102),
            fn.run("break\n"),
            fn.run("again\n", style=102)])
        self.assertEqual([p.number for p in paragraphs], [1, 2, 1, 3, 0, 1])

    def test_a_deeper_list_starts_again_after_each_shallower_item(self):
        paragraphs = self.decode([
            fn.run("a\n", style=102), fn.run("x\n", style=102, indent=1),
            fn.run("y\n", style=102, indent=1),
            fn.run("b\n", style=102), fn.run("z\n", style=102, indent=1)])
        self.assertEqual([p.number for p in paragraphs], [1, 1, 2, 2, 1])

    def test_a_bullet_between_numbered_items_does_not_restart_them(self):
        paragraphs = self.decode([
            fn.run("one\n", style=102), fn.run("bullet\n", style=100, indent=1),
            fn.run("two\n", style=102)])
        self.assertEqual([p.number for p in paragraphs], [1, 0, 2])

    def test_run_lengths_count_utf16_units_not_characters(self):
        # the emoji is one character but two UTF-16 units; if the lengths
        # were counted in characters, "time" would be cut in the wrong place
        paragraphs = self.decode([fn.run("Party \U0001F389 "),
                                  fn.run("time", bold=True),
                                  fn.run("\n")])
        spans = paragraphs[0].spans
        self.assertEqual([(s.text, s.bold) for s in spans],
                         [("Party \U0001F389 ", False), ("time", True)])

    def test_font_traits_and_links(self):
        paragraphs = self.decode([
            fn.run("b", bold=True), fn.run("i", italic=True),
            fn.run("u", underline=True), fn.run("s", strike=True),
            fn.run("both", bold=True, italic=True),
            fn.run("link", link="https://example.com"), fn.run("\n")])
        spans = {s.text: s for s in paragraphs[0].spans}
        self.assertTrue(spans["b"].bold and not spans["b"].italic)
        self.assertTrue(spans["i"].italic and not spans["i"].bold)
        self.assertTrue(spans["u"].underline)
        self.assertTrue(spans["s"].strike)
        self.assertTrue(spans["both"].bold and spans["both"].italic)
        self.assertEqual(spans["link"].link, "https://example.com")

    def test_attachments_are_spans_of_their_own(self):
        paragraphs = self.decode([
            fn.run("see "), fn.run("\ufffc", attachment=("A1", "public.png")),
            fn.run(" here\n")])
        spans = paragraphs[0].spans
        self.assertEqual([s.attachment for s in spans], ["", "A1", ""])
        self.assertEqual(spans[1].attachment_uti, "public.png")
        self.assertEqual(paragraphs[0].text, "see \ufffc here")

    def test_blank_lines_are_kept(self):
        paragraphs = self.decode([fn.run("a\n\nb\n")])
        self.assertEqual([p.text for p in paragraphs], ["a", "", "b"])

    def test_text_after_the_last_line_break_is_kept(self):
        self.assertEqual(
            [p.text for p in self.decode([fn.run("a\nb")])], ["a", "b"])

    def test_text_the_runs_do_not_cover_is_still_shown(self):
        data = fn.blob([fn.run("short")])
        # a note whose text is longer than its runs
        text_note = (fn.pb_field(2, "short and then some")
                     + fn.pb_field(5, fn.run("short")[1]))
        raw = fn.pb_field(2, fn.pb_field(2, 0) + fn.pb_field(3, text_note))
        self.assertEqual(nt.decode_note_data(raw)[0].text,
                         "short and then some")
        self.assertTrue(data)

    def test_runs_longer_than_the_text_do_not_crash(self):
        text_note = (fn.pb_field(2, "abc")
                     + fn.pb_field(5, fn.pb_field(1, 99)))
        raw = fn.pb_field(2, fn.pb_field(2, 0) + fn.pb_field(3, text_note))
        self.assertEqual(nt.decode_note_data(raw)[0].text, "abc")

    def test_uncompressed_data_is_accepted(self):
        self.assertEqual(
            self.decode([fn.run("plain\n")], gzip_it=False)[0].text, "plain")

    def test_unreadable_data_raises_value_error(self):
        for blob in (None, b"", b"\x1f\x8bnot gzip", b"\x01\x02\x03 junk",
                     b"\x0a\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01",
                     b"\x0a\x05ab", b"\x1b\x00"):
            with self.subTest(blob=blob):
                with self.assertRaises(ValueError):
                    nt.decode_note_data(blob)

    def test_protobuf_reader_rejects_what_it_cannot_read(self):
        with self.assertRaises(ValueError):
            nt.parse_fields(b"\x0b")            # a group: wire type 3
        with self.assertRaises(ValueError):
            nt.parse_fields(b"\x80")            # a number that never ends
        self.assertEqual(nt.parse_fields(b"\x08\x96\x01\x12\x02hi"),
                         [(1, 150), (2, b"hi")])


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_connection(self)
        self.index = index_for(fn.backup_files())
        self.reader = nt.NotesReader(self.conn, nt.media_resolver(self.index))
        self.notes = {n.pk: n for n in self.reader.notes()}

    def load(self, pk):
        return self.reader.load(self.notes[pk])

    def test_deleted_notes_are_left_out_and_the_rest_newest_first(self):
        self.assertNotIn(16, self.notes)
        self.assertEqual([n.pk for n in self.reader.notes()],
                         [14, 10, 11, 12, 13, 15, 17, 18])

    def test_folders_counts_accounts_and_the_trash(self):
        folders = {f.title: f for f in self.reader.folders()}
        self.assertEqual(set(folders), {"Notes", "Recipes",
                                        "Recently Deleted", "Soups"})
        self.assertEqual(folders["Notes"].count, 5)
        self.assertEqual(folders["Recipes"].count, 1)
        self.assertEqual(folders["Soups"].parent, folders["Recipes"].pk)
        self.assertEqual(folders["Notes"].account, "iCloud")
        self.assertTrue(folders["Recently Deleted"].is_trash)
        self.assertFalse(folders["Notes"].is_trash)
        self.assertTrue(self.notes[13].deleted)      # in the trash folder
        self.assertFalse(self.notes[10].deleted)

    def test_dates_and_flags(self):
        note = self.notes[10]
        self.assertEqual(note.created, 770_000_000 + APPLE_EPOCH)
        self.assertEqual(note.modified, 778_100_000 + APPLE_EPOCH)
        self.assertTrue(note.pinned)
        self.assertFalse(self.notes[11].pinned)

    def test_a_note_without_a_stored_title_is_named_after_its_text(self):
        self.assertEqual(self.load(14).title, "No stored title here")

    def test_a_note_with_no_text_at_all_is_called_untitled(self):
        conn = make_connection(self)
        conn.execute("UPDATE ZICCLOUDSYNCINGOBJECT SET ZTITLE1 = NULL "
                     "WHERE Z_PK = 18")
        reader = nt.NotesReader(conn)
        note = next(n for n in reader.notes() if n.pk == 18)
        self.assertEqual(reader.load(note).title, "Untitled note")

    def test_a_locked_note_says_so_and_has_no_text(self):
        note = self.load(12)
        self.assertTrue(note.locked)
        self.assertEqual(note.paragraphs, [])
        self.assertIn("locked", note.error)
        self.assertEqual(note.title, "Secret")

    def test_a_damaged_note_falls_back_to_its_preview_text(self):
        note = self.load(15)
        self.assertIn("could not be read", note.error)
        self.assertEqual(note.text, "what is left of it")

    def test_loading_twice_does_nothing_new(self):
        note = self.load(10)
        first = note.paragraphs
        self.assertIs(self.reader.load(note).paragraphs, first)

    def test_attachments_of_a_note(self):
        attachments = self.load(10).attachments
        self.assertEqual(set(attachments), {"ATT-PHOTO", "ATT-TAG",
                                            "ATT-LINK"})
        photo = attachments["ATT-PHOTO"]
        self.assertEqual((photo.kind, photo.name), ("image", "photo.png"))
        self.assertEqual(photo.path, f"{fn.NOTES_DOMAIN}/{fn.NOTES_FILES['photo']}")
        self.assertEqual(attachments["ATT-TAG"].kind, "inline")
        self.assertEqual(attachments["ATT-TAG"].label, "#home")
        link = attachments["ATT-LINK"]
        self.assertEqual((link.kind, link.url, link.label),
                         ("url", "https://example.com/", "Example site"))
        voice = self.load(11).attachments["ATT-VOICE"]
        self.assertEqual((voice.kind, voice.name), ("audio", "Recording.m4a"))
        self.assertEqual(voice.label, "Recording: Recording.m4a")

    def test_the_newest_version_of_an_attachment_file_wins(self):
        photo = self.load(10).attachments["ATT-PHOTO"]
        self.assertIn("1_GEN-NEW", photo.path)

    def test_an_attachment_missing_from_the_backup_has_no_path(self):
        conn = make_connection(self)
        reader = nt.NotesReader(conn, nt.media_resolver(index_for([
            (fn.NOTES_DOMAIN, "NoteStore.sqlite", b"x")])))
        note = next(n for n in reader.notes() if n.pk == 10)
        photo = reader.load(note).attachments["ATT-PHOTO"]
        self.assertEqual(photo.path, "")
        self.assertEqual(photo.name, "photo.png")      # the name is kept

    def test_search_finds_titles_and_text_and_wants_every_word(self):
        found = lambda text: sorted(n.pk for n in self.reader.search(text))
        self.assertEqual(found("pancakes"), [11])          # title
        self.assertEqual(found("BATTER"), [11])            # text, any case
        self.assertEqual(found("pour batter"), [11])
        self.assertEqual(found("pour milk"), [])           # both must match
        self.assertEqual(found("tomatoes"), [17])
        self.assertEqual(found("   "), [])
        self.assertEqual(found("encrypted"), [])           # locked: no text

    def test_search_looks_at_the_stored_title_too(self):
        conn = make_connection(self)
        conn.execute("UPDATE ZICCLOUDSYNCINGOBJECT SET ZTITLE1 = 'Gazpacho' "
                     "WHERE Z_PK = 17")                 # the text says tomato
        reader = nt.NotesReader(conn)
        reader.notes()
        self.assertEqual([n.pk for n in reader.search("gazpacho")], [17])

    def test_search_does_not_match_the_internal_object_character(self):
        self.assertEqual(self.reader.search("\ufffc"), [])
        self.assertEqual(self.reader.search("ATT-PHOTO"), [])

    def test_a_file_used_twice_is_listed_once(self):
        conn = make_connection(self)
        conn.execute(
            "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZNOTE, "
            "ZIDENTIFIER, ZTYPEUTI, ZMEDIA) VALUES (30, 3, 10, 'ATT-AGAIN', "
            "'public.png', 20)")                   # the same picture again
        reader = nt.NotesReader(conn, nt.media_resolver(self.index))
        note = next(n for n in reader.notes() if n.pk == 10)
        reader.load(note)
        self.assertEqual(len(note.attachments), 4)
        self.assertEqual(len(reader.attachment_paths([note])), 1)

    def test_attachment_paths_are_listed_once(self):
        paths = self.reader.attachment_paths()
        self.assertEqual(len(paths), 2)
        self.assertEqual(len(set(paths)), 2)
        one = self.reader.attachment_paths([self.notes[11]])
        self.assertEqual(len(one), 1)
        self.assertTrue(one[0].endswith("Recording.m4a"))


class SchemaToleranceTests(unittest.TestCase):
    def test_a_database_without_the_optional_columns_still_reads(self):
        def build(conn):
            conn.executescript("""
                CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY,
                    Z_NAME VARCHAR);
                CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER PRIMARY KEY,
                    Z_ENT INTEGER, ZTITLE1 VARCHAR, ZFOLDER INTEGER,
                    ZMODIFICATIONDATE1 TIMESTAMP);
                CREATE TABLE ZICNOTEDATA (Z_PK INTEGER PRIMARY KEY,
                    ZNOTE INTEGER, ZDATA BLOB);
                INSERT INTO Z_PRIMARYKEY VALUES (8, 'ICNote');
                INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES
                    (1, 8, 'Lonely', NULL, 700000000);
            """)
            conn.execute("INSERT INTO ZICNOTEDATA (ZNOTE, ZDATA) VALUES "
                         "(1, ?)", (fn.blob([fn.run("only text\n")]),))
            conn.commit()

        reader = nt.NotesReader(make_connection(self, build))
        (note,) = reader.notes()
        self.assertEqual(reader.load(note).text, "only text")
        self.assertEqual(note.attachments, {})
        self.assertEqual(reader.folders(), [])
        self.assertIsNone(note.created)

    def test_a_database_with_no_notes_tables_gives_an_empty_list(self):
        def build(conn):
            conn.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER)")
            conn.commit()

        self.assertEqual(nt.NotesReader(make_connection(self, build)).notes(),
                         [])

    def test_without_the_entity_table_notes_are_found_by_their_data(self):
        conn = make_connection(self)
        conn.execute("DROP TABLE Z_PRIMARYKEY")
        reader = nt.NotesReader(conn)
        titles = sorted(n.title for n in reader.notes())
        self.assertIn("Shopping list", titles)


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        cases = {
            ("public.jpeg", "a.jpg"): "image",
            ("public.heic", "a.heic"): "image",
            ("com.apple.m4a-audio", "a.m4a"): "audio",
            ("com.apple.quicktime-movie", "voice_memo_01-audio.MOV"): "audio",
            ("com.apple.quicktime-movie", "clip.MOV"): "video",
            ("public.url", ""): "url",
            ("com.apple.notes.inlinetextattachment.mention", ""): "inline",
            ("com.apple.notes.table", ""): "table",
            ("com.apple.paper", ""): "drawing",
            ("com.apple.notes.gallery", ""): "scan",
            ("com.adobe.pdf", "a.pdf"): "file",
            ("com.adobe.pdf", ""): "other",
        }
        for (uti, name), kind in cases.items():
            with self.subTest(uti=uti, name=name):
                self.assertEqual(nt.classify(uti, name), kind)


class MediaResolverTests(unittest.TestCase):
    base = f"{fn.NOTES_ACCOUNT}/Media"

    def resolver(self, *paths):
        return nt.media_resolver(index_for(
            [(fn.NOTES_DOMAIN, p, b"x") for p in paths]))

    def test_the_file_with_the_wanted_name_beats_a_newer_other_file(self):
        resolve = self.resolver(f"{self.base}/M1/1_A/wanted.png",
                                f"{self.base}/M1/2_B/other.png")
        self.assertTrue(resolve("M1", "wanted.png").endswith("wanted.png"))

    def test_the_highest_generation_wins_and_ten_beats_nine(self):
        resolve = self.resolver(f"{self.base}/M1/9_A/f.png",
                                f"{self.base}/M1/10_B/f.png",
                                f"{self.base}/M1/2_C/f.png")
        self.assertIn("10_B", resolve("M1", "f.png"))

    def test_a_file_straight_inside_the_media_folder(self):
        resolve = self.resolver(f"{self.base}/M1/f.png")
        self.assertTrue(resolve("M1", "f.png").endswith("M1/f.png"))

    def test_unknown_ids_and_empty_backups(self):
        self.assertEqual(self.resolver(f"{self.base}/M1/f.png")("nope", "f"),
                         "")
        self.assertEqual(self.resolver()("M1", "f"), "")
        self.assertEqual(self.resolver(f"{self.base}/M1/f.png")(None, "f"), "")


if __name__ == "__main__":
    unittest.main()
