# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Contacts view
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

"""The Contacts tab: a list of people on the left, the contact's card on the
right. Contacts can be exported as a vCard file (which other address books
import), a spreadsheet, a web page, text or JSON, and the original database
can always be extracted untouched.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from . import contacts as ct
from . import contacts_export as cx
from .common import format_datetime
from .dialogs import ask_export
from .panel_base import AppPanel

SORTS = {"Last name": "last", "First name": "first"}
_MUTED = "#6b7280"


def _load(conn, _book, _index):
    """(runs on the database thread) -> the reader and the contacts."""
    reader = ct.ContactsReader(conn)
    return reader, reader.contacts()


class ContactsPanel(AppPanel):
    DATABASE = ct.DATABASE
    FOLDER = "contacts-view"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no address book."

    def __init__(self, master, context):
        super().__init__(master, context)
        self.contacts = []
        self.view = []
        self._rows = {}
        self.current = None
        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="Last name")
        self.title_var = tk.StringVar()
        self._build()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Search contacts:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=34).pack(
            side="left", padx=8)
        self.search_var.trace_add(
            "write", lambda *a: self.schedule("search", 300, self.refresh))
        ttk.Label(top, text="Sort by:").pack(side="left", padx=(12, 4))
        self.sort_box = ttk.Combobox(top, textvariable=self.sort_var,
                                     values=list(SORTS), state="readonly",
                                     width=12)
        self.sort_box.pack(side="left")
        self.sort_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(top, textvariable=self.state_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Export...", command=self.export).pack(
            side="left")
        ttk.Button(bottom, text="Extract original files...",
                   command=self.extract_originals).pack(side="right")

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.LabelFrame(paned, text="Contacts", padding=6)
        paned.add(left, weight=2)
        self.tree = ttk.Treeview(left, columns=("detail",),
                                 show=("tree", "headings"),
                                 selectmode="browse")
        self.tree.heading("#0", text="Name")
        self.tree.heading("detail", text="Company / number")
        self.tree.column("#0", width=210, minwidth=100)
        self.tree.column("detail", width=140, minwidth=70)
        scroll = ttk.Scrollbar(left, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.LabelFrame(paned, text="Card", padding=6)
        paned.add(right, weight=4)
        self.card = tk.Text(right, wrap="word", state="disabled",
                            cursor="arrow", borderwidth=0,
                            highlightthickness=0, padx=14, pady=10,
                            background="#ffffff", foreground="#1c1c1e")
        card_scroll = ttk.Scrollbar(right, orient="vertical",
                                    command=self.card.yview)
        self.card.configure(yscrollcommand=card_scroll.set)
        card_scroll.pack(side="right", fill="y")
        self.card.pack(side="left", fill="both", expand=True)
        base = tkfont.nametofont("TkDefaultFont").actual()
        family, size = base["family"], max(10, abs(base["size"]))
        self._fonts = [
            tkfont.Font(family=family, size=size + 8, weight="bold"),
            tkfont.Font(family=family, size=size - 1),
            tkfont.Font(family=family, size=size)]
        self.card.tag_configure("name", font=self._fonts[0], spacing3=2)
        self.card.tag_configure("sub", foreground=_MUTED, font=self._fonts[2],
                                spacing3=2)
        self.card.tag_configure("label", foreground=_MUTED,
                                font=self._fonts[1], spacing1=8)
        self.card.tag_configure("value", font=self._fonts[2], lmargin1=8,
                                lmargin2=8)

    # ── Loading and the list ─────────────────────────────────

    def on_loaded(self, contacts):
        self.contacts = contacts
        self.state_var.set(f"{len(contacts):,} contacts")
        self.refresh()

    def refresh(self):
        """Apply the search and the sort order, and redraw the list."""
        self.cancel_timer("search")
        by = SORTS[self.sort_var.get()]
        contacts = sorted(self.contacts, key=lambda c: c.sort_key(by))
        text = self.search_var.get().strip()
        if text:
            contacts = ct.search_contacts(contacts, text)
        self.view = contacts
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for contact in contacts:
            row = f"p{contact.pk}"
            self._rows[row] = contact
            detail = contact.organization if contact.organization \
                and contact.organization != contact.display_name else (
                    contact.phones[0][1] if contact.phones else "")
            self.tree.insert("", "end", iid=row, text=contact.display_name,
                             values=(detail,))
        if text:
            self.state_var.set(f"{len(contacts):,} of {len(self.contacts):,}"
                               " contacts")
        else:
            self.state_var.set(f"{len(self.contacts):,} contacts")
        if self.current is not None:
            row = f"p{self.current.pk}"
            if self.tree.exists(row):
                self.tree.selection_set(row)
                self.tree.see(row)

    # ── The card ─────────────────────────────────────────────

    def _on_select(self, event):
        selection = self.tree.selection()
        if selection and selection[0] in self._rows:
            self.show_contact(self._rows[selection[0]])

    def show_contact(self, contact):
        self.current = contact
        text = self.card
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("end", contact.display_name + "\n", "name")
        if contact.person_name and contact.person_name \
                != contact.display_name:
            text.insert("end", contact.person_name + "\n", "sub")
        full = " ".join(p for p in (contact.prefix, contact.first,
                                    contact.middle, contact.last,
                                    contact.suffix) if p)
        if full and full not in (contact.display_name, contact.person_name):
            text.insert("end", full + "\n", "sub")
        if contact.nickname and contact.nickname != contact.display_name:
            text.insert("end", f"“{contact.nickname}”\n", "sub")
        work = ", ".join(p for p in (contact.job_title, contact.organization,
                                     contact.department) if p)
        if work and work != contact.display_name:
            text.insert("end", work + "\n", "sub")
        sections = (
            [(label or "phone", number) for label, number in contact.phones],
            [(label or "email", value) for label, value in contact.emails],
            [(a.label or "address", "\n".join(a.lines))
             for a in contact.addresses],
            [(label or "web", value) for label, value in contact.urls],
            [(label or "related", value) for label, value in contact.related],
            [(label or "date", value) for label, value in contact.dates],
            [(service or "messaging", name)
             for service, name in contact.messaging],
            [("birthday", contact.birthday)] if contact.birthday else [],
            [("note", contact.note)] if contact.note else [])
        for section in sections:
            for label, value in section:
                text.insert("end", label + "\n", "label")
                text.insert("end", value + "\n", "value")
        stamps = [f"{word} {format_datetime(stamp)}" for word, stamp in
                  (("created", contact.created),
                   ("changed", contact.modified)) if stamp]
        if stamps:
            text.insert("end", "\n" + " · ".join(stamps) + "\n", "label")
        text.configure(state="disabled")
        text.yview_moveto(0)

    # ── Exporting ────────────────────────────────────────────

    def export(self):
        if not self.contacts:
            messagebox.showinfo("Info", "There are no contacts to export.")
            return
        scopes = {"all": f"All {len(self.contacts):,} contacts"}
        default = "all"
        if len(self.view) != len(self.contacts):
            scopes = {"view": f"The {len(self.view):,} contacts shown",
                      **scopes}
            default = "view"
        if self.current is not None:
            scopes = {"one": f"Only “{self.current.display_name}”", **scopes}
            default = "one"
        choice = ask_export(self, "Export contacts", cx.FORMATS, scopes,
                            default)
        if choice is None:
            return
        fmt, scope, folder = choice
        chosen = {"one": lambda: [self.current], "view": lambda: self.view,
                  "all": lambda: self.contacts}[scope]()
        self.export_to(chosen, fmt, folder)

    def export_to(self, contacts, fmt, folder):
        """Export *contacts* as *fmt* into *folder* (in the background)."""
        contacts = list(contacts)
        self.start_export(lambda reader: contacts,
                          lambda data, fetch: cx.export(data, fmt, folder),
                          folder)

    def extract_originals(self):
        """Extract the address book database exactly as the backup has it."""
        self.extract_originals_of([ct.DATABASE, ct.DATABASE + "-wal",
                                   ct.DATABASE + "-shm"])
