# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Calls view
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

"""The Calls tab: the call history as a table you can sort, filter and
search, with names from the address book. It can be exported (spreadsheet,
web page, text, JSON), and the original database can always be extracted.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from . import calls as cl
from . import calls_export as cx
from .common import format_datetime
from .dialogs import ask_export
from .export_util import describe_duration
from .panel_base import AppPanel

PAGE = 2000
"""How many rows are drawn at once; more load on request."""

HEADINGS = {"when": "Date", "who": "Who", "number": "Number",
            "direction": "Direction", "kind": "Type", "duration": "Duration",
            "place": "Place"}
SORT_KEYS = {
    "when": lambda c: c.when or 0,
    "who": lambda c: c.display_name.casefold(),
    "number": lambda c: c.address,
    "direction": lambda c: c.direction_label,
    "kind": lambda c: c.kind_label,
    "duration": lambda c: c.duration,
    "place": lambda c: c.location.casefold(),
}
FILTERS = {
    "All calls": {},
    "Missed": {"direction": cl.MISSED},
    "Incoming": {"direction": cl.INCOMING},
    "Outgoing": {"direction": cl.OUTGOING},
    "Phone calls": {"kind": "phone"},
    "FaceTime": {"kind": "facetime"},
}


def _load(conn, book, _index):
    """(runs on the database thread) -> the reader and the calls."""
    reader = cl.CallsReader(conn, book)
    return reader, reader.calls()


class CallsPanel(AppPanel):
    DATABASE = cl.DATABASE
    FOLDER = "calls"
    WITH_CONTACTS = True
    LOADER = staticmethod(_load)
    MISSING = "This backup has no call history."

    def __init__(self, master, context):
        super().__init__(master, context)
        self.calls = []
        self.view = []                   # filtered, searched and sorted
        self._shown = 0
        self._rows = {}                  # tree row -> Call
        self._sort_key, self._sort_desc = "when", True
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="All calls")
        self.summary_var = tk.StringVar()
        self._build()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Search calls:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=34).pack(
            side="left", padx=8)
        self.search_var.trace_add(
            "write", lambda *a: self.schedule("search", 300, self.refresh))
        ttk.Label(top, text="Show:").pack(side="left", padx=(12, 4))
        self.filter_box = ttk.Combobox(top, textvariable=self.filter_var,
                                       values=list(FILTERS), state="readonly",
                                       width=14)
        self.filter_box.pack(side="left")
        self.filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(top, textvariable=self.state_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Export...", command=self.export).pack(
            side="left")
        ttk.Label(bottom, textvariable=self.summary_var,
                  style="Subtitle.TLabel").pack(side="left", padx=12)
        ttk.Button(bottom, text="Extract original files...",
                   command=self.extract_originals).pack(side="right")
        self.more_btn = ttk.Button(bottom, text="", command=self._show_more)

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        columns = list(HEADINGS)[1:]
        self.tree = ttk.Treeview(frame, columns=columns,
                                 show=("tree", "headings"),
                                 selectmode="extended")
        widths = {"when": 130, "who": 200, "number": 140, "direction": 90,
                  "kind": 100, "duration": 80, "place": 160}
        # the first heading (the date) lives in the tree column
        self.tree.column("#0", width=widths["when"], minwidth=90,
                         stretch=False)
        for column in columns:
            self.tree.column(column, width=widths[column], minwidth=60,
                             anchor="e" if column == "duration" else "w")
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("missed", foreground="#c0392b")
        self._update_headings()

    def _update_headings(self):
        for column, label in HEADINGS.items():
            if column == self._sort_key:
                label += " ▼" if self._sort_desc else " ▲"
            command = lambda c=column: self.sort_by(c)
            if column == "when":
                self.tree.heading("#0", text=label, command=command)
            else:
                self.tree.heading(column, text=label, command=command)

    def sort_by(self, key):
        """Sort by *key*; choosing the same column again reverses it."""
        if key == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, key == "when"
        self._update_headings()
        self.refresh()

    # ── Loading and showing ──────────────────────────────────

    def on_loaded(self, calls):
        self.calls = calls
        self.state_var.set(f"{len(calls):,} calls")
        self.refresh()

    def refresh(self):
        """Apply the filter, the search and the sort, and redraw."""
        self.cancel_timer("search")
        calls = cl.filter_calls(self.calls, **FILTERS[self.filter_var.get()])
        text = self.search_var.get().strip()
        if text:
            calls = cl.search_calls(calls, text)
        calls = sorted(calls, key=SORT_KEYS[self._sort_key],
                       reverse=self._sort_desc)
        self.view = calls
        self._shown = 0
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        self._show_more()
        totals = cl.summarize(calls)
        self.summary_var.set(
            f"{totals['total']:,} calls · {totals['missed']:,} missed · "
            f"{describe_duration(totals['talk_seconds']) or '0:00'} talk time")

    def _show_more(self):
        end = min(len(self.view), self._shown + PAGE)
        for call in self.view[self._shown:end]:
            row = f"c{call.rowid}"
            self._rows[row] = call
            self.tree.insert(
                "", "end", iid=row, text=format_datetime(call.when),
                tags=("missed",) if call.direction == cl.MISSED else (),
                values=(call.display_name, call.address,
                        call.direction_label, call.kind_label,
                        describe_duration(call.duration) if call.duration
                        else "", call.location))
        self._shown = end
        left = len(self.view) - end
        if left > 0:
            self.more_btn.configure(
                text=f"Show {min(PAGE, left):,} more ({left:,} not shown)")
            self.more_btn.pack(side="left", padx=8)
        else:
            self.more_btn.pack_forget()

    # ── Exporting ────────────────────────────────────────────

    def export(self):
        if not self.calls:
            messagebox.showinfo("Info", "There are no calls to export.")
            return
        scopes = {"all": f"All {len(self.calls):,} calls"}
        default = "all"
        if len(self.view) != len(self.calls):
            scopes = {"view": f"The {len(self.view):,} calls shown",
                      **scopes}
            default = "view"
        choice = ask_export(self, "Export calls", cx.FORMATS, scopes, default)
        if choice is None:
            return
        fmt, scope, folder = choice
        self.export_to(self.view if scope == "view" else self.calls, fmt,
                       folder)

    def export_to(self, calls, fmt, folder):
        """Export *calls* as *fmt* into *folder* (in the background)."""
        calls = list(calls)
        self.start_export(lambda reader: calls,
                          lambda data, fetch: cx.export(data, fmt, folder),
                          folder)

    def extract_originals(self):
        """Extract the call history database exactly as the backup has it."""
        self.extract_originals_of([cl.DATABASE, cl.DATABASE + "-wal",
                                   cl.DATABASE + "-shm"])
