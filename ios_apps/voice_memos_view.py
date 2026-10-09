# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Voice Memos view
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

"""The Voice Memos tab: the recordings as a list you can sort and search.

A recording opens in the program the computer plays audio with. Recordings
can be saved, exported (audio files named by date and title, a web page with
a player for each, a list) and extracted exactly as the backup holds them.
"""

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from . import voice_memos as vm
from . import voice_memos_export as vx
from .common import format_datetime
from .dialogs import ask_export
from .export_util import describe_duration, describe_size
from .panel_base import AppPanel

HEADINGS = {"title": "Title", "when": "Date", "length": "Length",
            "size": "Size"}
SORT_KEYS = {
    "title": lambda m: m.display_title.casefold(),
    "when": lambda m: m.when or 0,
    "length": lambda m: m.duration or 0,
    "size": lambda m: m.size,
}


def _load(conn, _book, index):
    """(runs on the database thread) -> no reader, and ``(memos, note)``."""
    memos = vm.scan(index)
    note = ""
    try:
        vm.enrich(memos, conn)
    except sqlite3.Error as exc:
        note = f"The recordings database could not be read ({exc}); " \
               "showing the files only."
    return None, (memos, note)


class VoiceMemosPanel(AppPanel):
    FOLDER = "voice-memos"
    OPTIONAL = True
    LOADER = staticmethod(_load)
    MISSING = "This backup has no voice recordings."

    def __init__(self, master, context):
        super().__init__(master, context)
        self.memos = []
        self._note = ""                  # what went wrong reading the database
        self.view = []
        self._rows = {}
        self._sort_key, self._sort_desc = "when", True
        self.search_var = tk.StringVar()
        self.info_var = tk.StringVar()
        self._build()

    # ── Loading ──────────────────────────────────────────────

    def database_path(self):
        index = self.ctx.index
        return vm.find_database(index) if index is not None else None

    def load_without_database(self, note=""):
        return vm.scan(self.ctx.index), note

    def on_loaded(self, data):
        self.memos, self._note = data
        self.refresh()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Search recordings:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=34).pack(
            side="left", padx=8)
        self.search_var.trace_add(
            "write", lambda *a: self.schedule("search", 300, self.refresh))
        ttk.Label(top, textvariable=self.state_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Play", command=self.play_selected).pack(
            side="left")
        ttk.Button(bottom, text="Save as...", command=self.save_selected).pack(
            side="left", padx=6)
        ttk.Button(bottom, text="Export...", command=self.export).pack(
            side="left")
        ttk.Label(bottom, textvariable=self.info_var,
                  style="Subtitle.TLabel").pack(side="left", padx=12)
        ttk.Button(bottom, text="Extract original files...",
                   command=self.extract_originals).pack(side="right")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("when", "length", "size"),
                                 show=("tree", "headings"),
                                 selectmode="extended")
        self.tree.column("#0", width=320, minwidth=120)
        self.tree.column("when", width=140, minwidth=80)
        self.tree.column("length", width=80, minwidth=60, anchor="e")
        self.tree.column("size", width=90, minwidth=60, anchor="e")
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._describe())
        self.tree.bind("<Double-1>", lambda e: self.play_selected())
        self.tree.bind("<Return>", lambda e: self.play_selected())
        self._update_headings()

    def _update_headings(self):
        for key, label in HEADINGS.items():
            if key == self._sort_key:
                label += " ▼" if self._sort_desc else " ▲"
            command = lambda k=key: self.sort_by(k)
            if key == "title":
                self.tree.heading("#0", text=label, command=command)
            else:
                self.tree.heading(key, text=label, command=command)

    def sort_by(self, key):
        """Sort by *key*; choosing the same column again reverses it."""
        if key == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, key != "title"
        self._update_headings()
        self.refresh()

    def refresh(self):
        self.cancel_timer("search")
        memos = self.memos
        text = self.search_var.get().strip()
        if text:
            memos = vm.search_memos(memos, text)
        self.view = sorted(memos, key=SORT_KEYS[self._sort_key],
                           reverse=self._sort_desc)
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for memo in self.view:
            row = f"m{len(self._rows)}"
            self._rows[row] = memo
            self.tree.insert("", "end", iid=row, text=memo.display_title,
                             values=(format_datetime(memo.when),
                                     describe_duration(memo.duration),
                                     describe_size(memo.size)))
        self.state_var.set(
            self._note or (f"{len(self.view):,} of {len(self.memos):,} "
                           "recordings" if text
                           else f"{len(self.memos):,} recordings"))
        self._describe()

    def selected_memos(self):
        return [self._rows[r] for r in self.tree.selection()
                if r in self._rows]

    def _describe(self):
        chosen = self.selected_memos()
        if len(chosen) == 1:
            memo = chosen[0]
            self.info_var.set(f"{memo.name} · "
                              + describe_size(memo.size))
        elif chosen:
            self.info_var.set(f"{len(chosen):,} selected")
        else:
            self.info_var.set("")

    # ── Playing and saving ───────────────────────────────────

    def _single(self, what):
        chosen = self.selected_memos()
        if len(chosen) != 1:
            messagebox.showinfo("Info", f"Choose one recording to {what}.")
            return None
        return chosen[0]

    def play_selected(self):
        memo = self._single("play")
        if memo is not None:
            self.open_backup_file(memo.path)

    def save_selected(self):
        memo = self._single("save")
        if memo is not None:
            self.save_backup_file(memo.path, vx.friendly_name(memo))

    # ── Exporting ────────────────────────────────────────────

    def export(self):
        if not self.memos:
            messagebox.showinfo("Info", "There are no recordings to export.")
            return
        scopes = {"all": f"All {len(self.memos):,} recordings"}
        default = "all"
        if len(self.view) != len(self.memos):
            scopes = {"view": f"The {len(self.view):,} shown", **scopes}
            default = "view"
        if self.selected_memos():
            scopes = {"selected":
                      f"The {len(self.selected_memos()):,} selected",
                      **scopes}
            default = "selected"
        choice = ask_export(self, "Export voice memos", vx.FORMATS, scopes,
                            default)
        if choice is None:
            return
        fmt, scope, folder = choice
        chosen = {"selected": self.selected_memos, "view": lambda: self.view,
                  "all": lambda: self.memos}[scope]()
        self.export_to(chosen, fmt, folder)

    def export_to(self, memos, fmt, folder):
        """Export *memos* as *fmt* into *folder* (in the background)."""
        memos = list(memos)
        copy_file = self.ctx.copier()
        self.start_export(
            lambda reader: memos,
            lambda data, fetch: vx.export(data, fmt, folder, copy_file),
            folder)

    def extract_originals(self):
        """Extract the recordings (and their database) exactly as the backup
        holds them, with the normal extraction."""
        chosen = self.selected_memos() or self.view
        paths = [m.path for m in chosen]
        database = self.database_path()
        if database:
            paths += [database, database + "-wal", database + "-shm"]
        if not paths:
            messagebox.showinfo("Info", "There is nothing to extract.")
            return
        self.extract_originals_of(paths)
