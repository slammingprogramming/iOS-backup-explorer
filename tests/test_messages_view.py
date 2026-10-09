# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Messages tab in the real window (skipped without a display)."""

import csv
import json
import gc
import os
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock

import ios_backup_explorer as app
from ios_apps import dialogs
from ios_apps import messages as ms
from ios_apps import messages_view as mv
from tests import fixture_apps as fa
from tests import fixture_backup as fb


def sms_with_a_sent_sms(conn):
    fa.build_sms_db(conn)
    conn.execute(
        "INSERT INTO message (guid, text, handle_id, service, date, "
        "is_from_me) VALUES ('G-SENT-SMS', 'Sent as a text', 2, 'SMS', ?, 1)",
        ((fa.T0 + 500) * fa.NS,))
    conn.execute("INSERT INTO chat_message_join VALUES (2, last_insert_rowid(),"
                 " 0)")
    conn.commit()


class MessagesGuiCase(unittest.TestCase):
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
        self.tmp = tempfile.mkdtemp(prefix="ibe-msgview-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dialogs = []
        for name in ("showerror", "showinfo", "showwarning"):
            patcher = mock.patch.object(
                app.messagebox, name,
                side_effect=lambda *a, _n=name, **k: self.dialogs.append(
                    (_n, a)))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(app.BackupExplorer, "BACKUP_PATHS", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.explorer = app.BackupExplorer(self.root)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        ex = self.explorer
        ex._cancel_timers()
        ex._clear_app_tabs()
        ex.apps.reset()
        ex.session.close()
        ex.session._executor.shutdown(wait=True)
        for child in self.root.winfo_children():
            child.destroy()
        # Drop the window and collect its garbage here, on the Tk thread:
        # left for later, the collector can run on a worker thread, which
        # may not finalise Tk variables.
        self.explorer = None
        gc.collect()

    def wait_for(self, condition, what, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {what}; status="
                  f"{self.explorer.status_var.get()!r}")

    def open_backup(self, encrypted=False, with_sms=True, with_contacts=True,
                    with_wal=False, builder=fa.build_sms_db):
        files = []
        if with_sms:
            if with_wal:
                db, wal, shm = fa.sms_db_with_wal()
                files += [("HomeDomain", "Library/SMS/sms.db-wal", wal),
                          ("HomeDomain", "Library/SMS/sms.db-shm", shm)]
            else:
                db = fa.database_bytes(builder)
            files.append(("HomeDomain", "Library/SMS/sms.db", db))
            files += [("MediaDomain", fa.ATTACHMENT_PATHS["photo"],
                       fa.PNG_BYTES),
                      ("MediaDomain", fa.ATTACHMENT_PATHS["notes"],
                       fa.NOTES_TXT)]
        if with_contacts:
            files.append(("HomeDomain",
                          "Library/AddressBook/AddressBook.sqlitedb",
                          fa.database_bytes(fa.build_addressbook)))
        files.append(("HomeDomain", "Library/Other/readme.txt", b"hello"))
        parent = tempfile.mkdtemp(dir=self.tmp)
        backup_dir, self.ids = fb.build_backup(parent, files=files,
                                               encrypted=encrypted)
        ex = self.explorer
        previous = ex.panel.index
        ex.path_var.set(backup_dir)
        if encrypted:
            ex.pass_var.set(fb.PASSPHRASE)
        ex._decrypt()
        self.wait_for(lambda: ex.panel.index is not None
                      and ex.panel.index is not previous,
                      "the new file index")

    # -- helpers on the panel ---------------------------------

    @property
    def tab(self):
        return self.explorer._app_panels[0]

    def show_tab(self):
        self.explorer.notebook.select(self.tab)
        self.wait_for(lambda: self.tab.conversations, "the conversations")

    def titles(self):
        tree = self.tab.conversation_tree
        return [tree.item(i, "text") for i in tree.get_children()]

    def select(self, title):
        tree = self.tab.conversation_tree
        item = next(i for i in tree.get_children()
                    if tree.item(i, "text") == title)
        conv = self.tab._items[item]
        tree.selection_set(item)
        # (the previous conversation's messages are still there until the
        # new ones arrive, so check that they are this conversation's)
        self.wait_for(lambda: self.tab.current is conv
                      and self.tab._messages
                      and self.tab._messages[0].chat_id in conv.chat_ids,
                      f"{title} to show")
        self.root.update()

    def chat(self):
        return self.tab.chat_text.get("1.0", "end")


class TabTests(MessagesGuiCase):
    def test_a_messages_tab_appears_only_when_the_backup_has_messages(self):
        self.open_backup(with_sms=False, with_contacts=False)
        self.assertEqual(self.explorer.notebook.tabs().__len__(), 1)
        self.assertEqual(self.explorer._app_panels, [])

    def test_the_tab_loads_when_it_is_first_shown(self):
        self.open_backup()
        # Messages, and the address book that is in the backup as well
        self.assertEqual(len(self.explorer.notebook.tabs()), 3)
        self.assertEqual(self.explorer.notebook.tab(self.tab, "text"),
                         "Messages")
        self.assertFalse(self.tab._loaded)          # nothing copied yet
        self.assertFalse(os.path.exists(os.path.join(
            self.explorer.apps.workspace.path, "messages")))
        self.show_tab()
        self.assertTrue(self.tab._loaded)
        self.assertEqual(self.titles(), [
            "+15550109999", "Weekend Plans", "Alice Example", "Bob Sample"])
        self.assertIn("4 conversations", self.tab.state_var.get())

    def test_the_tab_loads_only_once(self):
        self.open_backup()
        self.show_tab()
        with mock.patch.object(self.explorer.apps, "copy_database") as copy:
            self.explorer.notebook.select(0)
            self.explorer.notebook.select(self.tab)
            self.root.update()
        copy.assert_not_called()

    def test_conversation_list_columns(self):
        self.open_backup()
        self.show_tab()
        tree = self.tab.conversation_tree
        item = next(i for i in tree.get_children()
                    if tree.item(i, "text") == "Alice Example")
        self.assertEqual(tree.set(item, "count"), "9")
        self.assertRegex(tree.set(item, "last"), r"^\d{4}-\d{2}-\d{2} ")

    def test_without_an_address_book_the_numbers_show(self):
        self.open_backup(with_contacts=False)
        self.show_tab()
        self.assertIn("+15550101234", self.titles())
        self.assertNotIn("Alice Example", self.titles())

    def test_works_for_an_encrypted_backup(self):
        self.open_backup(encrypted=True)
        self.show_tab()
        self.assertEqual(len(self.titles()), 4)

    def test_opening_another_backup_removes_the_tab_and_the_copies(self):
        self.open_backup()
        self.show_tab()
        workspace = self.explorer.apps.workspace.path
        self.assertTrue(os.path.isdir(workspace))
        self.open_backup(with_sms=False, with_contacts=False)
        self.assertEqual(self.explorer._app_panels, [])
        self.assertEqual(len(self.explorer.notebook.tabs()), 1)
        self.assertFalse(os.path.exists(workspace))

    def test_the_connection_box_folds_away_once_a_backup_is_open(self):
        ex = self.explorer
        self.assertTrue(ex.conn_body.winfo_manager())          # at the start
        self.open_backup()
        self.assertFalse(ex.conn_body.winfo_manager())
        self.assertTrue(ex.change_btn.winfo_manager())
        ex.change_btn.invoke()
        self.assertTrue(ex.conn_body.winfo_manager())
        self.assertFalse(ex.change_btn.winfo_manager())
        self.open_backup(with_sms=False)                       # another one
        self.assertFalse(ex.conn_body.winfo_manager())

    def test_closing_removes_the_decrypted_copies(self):
        self.open_backup(encrypted=True)
        self.show_tab()
        workspace = self.explorer.apps.workspace.path
        self.assertTrue(os.path.exists(os.path.join(workspace, "messages",
                                                    "sms.db")))
        with mock.patch.object(self.root, "destroy"):
            self.explorer._on_close()
        self.assertFalse(os.path.exists(workspace))

    def test_recent_messages_kept_only_in_the_wal_file_are_shown(self):
        self.open_backup(with_wal=True)
        self.show_tab()
        self.select("Alice Example")
        self.assertIn("Only in the WAL", self.chat())


class ChatViewTests(MessagesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_backup(builder=sms_with_a_sent_sms)
        self.show_tab()
        self.select("Alice Example")

    def tags_at(self, needle):
        text = self.tab.chat_text
        index = text.search(needle, "1.0", "end")
        self.assertTrue(index, f"{needle!r} is not in the chat")
        return set(text.tag_names(index))

    def test_header(self):
        self.assertEqual(self.tab.title_var.get(), "Alice Example")
        self.assertIn("10 messages", self.tab.info_var.get())
        self.assertIn("SMS", self.tab.info_var.get())

    def test_the_conversation_reads_like_a_chat(self):
        chat = self.chat()
        for expected in ("Hey, are you free tonight?", "Yes! What time?",
                         "Around 7 \u2014 see you there \U0001F389",
                         "A caption with the photo",
                         "Old SMS from before iMessage"):
            self.assertIn(expected, chat)
        self.assertLess(chat.index("Old SMS from before iMessage"),
                        chat.index("Hey, are you free tonight?"))
        self.assertLess(chat.index("Hey, are you free tonight?"),
                        chat.index("Yes! What time?"))

    def test_bubbles_for_each_side_and_service(self):
        self.assertIn("recv_bg", self.tags_at("Hey, are you free tonight?"))
        self.assertIn("sent_bg", self.tags_at("Yes! What time?"))
        self.assertIn("sent_sms_bg", self.tags_at("Sent as a text"))
        self.assertIn("sent_line", self.tags_at("Yes! What time?"))
        self.assertIn("recv_line", self.tags_at("Hey, are you free tonight?"))

    def test_a_bubble_starts_with_a_plain_character(self):
        """Tk paints a line's margin with its first character's background,
        so that character must not have one or the bubble stretches across
        the whole pane."""
        text = self.tab.chat_text
        for needle in ("Yes! What time?", "Hey, are you free tonight?",
                       "photo.png"):
            where = text.search(needle, "1.0", "end")
            line_start = text.index(f"{where} linestart")
            tags = set(text.tag_names(line_start))
            self.assertFalse({t for t in tags if t.endswith("_bg")}, needle)
            self.assertTrue({t for t in tags if t.endswith("_line")}, needle)

    def test_a_long_message_is_a_rectangle_of_equal_lines(self):
        with mock.patch.object(self.tab, "_bubble_width", return_value=260):
            self.select("Bob Sample")
        text = self.tab.chat_text
        measure = self.tab._body_font.measure
        lines = []
        for number in range(1, int(text.index("end").split(".")[0])):
            tags = set(text.tag_names(f"{number}.3"))
            if "recv_bg" in tags:
                lines.append(text.get(f"{number}.1", f"{number}.end"))
        self.assertGreater(len(lines), 3)
        widths = [measure(line) for line in lines]
        self.assertLessEqual(max(widths) - min(widths),
                             self.tab._space * 2)
        self.assertLessEqual(max(widths), 260 + self.tab._space * 2)
        words = " ".join(lines).split()
        self.assertEqual(words, fa.LONG_TEXT.strip().split())

    def test_resizing_the_window_wraps_the_chat_again(self):
        tab = self.tab
        with mock.patch.object(tab, "_rewrap") as rewrap:
            tab._on_resize(mock.Mock(width=tab._rendered_width + 5))
            self.assertIsNone(tab._resize_job)       # too small a change
            tab._on_resize(mock.Mock(width=tab._rendered_width + 300))
            self.assertIsNotNone(tab._resize_job)
            self.wait_for(lambda: rewrap.call_count == 1, "the re-wrap")

    def test_day_headings_and_times(self):
        text = self.tab.chat_text
        heading = text.search("2025-", "1.0", "end")
        self.assertIn("day", text.tag_names(heading))
        self.assertRegex(self.chat(), r"\n[^\n]*\d{2}:\d{2}\n")

    def test_tapbacks_are_shown_under_the_message(self):
        self.assertIn("Liked by Me", self.chat())
        self.assertNotIn("Loved by", self.chat())          # that one was removed

    def test_attachments_are_listed_and_clickable(self):
        self.assertIn("photo.png (image/png, %d B)" % len(fa.PNG_BYTES),
                      self.chat())
        self.assertIn("notes.txt (text/plain, 18 B)", self.chat())
        self.assertIn("attachment", self.tags_at("photo.png"))
        self.assertEqual(len(self.tab._attachment_tags), 2)

    def test_a_group_conversation_names_who_spoke(self):
        self.select("Weekend Plans")
        chat = self.chat()
        self.assertIn("Bob Sample", chat)
        self.assertIn("named the conversation \u201cWeekend Plans\u201d", chat)
        self.assertIn("left the conversation", chat)
        self.assertIn("event", self.tags_at("left the conversation"))
        self.assertIn("with Alice Example, Bob Sample",
                      self.tab.info_var.get())

    def test_the_chat_cannot_be_edited(self):
        self.assertEqual(str(self.tab.chat_text.cget("state")), "disabled")

    def test_switching_conversations_replaces_the_text(self):
        self.select("Bob Sample")
        self.assertNotIn("Yes! What time?", self.chat())
        self.assertIn("This is a long message", self.chat())

    def test_long_conversations_load_in_pages(self):
        with mock.patch.object(mv, "PAGE", 3):
            self.select("Weekend Plans")
            self.select("Alice Example")
            self.assertTrue(self.tab.earlier_btn.winfo_manager())
            self.assertIn("earlier messages", self.tab.earlier_btn.cget("text"))
            self.assertIn("Sent as a text", self.chat())
            self.assertNotIn("Old SMS from before iMessage", self.chat())
            while self.tab._shown_from:
                self.tab.earlier_btn.invoke()
            self.assertIn("Old SMS from before iMessage", self.chat())
            self.assertFalse(self.tab.earlier_btn.winfo_manager())


class WrapTextTests(unittest.TestCase):
    def wrap(self, text, width):
        return mv.wrap_text(text, len, width)

    def test_words_are_kept_whole(self):
        self.assertEqual(self.wrap("hello world foo", 11),
                         ["hello world", "foo"])
        self.assertEqual(self.wrap("a b c d e f", 3),
                         ["a b", "c d", "e f"])

    def test_short_text_is_one_line(self):
        self.assertEqual(self.wrap("hi there", 80), ["hi there"])
        self.assertEqual(self.wrap("", 10), [""])

    def test_line_breaks_are_kept(self):
        self.assertEqual(self.wrap("one\ntwo\n\nfour", 80),
                         ["one", "two", "", "four"])

    def test_a_word_wider_than_the_line_is_broken(self):
        lines = self.wrap("x" * 25, 10)
        self.assertEqual(lines, ["x" * 10, "x" * 10, "x" * 5])
        lines = self.wrap("ab " + "y" * 25 + " cd", 10)
        self.assertTrue(all(len(line) <= 10 for line in lines))
        self.assertEqual("".join(lines).replace(" ", ""),
                         "ab" + "y" * 25 + "cd")

    def test_nothing_is_lost_and_it_always_ends(self):
        text = "The quick  brown fox\njumps over the lazy dog " * 5
        squash = lambda t: t.replace(" ", "").replace("\n", "")  # noqa: E731
        for width in (1, 2, 5, 17, 80):
            lines = self.wrap(text, width)
            self.assertEqual(squash("".join(lines)), squash(text), width)

    def test_wide_characters(self):
        measure = lambda t: sum(2 if ord(c) > 0x2e80 else 1 for c in t)  # noqa
        lines = mv.wrap_text("日本語 " * 6, measure, 10)
        self.assertTrue(all(measure(line) <= 10 for line in lines))


class SearchTests(MessagesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_backup()
        self.show_tab()

    def search(self, text):
        self.tab.search_var.set(text)
        self.wait_for(lambda: self.tab.state_var.get().endswith(
            "matching messages") and self.tab._search_job is None,
            "search results")

    def test_results_replace_the_conversation_list(self):
        self.search("snacks")
        self.assertTrue(self.tab.result_frame.winfo_manager())
        self.assertFalse(self.tab.list_frame.winfo_manager())
        tree = self.tab.result_tree
        (item,) = tree.get_children()
        self.assertEqual(tree.item(item, "text"), "Weekend Plans")
        self.assertIn("snacks", tree.set(item, "text"))
        self.assertEqual(self.tab.state_var.get(), "1 matching messages")

    def test_opening_a_result_jumps_to_that_message(self):
        self.search("see you there")
        tree = self.tab.result_tree
        tree.selection_set(tree.get_children()[0])
        self.tab._open_result()
        self.wait_for(lambda: self.tab._messages, "the conversation")
        self.assertEqual(self.tab.title_var.get(), "Alice Example")
        marked = self.tab.chat_text.tag_ranges("hit")
        self.assertTrue(marked)
        self.assertIn("see you there",
                      self.tab.chat_text.get(marked[0], marked[1]))

    def test_clearing_the_search_brings_the_conversations_back(self):
        self.search("snacks")
        self.tab.search_var.set("")
        self.wait_for(lambda: self.tab.list_frame.winfo_manager(),
                      "the conversation list")
        self.assertFalse(self.tab.result_frame.winfo_manager())

    def test_an_unsuccessful_search(self):
        self.search("zzzzzz")
        self.assertEqual(self.tab.result_tree.get_children(), ())

    def test_typing_is_debounced(self):
        with mock.patch.object(self.tab, "_run_search") as run:
            for text in ("s", "sn", "sna"):
                self.tab.search_var.set(text)
            self.assertEqual(run.call_count, 0)
            self.wait_for(lambda: run.call_count == 1, "one search")


class ExportTests(MessagesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_backup()
        self.show_tab()
        self.select("Alice Example")
        self.out = os.path.join(self.tmp, "export")

    def export(self, fmt, scope):
        with mock.patch.object(mv, "ask_export",
                               return_value=(fmt, scope, self.out)) as ask:
            self.tab.export(scope)
        self.wait_for(lambda: any(d[1][0] == "Export finished"
                                  for d in self.dialogs), "the export")
        return ask

    def test_the_dialog_offers_every_format_and_both_scopes(self):
        ask = self.export("txt", "one")
        _parent, title, formats, scopes, default = ask.call_args[0]
        self.assertEqual(set(formats), {"txt", "html", "csv", "json"})
        self.assertEqual(list(scopes), ["one", "all"])
        self.assertIn("Alice Example", scopes["one"])
        self.assertIn("4", scopes["all"])

    def test_html_with_attachments(self):
        self.export("html", "one")
        files = sorted(os.listdir(self.out))
        self.assertIn("index.html", files)
        self.assertIn("attachments", files)
        with open(os.path.join(self.out, "attachments",
                               "000001_photo.png"), "rb") as handle:
            self.assertEqual(handle.read(), fa.PNG_BYTES)
        page = next(f for f in files if "Alice" in f)
        with open(os.path.join(self.out, page), encoding="utf-8") as handle:
            html_page = handle.read()
        self.assertIn('src="attachments/000001_photo.png"', html_page)
        self.assertIn("Alice Example", html_page)

    def test_only_the_chosen_conversation_is_exported(self):
        self.export("txt", "one")
        (name,) = os.listdir(self.out)
        self.assertIn("Alice Example", name)

    def test_everything(self):
        self.export("txt", "all")
        self.assertEqual(len(os.listdir(self.out)), 4)

    def test_csv(self):
        self.export("csv", "all")
        with open(os.path.join(self.out, "messages.csv"),
                  encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 13)
        self.assertEqual({r["conversation"] for r in rows}, {
            "+15550109999", "Alice Example", "Bob Sample", "Weekend Plans"})

    def test_json(self):
        self.export("json", "all")
        with open(os.path.join(self.out, "messages.json"),
                  encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(len(data), 4)
        alice = next(c for c in data if c["title"] == "Alice Example")
        photo = next(a for m in alice["messages"] for a in m["attachments"]
                     if a["name"] == "photo.png")
        self.assertEqual(photo["file"], "attachments/000001_photo.png")
        self.assertTrue(os.path.isfile(os.path.join(self.out,
                                                    photo["file"])))

    def test_cancelling_the_dialog_exports_nothing(self):
        with mock.patch.object(mv, "ask_export", return_value=None):
            self.tab.export("one")
        self.root.update()
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.dialogs, [])

    def test_a_failed_export_says_why(self):
        with mock.patch.object(mv, "ask_export",
                               return_value=("txt", "one", self.out)), \
                mock.patch.object(mv.mx, "export",
                                  side_effect=OSError("disk full")):
            self.tab.export("one")
            self.wait_for(lambda: any(d[0] == "showerror"
                                      for d in self.dialogs), "the error")
        self.assertIn("disk full", self.dialogs[-1][1][1])

    def test_nothing_to_export(self):
        self.tab.conversations = []
        self.tab.export("all")
        self.assertIn("no messages", self.dialogs[-1][1][1])


class OriginalsAndAttachmentTests(MessagesGuiCase):
    def setUp(self):
        super().setUp()
        self.open_backup()
        self.show_tab()
        self.select("Alice Example")
        self.extracted = []
        self.explorer.apps.extract = self.extracted.append

    def originals(self, answer):
        with mock.patch.object(app.messagebox, "askyesnocancel",
                               return_value=answer, create=True), \
                mock.patch.object(mv.messagebox, "askyesnocancel",
                                  return_value=answer):
            self.tab.extract_originals()
            self.wait_for(lambda: self.extracted or self.dialogs,
                          "the extraction request")

    def test_this_conversations_originals(self):
        self.originals(True)
        (ids,) = self.extracted
        expected = {self.ids[("HomeDomain", "Library/SMS/sms.db")],
                    self.ids[("MediaDomain", fa.ATTACHMENT_PATHS["photo"])],
                    self.ids[("MediaDomain", fa.ATTACHMENT_PATHS["notes"])]}
        self.assertEqual(set(ids), expected)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_attachment(self):
        self.originals(False)
        (ids,) = self.extracted
        self.assertIn(self.ids[("MediaDomain", fa.ATTACHMENT_PATHS["photo"])],
                      ids)

    def test_cancelling(self):
        with mock.patch.object(mv.messagebox, "askyesnocancel",
                               return_value=None):
            self.tab.extract_originals()
        self.root.update()
        self.assertEqual(self.extracted, [])

    def test_the_wal_files_come_too(self):
        self.open_backup(with_wal=True)
        self.show_tab()
        self.select("Alice Example")
        self.extracted = []
        self.explorer.apps.extract = self.extracted.append
        self.originals(True)
        (ids,) = self.extracted
        for suffix in ("", "-wal", "-shm"):
            self.assertIn(
                self.ids[("HomeDomain", "Library/SMS/sms.db" + suffix)], ids)

    def test_saving_an_attachment(self):
        photo = next(a for m in self.tab._messages for a in m.attachments
                     if a.name == "photo.png")
        target = os.path.join(self.tmp, "saved.png")
        with mock.patch.object(mv.filedialog, "asksaveasfilename",
                               return_value=target):
            self.tab.save_attachment(photo)
        self.wait_for(lambda: os.path.exists(target)
                      and "Saved" in self.explorer.status_var.get(),
                      "the saved file")
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), fa.PNG_BYTES)

    def test_clicking_an_attachment_calls_save(self):
        text = self.tab.chat_text
        self.assertTrue(text.tk.call(text._w, "tag", "bind", "att0",
                                     "<Button-1>"))

    def test_an_attachment_that_is_not_in_the_backup(self):
        ghost = ms.Attachment(99, "gone.png", "image/png", None, 1,
                              "MediaDomain/Library/SMS/Attachments/no/such")
        self.tab.save_attachment(ghost)
        self.assertIn("not in the backup", self.dialogs[-1][1][1])

    def test_cancelling_the_save_dialog(self):
        photo = next(a for m in self.tab._messages for a in m.attachments)
        with mock.patch.object(mv.filedialog, "asksaveasfilename",
                               return_value=""):
            self.tab.save_attachment(photo)
        self.assertEqual(self.dialogs, [])


class ExportDialogTests(unittest.TestCase):
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
        # (runs last) collect the dialogs here, on the Tk thread: left for
        # later, the collector may run on a worker thread, which may not
        # finalise Tk variables
        self.addCleanup(gc.collect)

    def dialog(self, **kwargs):
        d = dialogs.ExportDialog(
            self.root, "Export", {"a": "Format A", "b": "Format B"},
            {"one": "Just one", "all": "Everything"}, **kwargs)
        self.addCleanup(lambda: d.winfo_exists() and d.destroy())
        return d

    def test_defaults(self):
        d = self.dialog()
        self.assertEqual((d.format_var.get(), d.scope_var.get()),
                         ("a", "one"))
        self.assertEqual(self.dialog(default_scope="all").scope_var.get(),
                         "all")
        self.assertEqual(self.dialog(default_scope="nope").scope_var.get(),
                         "one")

    def test_ok_returns_the_choices(self):
        d = self.dialog()
        d.format_var.set("b")
        d.scope_var.set("all")
        d.folder_var.set("C:/out")
        d._ok()
        self.assertEqual(d.result, ("b", "all", "C:/out"))

    def test_ok_asks_for_a_folder_when_there_is_none(self):
        d = self.dialog()
        with mock.patch.object(dialogs.filedialog, "askdirectory",
                               return_value="/chosen"):
            d._ok()
        self.assertEqual(d.result, ("a", "one", "/chosen"))

    def test_ok_without_any_folder_keeps_the_dialog_open(self):
        d = self.dialog()
        with mock.patch.object(dialogs.filedialog, "askdirectory",
                               return_value=""):
            d._ok()
        self.assertIsNone(d.result)
        self.assertTrue(d.winfo_exists())

    def test_cancel_returns_nothing(self):
        d = self.dialog()
        d.destroy()
        self.assertIsNone(d.result)


if __name__ == "__main__":
    unittest.main()
