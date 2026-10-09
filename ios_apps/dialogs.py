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
    ``result`` is ``(format, scope, folder)`` or None if it was cancelled."""

    def __init__(self, parent, title, formats, scopes, default_scope=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.format_var = tk.StringVar(value=next(iter(formats)))
        self.scope_var = tk.StringVar(
            value=default_scope if default_scope in scopes
            else next(iter(scopes)))
        self.folder_var = tk.StringVar()

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
        self.destroy()


def ask_export(parent, title, formats, scopes, default_scope=None):
    """Show the dialog and wait. Returns ``(format, scope, folder)`` or
    None."""
    dialog = ExportDialog(parent, title, formats, scopes, default_scope)
    dialog.grab_set()
    dialog.wait_window()
    return dialog.result
