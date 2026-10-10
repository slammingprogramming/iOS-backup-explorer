# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Voicemail: reading the list, the audio and the words, exporting, and the
tab in the window."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from file_index import FileIndex
from ios_apps import records_export as rx
from ios_apps import records_view as rv
from ios_apps import voicemail as vm
from ios_apps.common import ContactBook
from tests import fixture_voicemail as fv
from tests.fixture_apps import build_addressbook, database_bytes
from tests.gui_apps import AppGuiCase


def make_index(files):
    rows = []
    for number, (domain, path, data) in enumerate(files):
        rows.append((f"id{number}", domain, path, 1, len(data), 0, 0))
    return FileIndex(rows)


def address_book():
    folder = tempfile.mkdtemp(prefix="ibe-vm-ab-")
    try:
        path = os.path.join(folder, "ab.sqlitedb")
        with open(path, "wb") as handle:
            handle.write(database_bytes(build_addressbook))
        conn = sqlite3.connect(path)
        try:
            return ContactBook.from_connection(conn)
        finally:
            conn.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class ReaderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-vm-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        files = fv.backup_files()
        self.index = make_index(files)
        for domain, path, data in files:       # the working copies
            if path.startswith(fv.FOLDER):
                with open(os.path.join(self.tmp, os.path.basename(path)),
                          "wb") as handle:
                    handle.write(data)
        self.conn = sqlite3.connect(os.path.join(self.tmp, "voicemail.db"))
        self.addCleanup(self.conn.close)
        self.rows = vm.voicemail_rows(self.conn, address_book(), self.index)
        self.by = {r["id"]: r for r in self.rows}


class ReaderTests(ReaderCase):
    def test_newest_first(self):
        self.assertEqual([r["id"] for r in self.rows], [7, 6, 5, 4, 3, 8])

    def test_dates_count_from_1970(self):
        self.assertEqual(self.by[3]["when"], fv.UNIX0)
        self.assertEqual(self.by[3]["expires"], fv.UNIX0 + 5_000_000)
        self.assertIsNone(self.by[6]["expires"])           # 0: never

    def test_who_called(self):
        self.assertEqual(self.by[3]["from"], "Alice Example")
        self.assertEqual(self.by[3]["number"], "+15550101234")
        self.assertEqual(self.by[4]["from"], "Pizza Place")
        self.assertEqual(self.by[5]["from"], "5559990000")
        self.assertEqual(self.by[5]["callback"], "5559990001")
        self.assertEqual(self.by[5]["name"], "")
        self.assertEqual(self.by[6]["from"], "5551112222")   # no sender
        self.assertEqual(self.by[8]["from"], "Alice Example")  # other form

    def test_without_an_address_book_the_number_is_shown(self):
        rows = vm.voicemail_rows(self.conn, None, self.index)
        self.assertEqual({r["id"]: r["from"] for r in rows}[3],
                         "+15550101234")

    def test_the_words(self):
        self.assertEqual(self.by[3]["transcript"],
                         "Hi, it is Alice calling about dinner.")
        self.assertEqual(self.by[4]["transcript"], "Your pizza is ready")
        self.assertEqual(self.by[5]["transcript"], "")      # not readable
        self.assertEqual(self.by[7]["transcript"], "")      # nothing said
        self.assertTrue(self.by[5]["has_transcript"])
        self.assertFalse(self.by[6]["has_transcript"])

    def test_the_audio(self):
        self.assertEqual(self.by[3]["audio"], f"HomeDomain/{fv.FOLDER}/3.amr")
        self.assertEqual(self.by[3]["size"], 46)
        self.assertEqual(self.by[8]["audio"], "")
        self.assertIsNone(self.by[8]["size"])

    def test_length(self):
        self.assertEqual(self.by[3]["length"], 34)
        self.assertIsNone(self.by[6]["length"])             # 0 = unknown

    def test_deleted(self):
        self.assertEqual(self.by[5]["deleted"], fv.UNIX0 + 9000)
        self.assertIsNone(self.by[3]["deleted"])

    def test_a_missing_voicemail_table(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(vm.datasets(conn, None, self.index), [])

    def test_files_in_the_folder(self):
        audio, words = vm.folder_files(self.index)
        self.assertEqual(sorted(audio), [3, 4, 5, 6, 7])
        self.assertEqual(sorted(words), [3, 4, 5, 7])
        self.assertEqual(vm.folder_files(None), ({}, {}))
        self.assertEqual(vm.folder_files(make_index([])), ({}, {}))

    def test_what_a_tab_copies(self):
        self.assertEqual(vm.discover(self.index), [
            vm.DATABASE] + [f"HomeDomain/{fv.FOLDER}/{n}.transcript"
                            for n in (3, 4, 5, 7)])
        self.assertEqual(vm.discover(make_index([])), [])
        self.assertEqual(vm.discover(None), [])

    def test_odd_names_in_the_folder_are_ignored(self):
        files = fv.backup_files() + [
            ("HomeDomain", f"{fv.FOLDER}/greeting.amr", b"x"),
            ("HomeDomain", f"{fv.FOLDER}/9.exe", b"x"),
            ("HomeDomain", f"{fv.FOLDER}/10.AMR", b"x")]
        audio, _ = vm.folder_files(make_index(files))
        self.assertEqual(sorted(audio), [3, 4, 5, 6, 7, 10])

    def test_a_folder_named_like_a_recording_is_not_one(self):
        rows = [(f"id{n}", d, p, 1, len(b), 0, 0)
                for n, (d, p, b) in enumerate(fv.backup_files())]
        rows.append(("dir1", "HomeDomain", f"{fv.FOLDER}/11.amr", 2, 0, 0, 0))
        audio, _ = vm.folder_files(FileIndex(rows))
        self.assertNotIn(11, audio)


class TranscriptTests(unittest.TestCase):
    def test_the_whole_text_wins_over_the_pieces(self):
        self.assertEqual(vm.transcript_text(
            {"transcriptionString": "All of it", "segments": [
                {"substring": "Part"}]}), "All of it")

    def test_pieces_are_joined(self):
        self.assertEqual(vm.transcript_text(
            {"segments": [{"substring": "a "}, {"substring": ""},
                          {"substring": "b"}, {"x": 1}, "junk"]}), "a b")

    def test_anything_else_is_empty(self):
        for value in (None, [], "text", {"segments": "no"}, {}):
            self.assertEqual(vm.transcript_text(value), "")

    def test_files_that_cannot_be_read(self):
        folder = tempfile.mkdtemp(prefix="ibe-vm-t-")
        self.addCleanup(shutil.rmtree, folder, True)
        self.assertEqual(vm.read_transcript(os.path.join(folder, "x")), "")
        path = os.path.join(folder, "t.transcript")
        for data in (b"", b"junk", b"bplist00 NSKeyedArchiver but broken"):
            with open(path, "wb") as handle:
                handle.write(data)
            self.assertEqual(vm.read_transcript(path), "")


class ExportTests(ReaderCase):
    def setUp(self):
        super().setUp()
        self.dataset = vm.datasets(self.conn, address_book(), self.index)[0]
        self.out = os.path.join(self.tmp, "out")

    def copier(self, calls):
        def copy(path, directory, name):
            calls.append((path, name))
            if path.endswith("6.amr"):
                return False                    # missing from the backup
            with open(os.path.join(directory, name), "wb") as handle:
                handle.write(b"audio")
            return True
        return copy

    def test_the_formats_offered(self):
        formats = rx.formats_for(self.dataset)
        self.assertEqual(list(formats)[-1], "audio")
        self.assertIn("csv", formats)

    def test_audio_with_the_words_beside_it(self):
        calls = []
        paths, notes = rx.export(self.dataset, self.rows, "audio", self.out,
                                 self.copier(calls))
        names = sorted(os.path.basename(p) for p in paths)
        stamp = vm.friendly_name(self.by[3], "")
        self.assertIn(stamp + ".amr", names)
        self.assertIn(stamp + ".txt", names)
        with open(os.path.join(self.out, stamp + ".txt"),
                  encoding="utf-8") as handle:
            self.assertEqual(handle.read(),
                             "Hi, it is Alice calling about dinner.\n")
        self.assertEqual(len(calls), 5)         # 8 has no audio: not asked
        self.assertIn("2 voicemail(s) have no audio", notes)   # 6 and 8
        self.assertEqual(sum(n.endswith(".txt") for n in names), 2)  # 3, 4

    def test_names_never_collide(self):
        twin = dict(self.by[3])
        calls = []
        paths, _ = rx.export(self.dataset, [self.by[3], twin], "audio",
                             self.out, self.copier(calls))
        audio = [os.path.basename(p) for p in paths if p.endswith(".amr")]
        self.assertEqual(len(set(n.casefold() for n in audio)), 2)
        self.assertTrue(any("(2)" in n for n in audio))

    def test_the_list_formats(self):
        for fmt in ("csv", "html", "txt", "json"):
            with self.subTest(fmt=fmt):
                (path,) = rx.export(self.dataset, self.rows, fmt, self.out)
                self.assertTrue(os.path.isfile(path))

    def test_save_name(self):
        name = vm.friendly_name(self.by[4], ".amr")
        self.assertTrue(name.endswith(" - Pizza Place.amr"))
        self.assertNotIn(":", name)
        row = dict(self.by[4], name="", number="")
        self.assertTrue(vm.friendly_name(row, ".m4a").endswith(
            " - Voicemail.m4a"))


class VoicemailGuiCase(AppGuiCase):
    def open_voicemail(self, encrypted=False, **kw):
        self.open_files(fv.backup_files(**kw), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Voicemail")

    def show(self):
        tab = self.show_tab("Voicemail")
        self.wait_for(lambda: tab.datasets, "the voicemails")
        return tab

    def column(self, key):
        tab = self.tab
        index = [c.key for c in tab.dataset.columns].index(key)
        return [tab.tree.item(i, "values")[index]
                for i in tab.tree.get_children()]

    def select(self, title_part):
        tab = self.tab
        row = next(r for r, v in tab._items.items()
                   if title_part in v["from"])
        tab.tree.selection_set(row)
        self.root.update()
        return tab._items[row]


class WindowTests(VoicemailGuiCase):
    def test_the_tab_appears_only_with_voicemail(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        self.open_voicemail()
        self.assertIn("Voicemail", self.tab_titles())

    def test_the_list(self):
        self.open_voicemail()
        tab = self.show()
        self.assertEqual(tab.state_var.get(), "6 rows")
        self.assertEqual(self.column("from")[:3], [
            "5550106666", "5551112222", "5559990000"])
        self.assertIn("Alice Example", self.column("from"))
        self.assertIn("Hi, it is Alice calling about dinner.",
                      self.column("transcript"))

    def test_the_words_are_searched(self):
        self.open_voicemail()
        tab = self.show()
        tab.search_var.set("pizza")
        tab.refresh()
        self.assertEqual(self.column("from"), ["Pizza Place"])

    def test_the_details(self):
        self.open_voicemail()
        self.show()
        self.select("Alice")
        text = self.tab.detail.get("1.0", "end")
        self.assertIn("Number: +15550101234", text)
        self.assertIn("Hi, it is Alice calling about dinner.", text)
        self.select("5559990000")
        text = self.tab.detail.get("1.0", "end")
        self.assertIn("Call back: 5559990001", text)
        self.assertIn("Deleted:", text)
        self.assertIn("(the transcript is empty)", text)
        self.select("5551112222")
        self.assertIn("(no transcript)", self.tab.detail.get("1.0", "end"))

    def test_play_and_save(self):
        self.open_voicemail()
        self.show()
        opened, saved = [], []
        with mock.patch.object(type(self.tab), "open_backup_file",
                               lambda s, p: opened.append(p)), \
                mock.patch.object(type(self.tab), "save_backup_file",
                                  lambda s, p, n: saved.append((p, n))):
            self.select("Alice")
            self.tab.run_action("play")
            self.tab._on_double()
            self.tab.run_action("save")
            row = next(v for v in self.tab._items.values() if v["id"] == 8)
            self.tab.action_play(row)
            self.tab.action_save(row)
        self.assertEqual(opened, [f"HomeDomain/{fv.FOLDER}/3.amr"] * 2)
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0][1].endswith(" - Alice Example.amr"))
        self.assertEqual(self.dialogs[-1][0], "showinfo")
        self.assertIn("not in the backup", self.dialogs[-1][1][1])

    def test_export_the_audio(self):
        self.open_voicemail()
        tab = self.show()
        out = os.path.join(self.tmp, "export")
        with mock.patch.object(rv, "ask_export",
                               return_value=("audio", "all", out)):
            tab.export()
            self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        names = os.listdir(out)
        self.assertEqual(sum(n.endswith(".amr") for n in names), 5)
        self.assertEqual(sum(n.endswith(".txt") for n in names), 2)
        alice = [n for n in names if "Alice" in n and n.endswith(".amr")]
        with open(os.path.join(out, alice[0]), "rb") as handle:
            self.assertEqual(handle.read(), b"#!AMR\n" + bytes([3]) * 40)

    def test_original_files(self):
        self.open_voicemail()
        tab = self.show()
        extracted = []
        self.explorer.apps.extract = extracted.append
        tab.extract_originals()
        (ids,) = extracted
        wanted = {self.ids[("HomeDomain", f"{fv.FOLDER}/{n}")]
                  for n in ("voicemail.db", "3.amr", "4.amr", "5.amr",
                            "6.amr", "7.amr", "3.transcript",
                            "4.transcript", "5.transcript",
                            "7.transcript")}
        self.assertEqual(set(ids), wanted)

    def test_an_encrypted_backup_and_no_recordings(self):
        self.open_voicemail(encrypted=True, audio=False, transcripts=False,
                            contacts=False)
        self.show()
        self.assertEqual(len(self.column("from")), 6)
        self.assertEqual(self.column("transcript"), [""] * 6)
        self.assertIn("5550101234", self.column("from"))


if __name__ == "__main__":
    unittest.main()
