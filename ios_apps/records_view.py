# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — one panel for any table of records
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

"""A tab that shows one or more :class:`records.Dataset` tables: click a
heading to sort, type to search, choose which table to show, read the
details of the selected row, export what is shown, or extract the original
files. A concrete tab (Safari, Calendar, ...) only names its databases and
supplies a loader that returns the datasets.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from . import records_export as rx
from .dialogs import ask_export
from .panel_base import AppPanel

PAGE = 2000
"""How many rows are drawn at once; more load on request."""


class RecordsPanel(AppPanel):
    LOADER = None                # staticmethod: -> (reader, [Dataset])
    ORIGINALS = ()               # backup paths extracted untouched

    def __init__(self, master, context):
        super().__init__(master, context)
        self.datasets = {}
        self.dataset = None
        self.rows = []               # after the search and the sort
        self._shown = 0
        self._items = {}             # tree row -> row dict
        self._sort_key, self._sort_desc = None, False
        self.search_var = tk.StringVar()
        self.dataset_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self._action_buttons = []
        self._build()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        self.show_label = ttk.Label(top, text="Show:")
        self.dataset_box = ttk.Combobox(top, textvariable=self.dataset_var,
                                        state="readonly", width=24)
        self.dataset_box.bind("<<ComboboxSelected>>",
                              lambda e: self.choose_dataset())
        ttk.Label(top, text="Search:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=34).pack(
            side="left", padx=8)
        self.search_var.trace_add(
            "write", lambda *a: self.schedule("search", 300, self.refresh))
        self._top = top
        ttk.Label(top, textvariable=self.state_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        self.actions_frame = ttk.Frame(bottom)
        self.actions_frame.pack(side="left")
        ttk.Button(bottom, text="Export...", command=self.export).pack(
            side="left", padx=(0, 6))
        ttk.Label(bottom, textvariable=self.summary_var,
                  style="Subtitle.TLabel").pack(side="left", padx=6)
        ttk.Button(bottom, text="Extract original files...",
                   command=self.extract_originals).pack(side="right")
        self.more_btn = ttk.Button(bottom, text="", command=self._show_more)

        ttk.Label(self, textvariable=self.note_var, style="Subtitle.TLabel",
                  wraplength=900).pack(side="bottom", anchor="w")
        self.detail = tk.Text(self, height=5, wrap="word", state="disabled",
                              borderwidth=1, relief="solid",
                              highlightthickness=0, padx=8, pady=4)
        self._detail_shown = False

        self.frame = ttk.Frame(self)
        self.frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(self.frame, show="headings",
                                 selectmode="extended")
        scroll = ttk.Scrollbar(self.frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", lambda e: self._on_double())

    # ── Loading ──────────────────────────────────────────────

    def on_loaded(self, datasets):
        self.datasets = {d.key: d for d in datasets}
        keys = list(self.datasets)
        if not keys:
            self.state_var.set("Nothing was found here.")
            return
        if len(keys) > 1:
            self.show_label.pack(side="left", padx=(12, 4))
            self.dataset_box.pack(side="left")
        self.dataset_box.configure(values=[d.title for d in datasets])
        self.dataset_var.set(datasets[0].title)
        self.choose_dataset()

    def choose_dataset(self, key=None):
        """Show the table called *key* (or the one chosen in the list)."""
        if key is None:
            title = self.dataset_var.get()
            key = next((k for k, d in self.datasets.items()
                        if d.title == title), next(iter(self.datasets)))
        dataset = self.datasets[key]
        self.dataset = dataset
        self.dataset_var.set(dataset.title)
        self._sort_key = dataset.sort[0] if dataset.sort else None
        self._sort_desc = bool(dataset.sort and dataset.sort[1])
        columns = [c.key for c in dataset.columns]
        self.tree.configure(columns=columns)
        for column in dataset.columns:
            self.tree.column(column.key, width=column.width, minwidth=50,
                             anchor=column.anchor,
                             stretch=column is dataset.columns[-1])
        self._update_headings()
        self.note_var.set(dataset.note)
        self._rebuild_actions()
        if dataset.details is not None:
            if not self._detail_shown:
                self.detail.pack(side="bottom", fill="x", pady=(6, 0),
                                 before=self.frame)
                self._detail_shown = True
        elif self._detail_shown:
            self.detail.pack_forget()
            self._detail_shown = False
        self.refresh()

    def _rebuild_actions(self):
        for button in self._action_buttons:
            button.destroy()
        self._action_buttons = []
        for label, name in self.dataset.actions:
            button = ttk.Button(self.actions_frame, text=label,
                                command=lambda n=name: self.run_action(n))
            button.pack(side="left", padx=(0, 6))
            self._action_buttons.append(button)

    def _update_headings(self):
        for column in self.dataset.columns:
            label = column.heading
            if column.key == self._sort_key:
                label += " ▼" if self._sort_desc else " ▲"
            self.tree.heading(
                column.key, text=label,
                command=lambda k=column.key: self.sort_by(k))

    def sort_by(self, key):
        """Sort by column *key*; choosing it again reverses the order."""
        if key == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key = key
            kind = next(c.kind for c in self.dataset.columns
                        if c.key == key)
            self._sort_desc = kind in ("date", "number", "size", "duration")
        self._update_headings()
        self.refresh()

    # ── Showing the rows ─────────────────────────────────────

    def refresh(self):
        """Search and sort the table, and draw it again."""
        self.cancel_timer("search")
        if self.dataset is None:
            return
        rows = self.dataset.search(self.dataset.rows,
                                   self.search_var.get().strip())
        self.rows = self.dataset.sorted_rows(rows, self._sort_key,
                                             self._sort_desc)
        self._shown = 0
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        self._show_more()
        total = len(self.dataset.rows)
        self.state_var.set(f"{len(self.rows):,} of {total:,}"
                           if len(self.rows) != total else f"{total:,} rows")
        self.summary_var.set("")
        self._describe([])

    def _show_more(self):
        columns = self.dataset.columns
        end = min(len(self.rows), self._shown + PAGE)
        for row in self.rows[self._shown:end]:
            item = f"r{len(self._items)}"
            self._items[item] = row
            self.tree.insert("", "end", iid=item, values=[
                c.show(row.get(c.key), row) for c in columns])
        self._shown = end
        left = len(self.rows) - end
        if left > 0:
            self.more_btn.configure(
                text=f"Show {min(PAGE, left):,} more ({left:,} not shown)")
            self.more_btn.pack(side="left", padx=8)
        else:
            self.more_btn.pack_forget()

    def selected_rows(self):
        return [self._items[i] for i in self.tree.selection()
                if i in self._items]

    def _on_select(self):
        self._describe(self.selected_rows())

    def _describe(self, chosen):
        if not self._detail_shown:
            return
        text = ""
        if len(chosen) == 1:
            text = self.dataset.details(chosen[0]) or ""
        elif chosen:
            text = f"{len(chosen):,} selected"
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", text)
        self.detail.configure(state="disabled")

    def _on_double(self):
        """Double-click does the table's first action, if it has one."""
        if self.dataset.actions and self.selected_rows():
            self.run_action(self.dataset.actions[0][1])

    def run_action(self, name):
        """Do the action *name* (``action_<name>`` of the tab) on the
        selected row."""
        chosen = self.selected_rows()
        if len(chosen) != 1:
            messagebox.showinfo("Info", "Choose one row first.")
            return
        getattr(self, f"action_{name}")(chosen[0])

    # ── Exporting ────────────────────────────────────────────

    def export(self):
        dataset = self.dataset
        if dataset is None or not dataset.rows:
            messagebox.showinfo("Info", "There is nothing to export.")
            return
        scopes = {"all": f"All {len(dataset.rows):,} rows"}
        default = "all"
        if len(self.rows) != len(dataset.rows):
            scopes = {"view": f"The {len(self.rows):,} rows shown", **scopes}
            default = "view"
        if self.selected_rows():
            scopes = {"selected":
                      f"The {len(self.selected_rows()):,} selected", **scopes}
            default = "selected"
        choice = ask_export(self, f"Export {dataset.title}",
                            rx.formats_for(dataset), scopes, default)
        if choice is None:
            return
        fmt, scope, folder = choice
        chosen = {"selected": self.selected_rows, "view": lambda: self.rows,
                  "all": lambda: dataset.rows}[scope]()
        self.export_to(chosen, fmt, folder)

    def export_to(self, rows, fmt, folder):
        """Export *rows* of the table shown, as *fmt*, in the background."""
        dataset, rows = self.dataset, list(rows)
        copy_file = self.ctx.copier()
        self.start_export(
            lambda reader: rows,
            lambda data, fetch: rx.export(dataset, data, fmt, folder,
                                          copy_file),
            folder)

    def extract_originals(self):
        """Extract the databases and files exactly as the backup has them."""
        paths = []
        for path in self.ORIGINALS:
            paths += [path, path + "-wal", path + "-shm"]
        paths += self.extra_originals()
        self.extract_originals_of(paths)

    def extra_originals(self):
        """More files to extract with the databases (for the tab to say)."""
        return []
