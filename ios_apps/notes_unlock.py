# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — asking for the passwords of locked notes
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""The two dialogs for locked notes.

``PasswordDialog`` asks for one password (for the note just clicked).
``LockedNotesDialog`` is shown when an export holds locked notes: the person
types passwords one after another, each tried on every note that is still
locked, until all are open or they decide what to do with the rest.

Neither dialog knows how to open a note: they are given a function that tries
a password and reports back. A password is held in the dialog's entry only
until the dialog closes.
"""

import tkinter as tk
from tkinter import ttk

# what to do with the notes that are still locked, in an export
KEEP = "keep"        # export them as locked entries, without their text
LEAVE = "leave"      # export everything else
ONLY = "only"        # export just the locked notes that are open
CHOICES = {
    KEEP: "Export everything; notes that stay locked are listed without "
          "their text",
    LEAVE: "Export everything except the notes that are still locked",
    ONLY: "Export only the locked notes that are open (nothing else)",
}


class PasswordDialog(tk.Toplevel):
    """Ask for a password. ``result`` is the text typed, or None."""

    def __init__(self, parent, title, message, hint=""):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.var = tk.StringVar()
        self.show = tk.BooleanVar(value=False)
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=message, wraplength=420,
                  justify="left").pack(anchor="w")
        if hint:
            ttk.Label(body, text=f"Hint: {hint}", wraplength=420,
                      justify="left", style="Subtitle.TLabel").pack(
                anchor="w", pady=(6, 0))
        self.entry = ttk.Entry(body, textvariable=self.var, show="•",
                               width=40)
        self.entry.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(body, text="Show the password", variable=self.show,
                        command=self._toggle).pack(anchor="w", pady=(4, 0))
        ttk.Label(body, text="The password is kept in memory only, while "
                  "this backup is open, so other notes locked with the same "
                  "password open without asking.", wraplength=420,
                  justify="left", style="Subtitle.TLabel").pack(
            anchor="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        self.ok_button = ttk.Button(buttons, text="Unlock", command=self._ok)
        self.ok_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        self.entry.focus_set()

    def _toggle(self):
        self.entry.configure(show="" if self.show.get() else "•")

    def _ok(self):
        if self.var.get():
            self.result = self.var.get()
            self.destroy()


def ask_password(parent, title, message, hint=""):
    """Show the dialog and wait. The password, or None if cancelled."""
    dialog = PasswordDialog(parent, title, message, hint)
    dialog.grab_set()
    dialog.wait_window()
    return dialog.result


class LockedNotesDialog(tk.Toplevel):
    """Before an export: some of the notes are locked.

    *notes* are the notes being exported. *try_password(password, done)* must
    try the password on them, in the background, and call ``done(opened,
    still_locked)`` (two lists of notes) on the window's thread. After the
    dialog closes, ``result`` is one of ``KEEP``, ``LEAVE``, ``ONLY``, or
    None if the export was cancelled.
    """

    def __init__(self, parent, notes, try_password):
        super().__init__(parent)
        self.title("Locked notes")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.notes = [n for n in notes if n.locked]
        self._try = try_password
        self._busy = False
        self._before = 0
        self.var = tk.StringVar()
        self.show = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar()
        self.message_var = tk.StringVar()
        self.choice = tk.StringVar(value=KEEP)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, textvariable=self.status_var, wraplength=480,
                  justify="left").pack(anchor="w")
        self.tree = ttk.Treeview(body, columns=("hint",), height=6,
                                 show=("tree", "headings"),
                                 selectmode="none")
        self.tree.heading("#0", text="Still locked")
        self.tree.heading("hint", text="Password hint")
        self.tree.column("#0", width=250)
        self.tree.column("hint", width=230)
        self.tree.pack(fill="x", pady=(8, 0))

        ttk.Label(body, text="Password to try on all of them:").pack(
            anchor="w", pady=(10, 0))
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.entry = ttk.Entry(row, textvariable=self.var, show="•",
                               width=34)
        self.entry.pack(side="left", fill="x", expand=True)
        self.try_button = ttk.Button(row, text="Try this password",
                                     command=self._try_clicked)
        self.try_button.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(body, text="Show the password", variable=self.show,
                        command=self._toggle).pack(anchor="w", pady=(4, 0))
        ttk.Label(body, textvariable=self.message_var, wraplength=480,
                  justify="left").pack(anchor="w", pady=(6, 0))

        ttk.Label(body, text="When you export:").pack(anchor="w",
                                                       pady=(10, 0))
        for key, label in CHOICES.items():
            ttk.Radiobutton(body, text=label, value=key,
                            variable=self.choice).pack(anchor="w", padx=14)
        ttk.Label(body, text="Exported notes are saved as ordinary files, "
                  "without a password.", wraplength=480, justify="left",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        self.ok_button = ttk.Button(buttons, text="Export", command=self._ok)
        self.ok_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._try_clicked())
        self.refresh()
        self.entry.focus_set()

    # -- what is shown ----------------------------------------

    def still_locked(self):
        return [n for n in self.notes if not n.unlocked]

    def refresh(self):
        total = len(self.notes)
        still = self.still_locked()
        self.status_var.set(
            f"{total:,} of the notes you are exporting "
            f"{'is' if total == 1 else 'are'} locked with a password. "
            f"{total - len(still):,} "
            f"{'is' if total - len(still) == 1 else 'are'} open"
            + (f", {len(still):,} still locked." if still else
               ": all of them."))
        self.tree.delete(*self.tree.get_children())
        for note in still:
            self.tree.insert("", "end", text=note.display_title,
                             values=(note.hint,))
        self.tree.configure(height=max(1, min(6, len(still))))

    def _toggle(self):
        self.entry.configure(show="" if self.show.get() else "•")

    # -- trying passwords -------------------------------------

    def _try_clicked(self):
        password = self.var.get()
        if not password or self._busy or not self.still_locked():
            return
        self._busy = True
        self._before = len(self.still_locked())
        self.try_button.state(["disabled"])
        self.message_var.set("Trying the password...")
        self._try(password, self._tried)

    def _tried(self, opened, still):
        self._busy = False
        if not self.winfo_exists():
            return
        self.try_button.state(["!disabled"])
        left = len(self.still_locked())
        now = self._before - left
        self.var.set("")
        if now:
            self.message_var.set(
                f"That password opened {now:,} "
                f"note{'' if now == 1 else 's'}."
                + (f" {left:,} still locked: try another password, or "
                   "choose below what to do with them." if left else
                   " All the notes are open."))
        else:
            self.message_var.set(
                "That password does not open any of the notes that are "
                "still locked. Try another, or choose below what to do "
                "with them.")
        self.refresh()
        self.entry.focus_set()

    def _ok(self):
        self.result = self.choice.get()
        self.destroy()
