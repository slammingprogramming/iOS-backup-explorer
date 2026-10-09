# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A recording kept in more than one form: the mixed audio file and the
original movie file with a track for each side of a call."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from ios_apps import audio_tools, dialogs
from ios_apps import notes as nt
from ios_apps import notes_export as nx
from tests import fixture_notes as fn
from tests.test_notes import index_for, make_connection

REAL = f"{fn.NOTES_DOMAIN}/"
M4A, MOV, ONLY = (REAL + fn.CALL_FILE, REAL + fn.CALL_MOV_FILE,
                  REAL + fn.ONLY_MOV_FILE)
HAVE_FFMPEG = audio_tools.available()


def slurp(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


def spit(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


class FormsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-forms-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        conn = make_connection(self, fn.build_with_call_recordings)
        index = index_for(fn.backup_files(call_recordings=True))
        self.reader = nt.NotesReader(conn, nt.media_resolver(index))
        self.note = next(self.reader.load(n) for n in self.reader.notes()
                         if n.pk == 19)
        self.folders = self.reader.folders_by_pk
        self.both = self.note.attachments["ATT-30"]
        self.only = self.note.attachments["ATT-36"]

    def fetch(self, folder):
        """A stand-in for the backup: writes each file's real bytes."""
        contents = {M4A: fn.CALL_BYTES, MOV: fn.CALL_MOV_BYTES,
                    ONLY: fn.ONLY_MOV_BYTES}

        def fetch(wanted):
            target = os.path.join(folder, "attachments")
            os.makedirs(target, exist_ok=True)
            for item, name in wanted:
                spit(os.path.join(target, name),
                     contents.get(item.path, b"other bytes"))
            return [name for _item, name in wanted]

        return fetch

    def export(self, fmt, mode, mixer=None, name=None, can_mix=True):
        folder = os.path.join(self.tmp, name or f"{fmt}-{mode}")
        if mixer is None:
            mixer = fake_mixer
        with mock.patch.object(audio_tools, "available",
                               return_value=can_mix):
            paths = nx.export([self.note], self.folders, fmt, folder,
                              self.fetch(folder), mode,
                              mixer if can_mix else None)
        return folder, paths

    def files(self, folder):
        return sorted(os.listdir(os.path.join(folder, "attachments")))


def fake_mixer(source, destination):
    spit(destination, b"mixed:" + slurp(source, "rb"))
    return True


class ReaderTests(FormsCase):
    def test_a_recording_with_two_files_lists_the_mixed_audio_first(self):
        # (the movie was stored first; the order does not depend on that)
        self.assertEqual([(v.name, v.kind) for v in self.both.variants], [
            ("call.m4a", "mixed"), ("moments_call-audio.MOV", "tracks")])
        self.assertEqual(self.both.path, M4A)

    def test_the_picture_beside_a_recording_is_not_one_of_its_forms(self):
        self.assertEqual(len(self.both.variants), 2)

    def test_a_recording_kept_only_as_a_movie_has_that_one_form(self):
        self.assertEqual([v.kind for v in self.only.variants], ["tracks"])
        self.assertEqual(self.only.path, ONLY)

    def test_labels(self):
        mixed, tracks = self.both.variants
        self.assertEqual(mixed.label, "mixed audio (.m4a)")
        self.assertEqual(tracks.label,
                         "original with separate tracks (.mov)")
        self.assertEqual(nt.Variant("x/a.bin", "a.bin").label, "file (.bin)")
        self.assertEqual(nt.Variant("x", "a.MP3").kind, "mixed")

    def test_a_mixed_form_can_be_made_from_a_movie_only_recording(self):
        forms = nt.recording_forms(self.only, can_mix=True)
        self.assertEqual([(v.kind, v.mix) for v in forms],
                         [("tracks", False), ("mixed", True)])
        self.assertEqual(forms[1].name, "moments_only-audio.m4a")
        self.assertEqual(forms[1].path, ONLY)         # made from that file
        self.assertNotEqual(forms[1].key, forms[0].key)
        self.assertEqual(len(nt.recording_forms(self.only, can_mix=False)), 1)

    def test_a_recording_that_has_a_mixed_form_is_not_mixed_again(self):
        self.assertFalse(any(v.mix for v in
                             nt.recording_forms(self.both, can_mix=True)))

    def test_no_forms_without_a_file(self):
        self.assertEqual(
            nt.recording_forms(self.note.attachments["ATT-31"], True), [])

    def test_choosing_among_forms(self):
        pick = lambda a, mode, forms=None: nt.pick_variants(a, mode, forms)
        main, also = pick(self.both, "mixed")
        self.assertEqual((main.kind, also), ("mixed", []))
        main, also = pick(self.both, "original")
        self.assertEqual((main.kind, also), ("tracks", []))
        main, also = pick(self.both, "both")
        self.assertEqual((main.kind, [v.kind for v in also]),
                         ("mixed", ["tracks"]))
        # only a movie, and nothing to mix it with: it is all there is
        for mode in ("mixed", "original", "both"):
            main, also = pick(self.only, mode)
            self.assertEqual((main.path, also), (ONLY, []))

    def test_what_the_questions_in_the_window_rest_on(self):
        self.assertTrue(self.reader.has_audio_attachments())
        self.assertTrue(self.reader.has_recordings_in_parts())
        self.assertTrue(self.reader.has_recording_forms([self.note]))
        plain = nt.NotesReader(make_connection(self))
        self.assertFalse(plain.has_recordings_in_parts())
        self.assertTrue(plain.has_audio_attachments())       # the voice one
        self.assertFalse(plain.has_recording_forms())

    def test_originals_to_extract(self):
        paths = lambda mode: self.reader.attachment_paths([self.note], mode)
        both = paths("both")
        for expected in (M4A, MOV, ONLY):
            self.assertIn(expected, both)
        mixed = paths("mixed")
        self.assertIn(M4A, mixed)
        self.assertNotIn(MOV, mixed)
        self.assertIn(ONLY, mixed)               # its only file
        original = paths("original")
        self.assertIn(MOV, original)
        self.assertNotIn(M4A, original)
        self.assertEqual(len(original), len(set(original)))


class ChooseTests(FormsCase):
    def attachment(self, notes, ident="ATT-30"):
        return notes[0].attachments[ident]

    def test_the_notes_given_are_not_changed(self):
        before = dict(self.note.attachments)
        nx.choose_recordings([self.note], "original", can_mix=True)
        self.assertEqual(self.note.attachments, before)
        self.assertEqual(self.both.path, M4A)

    def test_each_choice(self):
        for mode, path, also in (("mixed", M4A, []), ("original", MOV, []),
                                 ("both", M4A, [MOV])):
            with self.subTest(mode=mode):
                notes = nx.choose_recordings([self.note], mode)
                attachment = self.attachment(notes)
                self.assertEqual(attachment.path, path)
                self.assertEqual([v.path for v in attachment.also], also)

    def test_the_files_of_a_recording_are_not_listed_beside_it(self):
        notes = nx.choose_recordings([self.note], "mixed")
        self.assertNotIn("ATT-29", notes[0].attachments)
        self.assertNotIn("ATT-34", notes[0].attachments)
        self.assertIn("ATT-30", notes[0].attachments)

    def test_mixing_is_only_offered_when_it_can_be_done(self):
        mixed = nx.choose_recordings([self.note], "mixed", can_mix=True)
        only = self.attachment(mixed, "ATT-36")
        self.assertTrue(only.mix)
        self.assertEqual((only.path, only.name),
                         (ONLY, "moments_only-audio.m4a"))
        mixed = nx.choose_recordings([self.note], "mixed", can_mix=False)
        only = self.attachment(mixed, "ATT-36")
        self.assertFalse(only.mix)
        self.assertEqual(only.name, "moments_only-audio.MOV")

    def test_original_and_both_for_a_movie_only_recording(self):
        original = self.attachment(nx.choose_recordings(
            [self.note], "original", True), "ATT-36")
        self.assertEqual((original.mix, original.name),
                         (False, "moments_only-audio.MOV"))
        both = self.attachment(nx.choose_recordings(
            [self.note], "both", True), "ATT-36")
        self.assertTrue(both.mix)
        self.assertEqual([v.name for v in both.also],
                         ["moments_only-audio.MOV"])

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            nx.choose_recordings([self.note], "everything")


class ExportTests(FormsCase):
    def test_the_mixed_file_only(self):
        folder, _ = self.export("html", "mixed")
        files = self.files(folder)
        self.assertEqual([n.split("_", 1)[1] for n in files],
                         ["call.m4a", "moments_only-audio.m4a"])
        mixed = slurp(os.path.join(folder, "attachments", files[1]), "rb")
        self.assertEqual(mixed, b"mixed:" + fn.ONLY_MOV_BYTES)

    def test_the_original_file_only(self):
        folder, _ = self.export("html", "original")
        self.assertEqual(
            [n.split("_", 1)[1] for n in self.files(folder)],
            ["moments_call-audio.MOV", "moments_only-audio.MOV"])
        page = slurp(os.path.join(folder, "Notes",
                                  "Call with Example Co.html"),
                     encoding="utf-8")
        self.assertIn("MOV", page)
        self.assertNotIn(".m4a", page)

    def test_both_files_and_a_link_to_the_other_one(self):
        folder, _ = self.export("html", "both")
        names = [n.split("_", 1)[1] for n in self.files(folder)]
        self.assertEqual(sorted(names), sorted([
            "call.m4a", "moments_call-audio.MOV", "moments_only-audio.m4a",
            "moments_only-audio.MOV"]))
        page = slurp(os.path.join(folder, "Notes",
                                  "Call with Example Co.html"),
                     encoding="utf-8")
        self.assertIn("original with separate tracks (.mov)</a>", page)
        for target in re.findall(r"(?:src|href)=\"(\.\./attachments/[^\"]+)\"",
                                 page):
            self.assertTrue(os.path.isfile(os.path.join(
                folder, "Notes", *target.split("/"))), target)

    def test_markdown_links_the_other_form(self):
        folder, _ = self.export("md", "both")
        text = slurp(os.path.join(folder, "Notes",
                                  "Call with Example Co.md"),
                     encoding="utf-8")
        self.assertIn("(also: [original with separate tracks (.mov)](", text)

    def test_json_names_the_files(self):
        folder, paths = self.export("json", "both")
        (data,) = json.loads(slurp(paths[0], encoding="utf-8"))
        call = next(a for a in data["attachments"] if a["id"] == "ATT-30")
        self.assertTrue(call["file"].endswith("call.m4a"))
        self.assertEqual(len(call["other_files"]), 1)
        self.assertTrue(call["other_files"][0].endswith(".MOV"))
        # the files of a recording are not listed as attachments of their own
        self.assertNotIn("ATT-29", [a["id"] for a in data["attachments"]])

    def test_the_mixing_leaves_no_working_copy_behind(self):
        folder, _ = self.export("html", "mixed")
        self.assertFalse([n for n in self.files(folder) if ".source" in n])

    def test_when_the_mixing_fails_the_original_is_kept_and_linked(self):
        folder, _ = self.export("html", "mixed", mixer=lambda s, d: False)
        names = [n.split("_", 1)[1] for n in self.files(folder)]
        self.assertIn("moments_only-audio.source.MOV", names)
        page = slurp(os.path.join(folder, "Notes",
                                  "Call with Example Co.html"),
                     encoding="utf-8")
        self.assertIn("source.MOV", page)

    def test_without_a_mixer_a_movie_only_recording_stays_a_movie(self):
        folder, _ = self.export("html", "mixed", can_mix=False)
        names = [n.split("_", 1)[1] for n in self.files(folder)]
        self.assertEqual(names, ["call.m4a", "moments_only-audio.MOV"])

    def test_text_and_csv_need_no_files(self):
        for fmt in ("txt", "csv"):
            with self.subTest(fmt=fmt):
                folder, paths = self.export("txt" if fmt == "txt" else "csv",
                                            "both", name=f"plain-{fmt}")
                self.assertFalse(os.path.exists(
                    os.path.join(folder, "attachments")))
                self.assertTrue(paths)

    def test_the_default_is_the_mixed_recording(self):
        folder = os.path.join(self.tmp, "default")
        nx.export([self.note], self.folders, "json", folder,
                  self.fetch(folder), mixer=fake_mixer)
        names = [n.split("_", 1)[1] for n in self.files(folder)]
        self.assertIn("call.m4a", names)
        self.assertNotIn("moments_call-audio.MOV", names)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is not installed")
class FfmpegTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-ffmpeg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def movie(self, tracks):
        """A small movie file with *tracks* audio tracks (a tone each)."""
        path = os.path.join(self.tmp, f"tracks{tracks}.mov")
        command = [audio_tools.find_tool("ffmpeg"), "-v", "error", "-y"]
        for n in range(tracks):
            command += ["-f", "lavfi", "-i",
                        f"sine=frequency={440 * (n + 1)}:duration=1"]
        for n in range(tracks):
            command += ["-map", str(n)]
        command += ["-c:a", "aac", path]
        subprocess.run(command, check=True, capture_output=True)
        return path

    def test_counting_tracks(self):
        self.assertEqual(audio_tools.audio_stream_count(self.movie(2)), 2)
        self.assertEqual(audio_tools.audio_stream_count(self.movie(1)), 1)
        self.assertEqual(audio_tools.audio_stream_count(
            os.path.join(self.tmp, "missing.mov")), 0)

    def test_two_tracks_become_one_audio_file(self):
        source = self.movie(2)
        target = os.path.join(self.tmp, "mixed.m4a")
        self.assertTrue(audio_tools.mix_to_m4a(source, target))
        self.assertEqual(audio_tools.audio_stream_count(target), 1)
        self.assertGreater(os.path.getsize(target), 1000)
        self.assertTrue(os.path.isfile(source))           # never changed

    def test_one_track_works_too(self):
        target = os.path.join(self.tmp, "one.m4a")
        self.assertTrue(audio_tools.mix_to_m4a(self.movie(1), target))
        self.assertEqual(audio_tools.audio_stream_count(target), 1)

    def test_something_that_is_not_media_leaves_nothing_behind(self):
        junk = os.path.join(self.tmp, "junk.mov")
        spit(junk, b"this is not a movie")
        target = os.path.join(self.tmp, "junk.m4a")
        self.assertFalse(audio_tools.mix_to_m4a(junk, target))
        self.assertFalse(os.path.exists(target))

    def test_a_whole_export_with_a_real_mix(self):
        movie = self.movie(2)
        with open(movie, "rb") as handle:
            data = handle.read()
        attachment = nt.Attachment(
            "A", "com.apple.m4a-audio", "audio", "call.MOV", "D/call.MOV",
            variants=[nt.Variant("D/call.MOV", "call.MOV")], pk=1)
        note = nt.Note(1, "Call", folder=2, loaded=True, paragraphs=[
            nt.Paragraph(spans=[nt.Span("\ufffc", attachment="A")])],
            attachments={"A": attachment})
        folder = os.path.join(self.tmp, "out")

        def fetch(wanted):
            target = os.path.join(folder, "attachments")
            os.makedirs(target, exist_ok=True)
            for _item, name in wanted:
                spit(os.path.join(target, name), data)
            return [name for _item, name in wanted]

        nx.export([note], {}, "html", folder, fetch, "mixed")
        (name,) = os.listdir(os.path.join(folder, "attachments"))
        self.assertTrue(name.endswith("call.m4a"), name)
        self.assertEqual(audio_tools.audio_stream_count(
            os.path.join(folder, "attachments", name)), 1)


class WithoutFfmpegTests(unittest.TestCase):
    def test_everything_says_no(self):
        with mock.patch.object(audio_tools, "find_tool", return_value=None):
            self.assertFalse(audio_tools.available())
            self.assertEqual(audio_tools.audio_stream_count("x.mov"), 0)
            self.assertFalse(audio_tools.mix_to_m4a("x.mov", "x.m4a"))


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display available")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        import gc
        self.addCleanup(gc.collect)         # (on the Tk thread, see the others)

    def make(self, cls, *args, **kwargs):
        dialog = cls(self.root, *args, **kwargs)
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        return dialog

    def test_the_export_dialog_answers_the_extra_question(self):
        dialog = self.make(dialogs.ExportDialog, "Export", {"a": "A"},
                           {"all": "All"}, None,
                           {"title": "Which?", "options": {"x": "X", "y": "Y"},
                            "default": "y"})
        self.assertEqual(dialog.extra_var.get(), "y")
        dialog.folder_var.set("somewhere")
        dialog.extra_var.set("x")
        dialog._ok()
        self.assertEqual(dialog.result, ("a", "all", "somewhere", "x"))

    def test_without_the_extra_question_the_answer_is_as_before(self):
        dialog = self.make(dialogs.ExportDialog, "Export", {"a": "A"},
                           {"all": "All"})
        dialog.folder_var.set("somewhere")
        dialog._ok()
        self.assertEqual(dialog.result, ("a", "all", "somewhere"))

    def test_a_choice(self):
        dialog = self.make(dialogs.ChoiceDialog, "T", "Which?",
                           {"a": "A", "b": "B"}, "b")
        self.assertEqual(dialog.var.get(), "b")
        dialog.var.set("a")
        dialog._ok()
        self.assertEqual(dialog.result, "a")

    def test_a_cancelled_choice_has_no_answer(self):
        dialog = self.make(dialogs.ChoiceDialog, "T", "Which?", {"a": "A"})
        self.assertEqual(dialog.var.get(), "a")        # the first by default
        dialog.destroy()
        self.assertIsNone(dialog.result)

    def test_an_unknown_default_falls_back_to_the_first(self):
        dialog = self.make(dialogs.ChoiceDialog, "T", "Q", {"a": "A"}, "zzz")
        self.assertEqual(dialog.var.get(), "a")


if __name__ == "__main__":
    unittest.main()
