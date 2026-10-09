# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Notes tab in the real window (skipped without a display)."""

import os
import tkinter.font as tkfont
import unittest
from unittest import mock

from ios_apps import common
from ios_apps import notes as nt
from ios_apps import notes_view as nv
from ios_apps import panel_base, pdf_export
from tests import fixture_notes as fn
from tests.fixture_apps import PNG_BYTES
from tests.gui_apps import AppGuiCase


class NotesGuiCase(AppGuiCase):
    def open_notes(self, encrypted=False, media=True):
        self.open_files(fn.backup_files(include_media=media),
                        encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Notes")

    def show(self):
        tab = self.show_tab("Notes")
        self.wait_for(lambda: tab.notes, "the notes")
        return tab

    def rows(self, parent=""):
        tree = self.tab.tree
        return [tree.item(i, "text") for i in tree.get_children(parent)]

    def select_note(self, title):
        tab = self.tab
        row = next(r for r, (kind, obj) in tab._items.items()
                   if kind == "note" and obj.title == title)
        tab.tree.selection_set(row)
        note = tab._items[row][1]
        self.wait_for(lambda: tab.rendered is note, f"{title!r} to show")
        self.root.update()
        return note

    def body_text(self):
        return self.tab.body.get("1.0", "end")

    def binding(self, tag):
        """The script bound to a click on *tag* ('' if there is none)."""
        body = self.tab.body
        return body.tk.call(body._w, "tag", "bind", tag, "<Button-1>")

    def font_of(self, index):
        names = [t for t in self.tab.body.tag_names(index)
                 if t.startswith("font")]
        return tkfont.Font(font=self.tab.body.tag_cget(names[-1], "font"))


class TabTests(NotesGuiCase):
    def test_the_tab_appears_only_when_the_backup_has_notes(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        self.open_notes()
        self.assertEqual(self.tab_titles(), ["Files", "Notes"])

    def test_it_loads_when_first_shown_and_only_once(self):
        self.open_notes()
        tab = self.tab
        self.assertFalse(tab._loaded)
        self.assertFalse(os.path.exists(os.path.join(
            self.explorer.apps.workspace.path, "notes")))
        self.show()
        self.assertTrue(tab._loaded)
        source = tab.source
        self.explorer.notebook.select(0)
        self.root.update()
        self.show_tab("Notes")
        self.assertIs(tab.source, source)
        self.assertIn("7 notes in 4 folders", tab.state_var.get())

    def test_the_working_copy_is_removed_when_the_backup_is_closed(self):
        self.open_notes()
        self.show()
        workspace = self.explorer.apps.workspace.path
        self.assertTrue(os.path.isdir(os.path.join(workspace, "notes")))
        self.explorer._clear_app_tabs()
        self.explorer.apps.reset()
        self.assertFalse(os.path.exists(workspace))

    def test_it_works_for_an_encrypted_backup(self):
        self.open_notes(encrypted=True)
        tab = self.show()
        self.select_note("Pancakes")
        self.assertIn("Mix flour", self.body_text())
        self.assertTrue(tab.notes)


class TreeTests(NotesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_notes()
        self.show()

    def test_folders_with_counts_and_the_trash_last(self):
        self.assertEqual(self.rows(), ["Notes  (5)", "Recipes  (2)",
                                       "Recently Deleted  (1)"])

    def test_notes_are_inside_their_folders_and_sub_folders_are_nested(self):
        tab = self.tab
        recipes = next(r for r, (k, o) in tab._items.items()
                       if k == "folder" and o.title == "Recipes")
        self.assertEqual(self.rows(recipes), ["Soups  (1)", "Pancakes"])
        soups = next(r for r, (k, o) in tab._items.items()
                     if k == "folder" and o.title == "Soups")
        self.assertEqual(self.rows(soups), ["Tomato soup"])

    def test_pinned_notes_come_first_then_newest(self):
        notes = next(r for r, (k, o) in self.tab._items.items()
                     if k == "folder" and o.title == "Notes")
        self.assertEqual(self.rows(notes), [
            "Shopping list", "Untitled note", "Secret", "Broken", "Empty"])

    def test_sorting_by_title_and_by_date_created(self):
        tab = self.tab
        notes = next(r for r, (k, o) in tab._items.items()
                     if k == "folder" and o.title == "Notes")
        tab.sort_var.set("Title")
        tab._show_tree()
        self.assertEqual(self.rows(notes), [
            "Shopping list", "Broken", "Empty", "Secret", "Untitled note"])
        tab.sort_var.set("Date created")
        tab._show_tree()
        self.assertEqual(self.rows(notes), [
            "Shopping list", "Secret", "Untitled note", "Broken", "Empty"])

    def test_the_date_column_shows_when_a_note_was_edited(self):
        tab = self.tab
        row = next(r for r, (k, o) in tab._items.items()
                   if k == "note" and o.title == "Pancakes")
        self.assertRegex(tab.tree.set(row, "when"), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")


class ShowingANoteTests(NotesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_notes()
        self.show()

    def test_text_lists_and_checkboxes(self):
        self.select_note("Shopping list")
        text = self.body_text()
        for expected in ("Shopping list", "Things to get", "[ ]\tMilk",
                         "[x]\tEggs", "\u2022\tApples", "\u2022\tGreen ones",
                         "1.\tWash up", "2.\tCook dinner",
                         "Party \U0001F389 time and site"):
            self.assertIn(expected, text)
        self.assertEqual(self.tab.title_var.get(), "Shopping list")
        self.assertIn("Notes", self.tab.info_var.get())
        self.assertIn("edited", self.tab.info_var.get())

    def test_titles_are_bigger_than_body_text_and_bold_is_bold(self):
        self.select_note("Shopping list")
        body = self.tab.body
        title = body.search("Shopping list", "1.0")
        heading = body.search("Things to get", "1.0")
        plain = body.search("Wash up", "1.0")
        bold = body.search("time", "1.0")
        self.assertGreater(self.font_of(title).actual("size"),
                           self.font_of(heading).actual("size"))
        self.assertGreater(self.font_of(heading).actual("size"),
                           self.font_of(plain).actual("size"))
        self.assertEqual(self.font_of(bold).actual("weight"), "bold")
        self.assertEqual(self.font_of(plain).actual("weight"), "normal")

    def test_list_markers_hang_in_a_column_next_to_the_text(self):
        self.select_note("Shopping list")
        body = self.tab.body
        tag = next(t for t in body.tag_names(body.search("Wash up", "1.0"))
                   if t.startswith("indent"))
        self.assertTrue(body.tag_cget(tag, "tabs"))           # not Tk's 8 chars
        self.assertGreater(int(body.tag_cget(tag, "lmargin2")),
                           int(body.tag_cget(tag, "lmargin1")))

    def test_a_checked_item_is_struck_through(self):
        self.select_note("Shopping list")
        body = self.tab.body
        eggs = body.search("Eggs", "1.0")
        milk = body.search("Milk", "1.0")
        self.assertIn("strike", body.tag_names(eggs))
        self.assertNotIn("strike", body.tag_names(milk))

    def test_links_are_clickable_and_underlined(self):
        self.select_note("Shopping list")
        body = self.tab.body
        site = body.search("site", "1.0")
        link = next(t for t in body.tag_names(site) if t.startswith("url"))
        self.assertEqual(body.tag_cget(link, "underline"), "1")
        self.assertTrue(self.binding(link))

    def test_unsafe_link_addresses_are_not_clickable(self):
        note = nt.Note(1, "t", loaded=True, paragraphs=[nt.Paragraph(spans=[
            nt.Span("go", link="javascript:alert(1)")])])
        tab = self.tab
        tab._render(note)
        link = next(t for t in tab.body.tag_names(tab.body.search("go", "1.0"))
                    if t.startswith("url"))
        self.assertFalse(self.binding(link))

    def test_attachments_show_as_chips_and_hashtags_as_text(self):
        self.select_note("Pancakes")
        self.assertIn("[Recording: Recording.m4a]", self.body_text())
        self.select_note("Shopping list")
        self.assertIn("#home", self.body_text())
        self.assertIn("Example site", self.body_text())

    def test_a_locked_note_explains_itself(self):
        self.tab.tree.selection_set(next(
            r for r, (k, o) in self.tab._items.items()
            if k == "note" and o.title == "Secret"))
        self.wait_for(lambda: "locked with a password" in self.body_text(),
                      "the explanation")
        self.assertIn("locked", self.tab.info_var.get())

    def test_a_damaged_note_still_shows_what_is_left(self):
        self.select_note("Broken")
        self.assertIn("could not be read", self.body_text())
        self.assertIn("what is left of it", self.body_text())

    def test_a_note_without_a_stored_title_gets_one(self):
        tab = self.tab
        self.assertIn("Untitled note", self.rows(next(
            r for r, (k, o) in tab._items.items()
            if k == "folder" and o.title == "Notes")))
        row = next(r for r, (k, o) in tab._items.items()
                   if k == "note" and o.pk == 14)
        tab.tree.selection_set(row)
        self.wait_for(lambda: tab.title_var.get() == "No stored title here",
                      "the derived title")
        self.assertEqual(tab.tree.item(row, "text"), "No stored title here")

    def test_a_late_answer_for_an_earlier_note_is_ignored(self):
        import concurrent.futures
        tab = self.tab
        self.select_note("Pancakes")
        stale = next(o for k, o in tab._items.values()
                     if k == "note" and o.title == "Shopping list")
        answer = concurrent.futures.Future()
        answer.set_result(stale)
        tab._note_loaded(answer, tab._request - 1)         # an old request
        self.assertIs(tab.rendered, tab.current)
        self.assertIn("Mix flour", self.body_text())
        self.assertEqual(tab.title_var.get(), "Pancakes")

    def test_picking_another_note_while_one_loads_shows_the_last(self):
        tab = self.tab
        first = next(r for r, (k, o) in tab._items.items()
                     if k == "note" and o.title == "Pancakes")
        second = next(r for r, (k, o) in tab._items.items()
                      if k == "note" and o.title == "Shopping list")
        tab.tree.selection_set(first)
        tab.tree.selection_set(second)
        self.wait_for(lambda: "Wash up" in self.body_text(), "the last note")
        self.root.update()
        self.assertNotIn("Mix flour", self.body_text())

    def test_pictures_are_drawn_inside_the_note(self):
        self.select_note("Shopping list")
        tab = self.tab
        self.wait_for(lambda: tab.body.image_names(), "the picture")
        self.assertNotIn("[Image: photo.png]", self.body_text())
        self.assertEqual(len(tab._photos), 1)

    def test_a_picture_that_cannot_be_drawn_stays_a_chip(self):
        with mock.patch.object(nv.imaging, "can_show", return_value=False):
            self.select_note("Shopping list")
            self.root.update()
        self.assertFalse(self.tab.body.image_names())
        self.assertIn("[Image: photo.png]", self.body_text())


class CallRecordingViewTests(NotesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_files(fn.backup_files(call_recordings=True))
        self.show()
        self.select_note("Call with Example Co")

    def test_the_recording_and_what_was_said_are_shown(self):
        text = self.body_text()
        self.assertIn("[Recording: Call with Example Co (2:05)]", text)
        self.assertIn("Hello, this is a test call.", text)
        self.assertIn("Only words.", text)

    def test_the_words_are_set_apart(self):
        body = self.tab.body
        spot = body.search("Hello, this", "1.0")
        self.assertIn("transcript", body.tag_names(spot))

    def test_the_recording_can_be_saved_and_opened(self):
        tab = self.tab
        call = tab.current.attachments["ATT-30"]
        self.assertTrue(call.path)                     # the menu is not greyed
        opened = []
        with mock.patch.object(common, "open_file", opened.append):
            tab.open_backup_file(call.path)
            self.wait_for(lambda: opened, "the player")
        with open(opened[0], "rb") as handle:
            self.assertEqual(handle.read(), fn.CALL_BYTES)
        self.assertTrue(opened[0].endswith(".m4a"))

    def test_the_words_can_be_searched_for(self):
        tab = self.tab
        tab.search_var.set("goodbye")
        tab._search()
        self.wait_for(lambda: tab.state_var.get().endswith(
            "matching notes"), "the results")
        self.assertEqual(self.rows(), ["Call with Example Co  — Notes"])

    def test_the_originals_include_the_recording(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        with mock.patch.object(nv.messagebox, "askyesnocancel",
                               return_value=True):
            self.tab.extract_originals()
            self.wait_for(lambda: extracted, "the request")
        (ids,) = extracted
        self.assertIn(self.ids[(fn.NOTES_DOMAIN, fn.CALL_FILE)], ids)


class SearchTests(NotesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_notes()
        self.show()

    def search(self, text):
        self.tab.search_var.set(text)
        self.tab._search()                      # without the typing delay
        self.wait_for(lambda: self.tab.state_var.get().endswith(
            "matching notes"), "the results")
        return self.rows()

    def test_search_finds_text_and_shows_the_folder(self):
        self.assertEqual(self.search("batter"), ["Pancakes  — Recipes"])
        self.assertEqual(self.search("tomato"), ["Tomato soup  — Soups"])
        self.assertIn("1 matching notes", self.tab.state_var.get())

    def test_search_finds_hashtags_and_link_titles(self):
        self.assertEqual(self.search("#home"), ["Shopping list  — Notes"])
        self.assertEqual(self.search("example site"),
                         ["Shopping list  — Notes"])

    def test_clearing_the_search_brings_the_folders_back(self):
        self.search("batter")
        self.tab.search_var.set("")
        self.tab._search()
        self.assertEqual(self.rows()[0], "Notes  (5)")

    def test_a_result_can_be_opened(self):
        self.search("batter")
        row = self.tab.tree.get_children()[0]
        self.tab.tree.selection_set(row)
        self.wait_for(lambda: "Mix flour" in self.body_text(), "the note")

    def test_typing_waits_a_moment_before_searching(self):
        tab = self.tab
        tab.search_var.set("pan")
        self.assertIn("search", tab._timers)
        tab.cancel_timers()
        self.assertEqual(tab._timers, {})


class ExportTests(NotesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_notes()
        self.show()
        self.out = os.path.join(self.tmp, "export")

    def export(self, fmt, notes=None):
        tab = self.tab
        before = len(self.dialogs)
        tab.export_to(notes or tab.notes, fmt, self.out)
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        return self.dialogs[-1]

    def test_every_format_through_the_window(self):
        for fmt, expected in (("txt", "Recipes/Pancakes.txt"),
                              ("md", "Notes/Shopping list.md"),
                              ("html", "index.html"),
                              ("json", "notes.json"),
                              ("csv", "notes.csv")):
            with self.subTest(fmt=fmt):
                self.out = os.path.join(self.tmp, f"out-{fmt}")
                kind, args = self.export(fmt)
                self.assertEqual(kind, "showinfo", args)
                self.assertTrue(os.path.isfile(os.path.join(
                    self.out, *expected.split("/"))), args)

    def test_html_includes_the_pictures_from_the_backup(self):
        self.export("html")
        photos = os.listdir(os.path.join(self.out, "attachments"))
        self.assertIn("00001_photo.png", photos)
        with open(os.path.join(self.out, "attachments", "00001_photo.png"),
                  "rb") as handle:
            self.assertEqual(handle.read(), PNG_BYTES)      # the newest one
        self.assertIn("00002_Recording.m4a", photos)

    @unittest.skipUnless(pdf_export.available(), "fpdf2 not installed")
    def test_pdf(self):
        kind, args = self.export("pdf")
        self.assertEqual(kind, "showinfo", args)
        with open(os.path.join(self.out, "Notes", "Shopping list.pdf"),
                  "rb") as handle:
            self.assertEqual(handle.read(5), b"%PDF-")

    def test_pdf_without_the_library_says_what_to_install(self):
        with mock.patch.object(pdf_export, "FPDF", None):
            kind, args = self.export("pdf")
        self.assertEqual(kind, "showerror")
        self.assertIn("pip install fpdf2", args[1])

    def test_the_dialog_scopes_and_the_chosen_notes(self):
        tab = self.tab
        calls = []

        def choose(parent, title, formats, scopes, default):
            calls.append((title, list(formats), dict(scopes), default))
            return ("txt", "folder", self.out)

        row = next(r for r, (k, o) in tab._items.items()
                   if k == "folder" and o.title == "Recipes")
        tab.tree.selection_set(row)
        with mock.patch.object(nv, "ask_export", side_effect=choose):
            tab.export()
        self.wait_for(lambda: self.dialogs, "the export")
        (title, formats, scopes, default), = calls
        self.assertEqual(formats, list(nv.nx.FORMATS))
        self.assertEqual(list(scopes), ["folder", "all"])
        self.assertIn("Recipes", scopes["folder"])
        self.assertIn("(2)", scopes["folder"])
        self.assertEqual(default, "folder")
        # the folder includes the sub-folder's note
        self.assertTrue(os.path.isfile(os.path.join(
            self.out, "Recipes", "Soups", "Tomato soup.txt")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.out, "Recipes", "Pancakes.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "Notes")))

    def test_exporting_only_the_chosen_note(self):
        tab = self.tab
        calls = []

        def choose(parent, title, formats, scopes, default):
            calls.append((list(scopes), default))
            return ("txt", "one", self.out)

        self.select_note("Pancakes")
        with mock.patch.object(nv, "ask_export", side_effect=choose):
            tab.export()
        self.wait_for(lambda: self.dialogs, "the export")
        self.assertEqual(calls[0][1], "one")
        self.assertEqual(self.listing(), ["Recipes/Pancakes.txt"])

    def listing(self):
        return sorted(os.path.relpath(os.path.join(root, name), self.out)
                      .replace("\\", "/")
                      for root, _dirs, names in os.walk(self.out)
                      for name in names)

    def test_cancelling_the_dialog_exports_nothing(self):
        with mock.patch.object(nv, "ask_export", return_value=None):
            self.tab.export()
        self.root.update()
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.dialogs, [])


class FilesAndOriginalsTests(NotesGuiCase):
    def setUp(self):
        super().setUp()
        # (a database with changes not yet merged into it has companion files)
        self.open_files(fn.backup_files() + [
            (fn.NOTES_DOMAIN, "NoteStore.sqlite-wal", b""),
            (fn.NOTES_DOMAIN, "NoteStore.sqlite-shm", b"")])
        self.show()
        self.extracted = []
        self.explorer.apps.extract = self.extracted.append

    def test_original_files_are_the_untouched_database_and_media(self):
        with mock.patch.object(nv.messagebox, "askyesnocancel",
                               return_value=False):
            self.tab.extract_originals()
            self.wait_for(lambda: self.extracted or self.dialogs, "the request")
        (ids,) = self.extracted
        path = lambda domain, rel: self.ids[(domain, rel)]
        self.assertIn(path(fn.NOTES_DOMAIN, "NoteStore.sqlite"), ids)
        self.assertIn(path(fn.NOTES_DOMAIN, "NoteStore.sqlite-wal"), ids)
        self.assertIn(path(fn.NOTES_DOMAIN, "NoteStore.sqlite-shm"), ids)
        self.assertIn(path(fn.NOTES_DOMAIN, fn.NOTES_FILES["photo"]), ids)
        self.assertIn(path(fn.NOTES_DOMAIN, fn.NOTES_FILES["voice"]), ids)
        self.assertNotIn(path(fn.NOTES_DOMAIN, fn.NOTES_FILES["photo_old"]),
                         ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_originals_of_one_note_only(self):
        self.select_note("Pancakes")
        with mock.patch.object(nv.messagebox, "askyesnocancel",
                               return_value=True):
            self.tab.extract_originals()
            self.wait_for(lambda: self.extracted, "the request")
        (ids,) = self.extracted
        voice = self.ids[(fn.NOTES_DOMAIN, fn.NOTES_FILES["voice"])]
        photo = self.ids[(fn.NOTES_DOMAIN, fn.NOTES_FILES["photo"])]
        self.assertIn(voice, ids)
        self.assertNotIn(photo, ids)

    def test_cancelling_the_question_extracts_nothing(self):
        self.select_note("Pancakes")
        with mock.patch.object(nv.messagebox, "askyesnocancel",
                               return_value=None):
            self.tab.extract_originals()
        self.root.update()
        self.assertEqual(self.extracted, [])

    def test_saving_an_attachment(self):
        self.select_note("Pancakes")
        attachment = next(iter(self.tab.current.attachments.values()))
        destination = os.path.join(self.tmp, "saved.m4a")
        with mock.patch("tkinter.filedialog.asksaveasfilename",
                        return_value=destination):
            self.tab.save_backup_file(attachment.path, attachment.name)
            self.wait_for(lambda: os.path.exists(destination)
                          and os.path.getsize(destination), "the saved file")
        with open(destination, "rb") as handle:
            self.assertEqual(handle.read(), fn.VOICE)

    def test_opening_an_attachment_uses_the_computers_viewer(self):
        self.select_note("Pancakes")
        attachment = next(iter(self.tab.current.attachments.values()))
        opened = []
        with mock.patch.object(common, "open_file", opened.append):
            self.tab.open_backup_file(attachment.path)
            self.wait_for(lambda: opened, "the viewer")
        self.assertTrue(opened[0].endswith(".m4a"))
        with open(opened[0], "rb") as handle:
            self.assertEqual(handle.read(), fn.VOICE)

    def test_a_program_is_never_started_from_here(self):
        self.open_files(fn.backup_files() + [
            ("HomeDomain", "Library/Other/run.bat", b"echo hello")])
        self.show()
        launched = []
        before = len(self.dialogs)
        with mock.patch.object(common.os, "startfile", launched.append,
                               create=True), \
                mock.patch("subprocess.Popen", launched.append):
            self.tab.open_backup_file("HomeDomain/Library/Other/run.bat")
            self.wait_for(lambda: len(self.dialogs) > before, "the answer")
        self.assertEqual(launched, [])
        kind, args = self.dialogs[-1]
        self.assertEqual(kind, "showinfo")
        self.assertIn("not opened", args[1])
        self.assertIn("Save as", args[1])

    def test_a_file_that_is_not_in_the_backup_is_reported(self):
        self.tab.open_backup_file("Nowhere/none.txt")
        self.tab.save_backup_file("Nowhere/none.txt", "none.txt")
        self.assertEqual([d[0] for d in self.dialogs], ["showinfo"] * 2)


class RobustnessTests(NotesGuiCase):
    def test_a_damaged_database_is_reported_not_raised(self):
        self.open_files([(fn.NOTES_DOMAIN, "NoteStore.sqlite",
                          b"this is not a database at all")])
        tab = self.show_tab("Notes")
        self.wait_for(lambda: "Could not" in tab.state_var.get(),
                      "the error message")

    def test_a_backup_with_an_empty_notes_database(self):
        self.open_files([(fn.NOTES_DOMAIN, "NoteStore.sqlite", b"")])
        tab = self.show_tab("Notes")
        self.wait_for(lambda: tab.state_var.get() not in ("", "Loading..."),
                      "something to be said")

    def test_closing_the_window_while_loading_is_harmless(self):
        self.open_notes()
        self.show_tab("Notes")
        self.explorer._clear_app_tabs()
        self.explorer.apps.reset()
        for _ in range(20):
            self.root.update()


if __name__ == "__main__":
    unittest.main()
