# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Locked notes in the real window: asking for passwords, remembering them,
and the export (skipped without a display)."""

import json
import os
import time
import unittest
from unittest import mock

from ios_apps import notes_unlock as nu
from ios_apps import notes_view as nv
from tests import fixture_notes_locked as fl
from tests.gui_apps import AppGuiCase


class LockedGuiCase(AppGuiCase):
    ENCRYPTED = False

    def setUp(self):
        super().setUp()
        self.open_files(fl.backup_files(), encrypted=self.ENCRYPTED)
        self.tab = self.panel_titled("Notes")
        self.explorer.notebook.select(self.tab)
        self.wait_for(lambda: self.tab.notes, "the notes")
        self.asked = []
        self.answers = []
        patcher = mock.patch.object(nv, "ask_password", side_effect=self.ask)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, parent, title, message, hint=""):
        self.asked.append((title, message, hint))
        return self.answers.pop(0) if self.answers else None

    def note(self, pk):
        return next(n for n in self.tab.notes if n.pk == pk)

    def row_text(self, pk):
        return self.tab.tree.item(f"n{pk}", "text")

    def click(self, pk):
        """Select a note the way a click does and wait for it to show."""
        tab = self.tab
        note = self.note(pk)
        tab.tree.selection_set(f"n{pk}")
        self.wait_for(lambda: tab.rendered is note, f"note {pk} to show")
        self.root.update()
        return note

    def settle(self, condition, what):
        self.wait_for(condition, what)
        self.root.update()

    def pump(self, seconds=0.5):
        """Let everything that is queued (results, idle jobs) happen."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.01)

    def body_text(self):
        return self.tab.body.get("1.0", "end")


class ClickingTests(LockedGuiCase):
    def test_locked_notes_are_marked(self):
        for pk in (fl.BANK, fl.DIARY, fl.VAULT, fl.BROKEN):
            self.assertTrue(self.row_text(pk).endswith("(locked)"), pk)
        self.assertNotIn("(locked)", self.row_text(10))

    def test_clicking_a_locked_note_asks_for_its_password(self):
        self.answers = [fl.SHARED]
        note = self.click(fl.BANK)
        self.settle(lambda: note.unlocked, "the note to open")
        self.settle(lambda: "4821" in self.body_text(), "its text")
        self.assertEqual(len(self.asked), 1)
        self.assertIn("Bank PINs", self.asked[0][1])
        self.assertEqual(self.asked[0][2], "")

    def test_the_hint_is_shown(self):
        self.click(fl.VAULT)
        self.settle(lambda: self.asked, "the question")
        self.assertEqual(self.asked[0][2], fl.HINT)

    def test_the_password_opens_the_other_notes_without_asking_again(self):
        self.answers = [fl.SHARED]
        self.click(fl.BANK)
        self.settle(lambda: self.note(fl.DIARY).unlocked, "the diary to open")
        self.settle(lambda: self.row_text(fl.DIARY).endswith("(unlocked)"),
                    "its row to say so")
        self.click(fl.DIARY)
        self.settle(lambda: "nothing happened" in self.body_text(), "text")
        self.assertEqual(len(self.asked), 1)          # only the first time

    def test_a_note_with_another_password_asks_again(self):
        self.answers = [fl.SHARED, fl.OTHER]
        self.click(fl.BANK)
        self.settle(lambda: self.note(fl.BANK).unlocked, "bank")
        self.assertFalse(self.note(fl.VAULT).unlocked)
        self.click(fl.VAULT)
        self.settle(lambda: self.note(fl.VAULT).unlocked, "vault")
        self.settle(lambda: "spare key" in self.body_text(), "text")
        self.assertEqual(len(self.asked), 2)

    def test_a_wrong_password_says_so_and_asks_again(self):
        self.answers = ["wrong", fl.SHARED]
        self.click(fl.BANK)
        self.settle(lambda: self.note(fl.BANK).unlocked
                    and not self.tab.unlock_button.winfo_manager(), "bank")
        self.assertEqual(len(self.asked), 2)
        self.assertTrue([d for d in self.dialogs if d[0] == "showwarning"])

    def test_cancelling_leaves_the_note_locked_with_a_button(self):
        self.answers = [None]
        note = self.click(fl.BANK)
        self.settle(lambda: self.asked, "the question")
        self.assertFalse(note.unlocked)
        self.assertIn("locked with a password", self.body_text())
        self.assertEqual(self.tab.unlock_button.winfo_manager(), "pack")
        self.answers = [fl.SHARED]
        self.tab.unlock_button.invoke()
        self.settle(lambda: note.unlocked
                    and not self.tab.unlock_button.winfo_manager(),
                    "the note to open")

    def test_other_changes_do_not_ask_again(self):
        # cancelled, then a password that opens other notes (not this one)
        self.answers = [None]
        self.click(fl.VAULT)
        self.settle(lambda: self.asked, "the question")
        self.answers = [fl.SHARED]
        self.tab.unlock_all()
        self.settle(lambda: self.note(fl.BANK).unlocked, "the others")
        self.settle(lambda: "Opened" in self.tab.state_var.get(), "message")
        self.pump()
        self.assertEqual(len(self.asked), 2)       # the click and the button
        self.tab.forget_passwords()
        self.settle(lambda: not self.note(fl.BANK).unlocked, "locked again")
        self.pump()
        self.assertEqual(len(self.asked), 2)       # forgetting never asks

    def test_a_note_that_can_never_open_does_not_ask(self):
        self.click(fl.BROKEN)
        self.click(12)
        self.root.update()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.tab.unlock_button.winfo_manager(), "")
        self.assertIn("locked", self.body_text())

    def test_search_includes_the_open_notes(self):
        self.answers = [fl.SHARED]
        self.click(fl.BANK)
        self.settle(lambda: self.note(fl.DIARY).unlocked, "diary")
        self.tab.search_var.set("nothing happened")
        self.settle(lambda: self.tab.tree.exists(f"n{fl.DIARY}")
                    and not self.tab.tree.exists(f"n{fl.BANK}"), "results")


class EncryptedBackupTests(LockedGuiCase):
    ENCRYPTED = True

    def test_a_locked_note_in_an_encrypted_backup(self):
        self.answers = [fl.SHARED]
        self.click(fl.DIARY)
        self.settle(lambda: "nothing happened" in self.body_text(), "text")


class AttachmentTests(LockedGuiCase):
    """The picture attached to "Bank PINs" is locked in the backup; once the
    note is open, every copy of it is opened."""

    def setUp(self):
        super().setUp()
        self.answers = [fl.SHARED]
        self.note_ = self.click(fl.BANK)
        self.settle(lambda: self.note_.unlocked, "the note to open")
        self.settle(lambda: self.note_.attachments
                    and self.tab.ctx.file_filters, "its files")
        self.path = self.note_.attachments["ATT-LOCKED"].path

    def test_the_file_in_the_backup_is_locked(self):
        self.assertNotEqual(fl.locked_file(), fl.LOCKED_PLAIN)
        self.assertIn(self.path, self.tab.ctx.file_filters)

    def test_a_working_copy_is_opened(self):
        copies = self.tab.ctx.fetch_local([self.path], "t").result(30)
        with open(copies[self.path], "rb") as handle:
            self.assertEqual(handle.read(), fl.LOCKED_PLAIN)

    def test_saving_a_file_gives_the_opened_one(self):
        out = os.path.join(self.tmp, "saved.png")
        self.tab.ctx.save_file(self.path, out).result(30)
        with open(out, "rb") as handle:
            self.assertEqual(handle.read(), fl.LOCKED_PLAIN)

    def test_the_copier_and_the_fetcher_open_it_too(self):
        folder = os.path.join(self.tmp, "c")
        os.makedirs(folder)
        self.assertTrue(self.tab.ctx.copier()(self.path, folder, "a.png"))
        with open(os.path.join(folder, "a.png"), "rb") as handle:
            self.assertEqual(handle.read(), fl.LOCKED_PLAIN)
        item = self.note_.attachments["ATT-LOCKED"]
        arrived = self.tab.ctx.fetcher(self.tmp)([(item, "b.png")])
        self.assertEqual(arrived, ["b.png"])
        with open(os.path.join(self.tmp, "attachments", "b.png"), "rb") as h:
            self.assertEqual(h.read(), fl.LOCKED_PLAIN)

    def test_an_export_holds_the_opened_file(self):
        out = os.path.join(self.tmp, "export")
        before = len(self.dialogs)
        self.tab.export_to([self.note_], "html", out)
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        found = []
        for folder, _dirs, files in os.walk(os.path.join(out, "attachments")):
            for name in files:
                with open(os.path.join(folder, name), "rb") as handle:
                    found.append(handle.read())
        self.assertIn(fl.LOCKED_PLAIN, found)
        self.assertNotIn(fl.locked_file(), found)

    def test_a_file_that_will_not_open_is_not_passed_on_locked(self):
        def broken(local):
            raise ValueError("no")

        self.tab.ctx.add_file_filter(self.path, broken)
        self.assertEqual(self.tab.ctx.fetch_local([self.path], "t").result(30),
                         {})
        out = os.path.join(self.tmp, "saved.png")
        with self.assertRaises(ValueError):
            self.tab.ctx.save_file(self.path, out).result(30)
        self.assertFalse(os.path.exists(out))
        folder = os.path.join(self.tmp, "c")
        os.makedirs(folder)
        self.assertFalse(self.tab.ctx.copier()(self.path, folder, "a.png"))
        self.assertEqual(os.listdir(folder), [])

    def test_forgetting_and_closing_drop_the_means_of_opening(self):
        self.tab.forget_passwords()
        self.settle(lambda: not self.note_.unlocked, "locked again")
        self.explorer.apps.reset()
        self.assertEqual(self.tab.ctx.file_filters, {})


class ExportWithoutClickingTests(LockedGuiCase):
    def test_an_export_of_a_note_that_was_never_shown_holds_the_opened_file(
            self):
        self.answers = [fl.SHARED]
        self.tab.unlock_all()                      # (no note is clicked)
        self.settle(lambda: self.note(fl.BANK).unlocked, "the note to open")
        self.assertEqual(self.tab.ctx.file_filters, {})
        out = os.path.join(self.tmp, "export")
        before = len(self.dialogs)
        self.tab.export_to([self.note(fl.BANK)], "html", out)
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        found = []
        for folder, _dirs, files in os.walk(os.path.join(out, "attachments")):
            for name in files:
                with open(os.path.join(folder, name), "rb") as handle:
                    found.append(handle.read())
        self.assertIn(fl.LOCKED_PLAIN, found)
        self.assertNotIn(fl.locked_file(), found)


class ButtonTests(LockedGuiCase):
    def test_unlock_notes_tries_one_password_on_all(self):
        self.answers = [fl.SHARED]
        self.tab.unlock_all()
        self.settle(lambda: "2 of 3" in self.tab.state_var.get(),
                    "the count")                  # (12 and 43 are hopeless)
        self.assertTrue(self.note(fl.BANK).unlocked
                        and self.note(fl.DIARY).unlocked)
        self.assertFalse(self.note(fl.VAULT).unlocked)

    def test_unlock_notes_with_a_wrong_password(self):
        self.answers = ["nope"]
        self.tab.unlock_all()
        self.settle(lambda: [d for d in self.dialogs
                             if d[0] == "showwarning"], "the warning")
        self.assertFalse(self.note(fl.BANK).unlocked)

    def test_unlock_notes_when_there_are_none_to_open(self):
        self.answers = [fl.SHARED]
        self.tab.unlock_all()
        self.settle(lambda: self.note(fl.BANK).unlocked, "open")
        self.answers = [fl.OTHER]
        self.tab.unlock_all()
        self.settle(lambda: self.note(fl.VAULT).unlocked, "open")
        before = len(self.dialogs)
        self.tab.unlock_all()                  # nothing left to unlock
        self.assertEqual(self.dialogs[before][0], "showinfo")
        self.assertEqual(self.answers, [])

    def test_forget_passwords_locks_everything_again(self):
        self.answers = [fl.SHARED]
        self.click(fl.BANK)
        self.settle(lambda: self.note(fl.BANK).unlocked, "open")
        self.tab.forget_passwords()
        self.settle(lambda: not self.note(fl.BANK).unlocked, "locked again")
        self.assertTrue(self.row_text(fl.BANK).endswith("(locked)"))
        self.assertIn("locked with a password", self.body_text())


class FakeDialog(nu.LockedNotesDialog):
    """The real dialog, driven by a script instead of a person."""
    script = None
    shown = []
    errors = []

    def grab_set(self):
        pass

    def wait_window(self, *args):
        FakeDialog.shown.append(self)
        try:
            FakeDialog.script(self)
        except BaseException as error:           # (Tk would only print it)
            FakeDialog.errors.append(error)
        self.update()
        if self.winfo_exists():
            self.destroy()


class ExportTests(LockedGuiCase):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "export")
        FakeDialog.shown = []
        FakeDialog.errors = []
        for patcher in (
                mock.patch.object(nv, "LockedNotesDialog", FakeDialog),
                mock.patch.object(nv, "ask_export", return_value=(
                    "json", "all", self.out))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_export(self, script=None):
        FakeDialog.script = script or (lambda dialog: dialog._ok())
        before = len(self.dialogs)
        self.tab.export()
        self.wait_for(lambda: len(self.dialogs) > before
                      or (script and FakeDialog.shown
                          and getattr(FakeDialog.shown[-1], "result", 1)
                          is None), "the export")
        self.root.update()
        if FakeDialog.errors:
            raise FakeDialog.errors[0]

    def exported(self):
        path = os.path.join(self.out, "notes.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return {n["title"]: n for n in json.load(handle)}

    def try_passwords(self, dialog, *passwords):
        for password in passwords:
            dialog.var.set(password)
            dialog._try_clicked()
            self.wait_for(lambda: not dialog._busy, "the password to be tried")
            self.root.update()

    def test_no_dialog_when_no_note_is_locked(self):
        notes = [n for n in self.tab.notes if not n.locked]
        with mock.patch.object(self.tab, "export_to") as export_to, \
                mock.patch.object(self.tab, "notes", notes):
            self.tab.export()
        self.assertEqual(FakeDialog.shown, [])
        self.assertTrue(export_to.called)

    def test_the_dialog_lists_the_locked_notes_and_their_hints(self):
        seen = {}

        def script(dialog):
            seen["rows"] = [dialog.tree.item(i, "text") for i in
                            dialog.tree.get_children()]
            seen["hints"] = [dialog.tree.item(i, "values")[0] for i in
                             dialog.tree.get_children()]
            seen["status"] = dialog.status_var.get()
            dialog.destroy()

        self.run_export(script)
        self.assertEqual(sorted(seen["rows"]), sorted(
            ["Bank PINs", "Diary", "Vault", "Broken lock", "Secret"]))
        self.assertIn(fl.HINT, seen["hints"])
        self.assertIn("5 of the notes", seen["status"])
        self.assertIsNone(self.exported())               # cancelled

    def test_trying_passwords_one_after_another(self):
        seen = []

        def script(dialog):
            self.try_passwords(dialog, "wrong")
            seen.append(dialog.message_var.get())
            seen.append(dialog.var.get())            # the entry is emptied
            self.try_passwords(dialog, fl.SHARED)
            seen.append(dialog.message_var.get())
            seen.append(sorted(n.pk for n in dialog.still_locked()))
            self.try_passwords(dialog, fl.OTHER)
            seen.append(dialog.message_var.get())
            seen.append(sorted(n.pk for n in dialog.still_locked()))
            dialog._ok()

        self.run_export(script)
        self.assertIn("does not open", seen[0])
        self.assertEqual(seen[1], "")
        self.assertIn("opened 2 notes", seen[2])
        self.assertEqual(seen[3], [12, fl.VAULT, fl.BROKEN])
        self.assertIn("opened 1 note.", seen[4])
        self.assertEqual(seen[5], [12, fl.BROKEN])         # hopeless ones
        data = self.exported()
        self.assertIn("4821", data["Bank PINs"]["text"])
        self.assertIn("spare key", data["Vault"]["text"])
        self.assertTrue(data["Vault"]["locked"])
        self.assertEqual(data["Vault"]["error"], "")

    def test_keep_lists_the_still_locked_notes_without_text(self):
        def script(dialog):
            self.try_passwords(dialog, fl.SHARED)
            dialog.choice.set(nu.KEEP)
            dialog._ok()

        self.run_export(script)
        data = self.exported()
        self.assertEqual(data["Vault"]["text"], "")
        self.assertIn("locked", data["Vault"]["error"])
        self.assertIn("Shopping list", data)

    def test_leave_drops_the_notes_that_stay_locked(self):
        def script(dialog):
            self.try_passwords(dialog, fl.SHARED)
            dialog.choice.set(nu.LEAVE)
            dialog._ok()

        self.run_export(script)
        data = self.exported()
        self.assertIn("Bank PINs", data)
        self.assertIn("Shopping list", data)
        for title in ("Vault", "Secret", "Broken lock"):
            self.assertNotIn(title, data)

    def test_only_exports_just_the_locked_notes_that_are_open(self):
        def script(dialog):
            self.try_passwords(dialog, fl.SHARED)
            dialog.choice.set(nu.ONLY)
            dialog._ok()

        self.run_export(script)
        self.assertEqual(sorted(self.exported()), ["Bank PINs", "Diary"])

    def test_cancelling_exports_nothing(self):
        self.run_export(lambda dialog: dialog.destroy())
        self.assertIsNone(self.exported())
        self.assertFalse([d for d in self.dialogs if d[0] == "showinfo"])

    def test_the_same_password_is_not_asked_twice(self):
        self.answers = [fl.SHARED]
        self.click(fl.BANK)
        self.settle(lambda: self.note(fl.DIARY).unlocked, "open")
        seen = []

        def script(dialog):
            seen.append(sorted(n.pk for n in dialog.still_locked()))
            dialog._ok()

        self.run_export(script)
        self.assertEqual(seen, [[12, fl.VAULT, fl.BROKEN]])  # not the open

    def test_no_dialog_when_everything_that_can_open_is_open(self):
        self.answers = [fl.SHARED]
        self.tab.unlock_all()
        self.settle(lambda: self.note(fl.BANK).unlocked, "open")
        self.answers = [fl.OTHER]
        self.tab.unlock_all()
        self.settle(lambda: self.note(fl.VAULT).unlocked, "open")
        self.run_export()
        self.assertEqual(FakeDialog.shown, [])      # (12 and 43 are hopeless)
        data = self.exported()
        self.assertIn("nothing happened", data["Diary"]["text"])

    def test_only_hopeless_locked_notes_do_not_ask(self):
        notes = [n for n in self.tab.notes if n.pk in (12, fl.BROKEN, 10)]
        with mock.patch.object(self.tab, "notes", notes):
            self.run_export()
        self.assertEqual(FakeDialog.shown, [])
        self.assertIn("Secret", self.exported())

    def test_the_dialog_does_nothing_without_a_password(self):
        def script(dialog):
            dialog._try = mock.Mock()
            dialog._try_clicked()                    # nothing typed
            self.root.update()
            self.assertFalse(dialog._busy)
            dialog._try.assert_not_called()
            dialog.destroy()

        self.run_export(script)


class PasswordDialogTests(AppGuiCase):
    def test_the_entry_hides_and_shows_the_password(self):
        dialog = nu.PasswordDialog(self.root, "t", "m", "my hint")
        self.addCleanup(dialog.destroy)
        self.assertEqual(dialog.entry.cget("show"), "•")
        dialog.show.set(True)
        dialog._toggle()
        self.assertEqual(dialog.entry.cget("show"), "")

    def test_ok_needs_a_password_and_returns_it(self):
        dialog = nu.PasswordDialog(self.root, "t", "m")
        dialog._ok()
        self.assertIsNone(dialog.result)             # nothing typed: stays
        self.assertTrue(dialog.winfo_exists())
        dialog.var.set("secret")
        dialog._ok()
        self.assertEqual(dialog.result, "secret")


if __name__ == "__main__":
    unittest.main()
