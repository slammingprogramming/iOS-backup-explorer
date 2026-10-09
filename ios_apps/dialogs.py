# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the export dialog shared by the app views
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

"""A small "export as ..." dialog: pick a format, what to export, and where."""

import tkinter as tk
from tkinter import filedialog, ttk


class ExportDialog(tk.Toplevel):
    """Ask for a format, a scope and a folder. After the dialog closes,
    ``result`` is ``(format, scope, folder)`` or None if it was cancelled.

    *extra*, if given, adds one more question: ``{"title": ..., "options":
    {key: label}, "default": key}``. The answer is then a fourth item of
    ``result``."""

    def __init__(self, parent, title, formats, scopes, default_scope=None,
                 extra=None):
        super().__init__(parent)
        self.extra = extra
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.format_var = tk.StringVar(value=next(iter(formats)))
        self.scope_var = tk.StringVar(
            value=default_scope if default_scope in scopes
            else next(iter(scopes)))
        self.folder_var = tk.StringVar()
        self.extra_var = tk.StringVar(
            value=(extra.get("default") or next(iter(extra["options"])))
            if extra else "")

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Format").grid(row=0, column=0, sticky="w")
        for row, (key, label) in enumerate(formats.items(), 1):
            ttk.Radiobutton(body, text=label, value=key,
                            variable=self.format_var).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=14)
        row = len(formats) + 1
        ttk.Label(body, text="What to export").grid(
            row=row, column=0, sticky="w", pady=(10, 0))
        for offset, (key, label) in enumerate(scopes.items(), 1):
            ttk.Radiobutton(body, text=label, value=key,
                            variable=self.scope_var).grid(
                row=row + offset, column=0, columnspan=2, sticky="w",
                padx=14)
        row += len(scopes) + 1
        if extra:
            ttk.Label(body, text=extra["title"]).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
            for offset, (key, label) in enumerate(extra["options"].items(),
                                                  1):
                ttk.Radiobutton(body, text=label, value=key,
                                variable=self.extra_var).grid(
                    row=row + offset, column=0, columnspan=2, sticky="w",
                    padx=14)
            row += len(extra["options"]) + 1
        ttk.Label(body, text="Save into folder").grid(
            row=row, column=0, sticky="w", pady=(10, 0))
        self.folder_entry = ttk.Entry(body, textvariable=self.folder_var,
                                      width=46)
        self.folder_entry.grid(row=row + 1, column=0, sticky="we")
        ttk.Button(body, text="Browse...", command=self._browse).grid(
            row=row + 1, column=1, padx=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=row + 2, column=0, columnspan=2, sticky="e",
                     pady=(14, 0))
        self.ok_button = ttk.Button(buttons, text="Export", command=self._ok)
        self.ok_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())

    def _browse(self):
        folder = filedialog.askdirectory(parent=self,
                                         title="Choose the export folder")
        if folder:
            self.folder_var.set(folder)

    def _ok(self):
        folder = self.folder_var.get().strip()
        if not folder:
            self._browse()
            folder = self.folder_var.get().strip()
            if not folder:
                return
        self.result = (self.format_var.get(), self.scope_var.get(), folder)
        if self.extra:
            self.result += (self.extra_var.get(),)
        self.destroy()


class ChoiceDialog(tk.Toplevel):
    """Ask one question with a few answers. ``result`` is the key of the
    answer, or None if the dialog was cancelled."""

    def __init__(self, parent, title, question, options, default=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.var = tk.StringVar(
            value=default if default in options else next(iter(options)))
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=question, wraplength=420,
                  justify="left").pack(anchor="w")
        for key, label in options.items():
            ttk.Radiobutton(body, text=label, value=key,
                            variable=self.var).pack(anchor="w", padx=14,
                                                    pady=(4, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())

    def _ok(self):
        self.result = self.var.get()
        self.destroy()


def ask_choice(parent, title, question, options, default=None):
    """Show the question and wait. Returns the key of the answer, or None."""
    dialog = ChoiceDialog(parent, title, question, options, default)
    dialog.grab_set()
    dialog.wait_window()
    return dialog.result


def ask_export(parent, title, formats, scopes, default_scope=None,
               extra=None):
    """Show the dialog and wait. Returns ``(format, scope, folder)`` (and
    the answer to *extra*, if there is one) or None."""
    dialog = ExportDialog(parent, title, formats, scopes, default_scope,
                          extra)
    dialog.grab_set()
    dialog.wait_window()
    return dialog.result
