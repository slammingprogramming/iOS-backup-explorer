# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Notes view
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

"""The Notes tab: folders and notes on the left, the note on the right.

Notes show with their headings, lists, checklists, bold and italic text,
links and pictures. Voice recordings and other attachments can be opened or
saved. Notes can be exported (text, Markdown, web page, PDF, JSON,
spreadsheet), and the original database and attachments can always be
extracted untouched.
"""

import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import messagebox, ttk

from ui_util import post_when_done

from . import imaging
from . import notes as nt
from . import notes_export as nx
from .common import format_datetime
from .dialogs import ask_export
from .panel_base import AppPanel

SORTS = {"Date edited": lambda n: n.modified or 0,
         "Date created": lambda n: n.created or 0,
         "Title": lambda n: n.display_title.casefold()}
PICTURE_BOX = (420, 320)
_MUTED = "#6b7280"
_LINK = "#0b5ac8"


def _load(conn, _book, index):
    """(runs on the database thread) -> the reader and the first data."""
    reader = nt.NotesReader(conn, nt.media_resolver(index))
    notes = reader.notes()
    return reader, (notes, reader.folders())


class NotesPanel(AppPanel):
    DATABASE = nt.DATABASE
    FOLDER = "notes"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no Notes database."

    def __init__(self, master, context):
        super().__init__(master, context)
        self.notes = []
        self.folders = {}
        self._items = {}                 # tree row -> ("note"|"folder", obj)
        self.current = None
        self.rendered = None             # the note now on screen
        self._request = 0
        self._photos = []                # keep Tk pictures alive
        self._fonts = {}
        self._pictures = {}              # attachment tag -> attachment
        self._url_tags = 0
        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="Date edited")
        self.title_var = tk.StringVar()
        self.info_var = tk.StringVar()
        self._build()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Search notes:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=34).pack(
            side="left", padx=8)
        self.search_var.trace_add(
            "write", lambda *a: self.schedule("search", 350, self._search))
        ttk.Label(top, text="Sort by:").pack(side="left", padx=(12, 4))
        self.sort_box = ttk.Combobox(top, textvariable=self.sort_var,
                                     values=list(SORTS), state="readonly",
                                     width=14)
        self.sort_box.pack(side="left")
        self.sort_box.bind("<<ComboboxSelected>>",
                           lambda e: self._show_tree())
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
        left = ttk.LabelFrame(paned, text="Folders and notes", padding=6)
        paned.add(left, weight=2)
        self.tree = ttk.Treeview(left, columns=("when",),
                                 show=("tree", "headings"),
                                 selectmode="browse")
        self.tree.heading("#0", text="Note")
        self.tree.heading("when", text="Edited")
        self.tree.column("#0", width=230, minwidth=100)
        self.tree.column("when", width=110, minwidth=70)
        scroll = ttk.Scrollbar(left, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.LabelFrame(paned, text="Note", padding=6)
        paned.add(right, weight=5)
        header = ttk.Frame(right)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.title_var,
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, textvariable=self.info_var,
                  style="Subtitle.TLabel").pack(anchor="w")
        self.body = tk.Text(right, wrap="word", state="disabled",
                            cursor="arrow", borderwidth=0,
                            highlightthickness=0, padx=12, pady=8,
                            background="#ffffff", foreground="#1c1c1e")
        body_scroll = ttk.Scrollbar(right, orient="vertical",
                                    command=self.body.yview)
        self.body.configure(yscrollcommand=body_scroll.set)
        body_scroll.pack(side="right", fill="y")
        self.body.pack(side="left", fill="both", expand=True)
        self._configure_tags()

    def _configure_tags(self):
        text = self.body
        base = tkfont.nametofont("TkDefaultFont").actual()
        self._family = base["family"]
        self._size = max(10, abs(base["size"]))
        self._fixed = tkfont.nametofont("TkFixedFont").actual()["family"]
        text.tag_configure("notice", foreground=_MUTED,
                           font=self._font(self._size, False, True))
        text.tag_configure("underline", underline=True)
        text.tag_configure("strike", overstrike=True)
        text.tag_configure("link", foreground=_LINK, underline=True)
        text.tag_configure("chip", background="#eef0f3")
        text.tag_configure("attachment", foreground=_LINK, underline=True,
                           background="#eef0f3")
        text.tag_configure("prefix", foreground=_MUTED)

    def _font(self, size, bold=False, italic=False, mono=False):
        key = (size, bold, italic, mono)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(
                family=self._fixed if mono else self._family, size=size,
                weight="bold" if bold else "normal",
                slant="italic" if italic else "roman")
        return self._fonts[key]

    def _font_tag(self, style, bold, italic):
        size = {nt.TITLE: self._size + 7, nt.HEADING: self._size + 4,
                nt.SUBHEADING: self._size + 2}.get(style, self._size)
        bold = bold or style in (nt.TITLE, nt.HEADING, nt.SUBHEADING)
        mono = style == nt.MONOSPACED
        name = f"font{size}{int(bold)}{int(italic)}{int(mono)}"
        self.body.tag_configure(name, font=self._font(size, bold, italic, mono))
        return name

    def _indent_tag(self, indent, listed):
        name = f"indent{indent}{int(listed)}"
        left = 4 + indent * 24 + (18 if listed else 0)
        self.body.tag_configure(name, lmargin1=left - (18 if listed else 0),
                                lmargin2=left, spacing1=2, spacing3=2,
                                tabs=(left,))
        return name

    # ── Loading and the tree ─────────────────────────────────

    def on_loaded(self, data):
        self.notes, folder_list = data
        self.folders = {f.pk: f for f in folder_list}
        self._show_tree()
        shown = [n for n in self.notes if not n.deleted]
        self.state_var.set(f"{len(shown):,} notes in "
                           f"{len(folder_list):,} folders")

    def _sorted(self, notes):
        key = SORTS[self.sort_var.get()]
        newest_first = self.sort_var.get() != "Title"
        notes = sorted(notes, key=key, reverse=newest_first)
        return sorted(notes, key=lambda n: not n.pinned)      # pinned first

    def _folder_children(self):
        children, roots = {}, []
        for folder in self.folders.values():
            if folder.parent in self.folders:
                children.setdefault(folder.parent, []).append(folder)
            else:
                roots.append(folder)
        return children, roots

    def _count_in(self, folder, children, by_folder):
        total = len(by_folder.get(folder.pk, ()))
        return total + sum(self._count_in(sub, children, by_folder)
                           for sub in children.get(folder.pk, ()))

    def _show_tree(self):
        tree = self.tree
        tree.delete(*tree.get_children())
        self._items.clear()
        by_folder = {}
        for note in self._sorted(self.notes):
            by_folder.setdefault(note.folder, []).append(note)
        children, roots = self._folder_children()
        accounts = {f.account for f in roots if f.account}
        roots.sort(key=lambda f: (f.is_trash, f.title.casefold()))

        def add_folder(parent_row, folder):
            row = f"f{folder.pk}"
            count = self._count_in(folder, children, by_folder)
            tree.insert(parent_row, "end", iid=row, open=not folder.is_trash,
                        text=f"{folder.title}  ({count:,})")
            self._items[row] = ("folder", folder)
            for sub in sorted(children.get(folder.pk, ()),
                              key=lambda f: f.title.casefold()):
                add_folder(row, sub)
            for note in by_folder.get(folder.pk, ()):
                self._add_note_row(row, note)

        account_rows = {}
        for folder in roots:
            parent = ""
            if len(accounts) > 1:
                name = folder.account or "On My iPhone"
                if name not in account_rows:
                    account_rows[name] = tree.insert(
                        "", "end", text=name, open=True)
                parent = account_rows[name]
            add_folder(parent, folder)
        loose = [n for n in self._sorted(self.notes)
                 if n.folder not in self.folders]
        for note in loose:
            self._add_note_row("", note)

    def _add_note_row(self, parent, note, show_folder=False):
        row = f"n{note.pk}"
        title = note.display_title
        if show_folder:
            folder = self.folders.get(note.folder)
            title += f"  — {folder.title}" if folder else ""
        self.tree.insert(parent, "end", iid=row, text=title,
                         values=(format_datetime(note.modified),))
        self._items[row] = ("note", note)

    # ── Showing a note ───────────────────────────────────────

    def _on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        kind, item = self._items.get(selection[0], (None, None))
        if kind == "note":
            self.select_note(item)

    def select_note(self, note):
        self._request += 1
        self.current = note
        self.title_var.set(note.display_title)
        self.info_var.set(self._describe(note))
        self.run_query(lambda reader: reader.load(note), self._note_loaded,
                       self._request)

    def _describe(self, note):
        folder = self.folders.get(note.folder)
        bits = [folder.title] if folder else []
        if note.modified:
            bits.append("edited " + format_datetime(note.modified))
        if note.created:
            bits.append("created " + format_datetime(note.created))
        if note.deleted:
            bits.append("recently deleted")
        if note.locked:
            bits.append("locked")
        return " · ".join(bits)

    def _note_loaded(self, done, request):
        if request != self._request:
            return
        error = done.exception()
        if error is not None:
            self.fail("Could not read the note", error)
            return
        note = done.result()
        self.title_var.set(note.display_title)
        row = f"n{note.pk}"
        if self.tree.exists(row) and not self.search_var.get().strip():
            self.tree.item(row, text=note.display_title)
        self._render(note)
        self._load_pictures(note, request)

    def _render(self, note):
        text = self.body
        self.rendered = note
        text.configure(state="normal")
        text.delete("1.0", "end")
        self._photos.clear()
        self._pictures.clear()
        for mark in text.mark_names():
            if mark.startswith(("ats", "ate")):
                text.mark_unset(mark)
        if note.error:
            text.insert("end", note.error + "\n\n", "notice")
        for paragraph in note.paragraphs:
            self._insert_paragraph(text, paragraph, note)
        text.configure(state="disabled")
        text.yview_moveto(0)

    def _insert_paragraph(self, text, paragraph, note):
        style = paragraph.style
        listed = style in nt.LIST_STYLES
        tags = [self._indent_tag(paragraph.indent, listed)]
        if listed:
            marker = {nt.BULLET: "•", nt.DASH: "–",
                      nt.NUMBERED: f"{paragraph.number}.",
                      nt.CHECKBOX: "[x]" if paragraph.checked else "[ ]"}[style]
            text.insert("end", marker + "\t", tuple(tags) + ("prefix",))
        if not paragraph.spans:
            text.insert("end", "\n", tuple(tags))
            return
        for span in paragraph.spans:
            if span.attachment:
                self._insert_attachment(
                    text, note.attachments.get(span.attachment), tags)
                continue
            span_tags = tags + [self._font_tag(style, span.bold, span.italic)]
            if span.underline:
                span_tags.append("underline")
            if span.strike or (style == nt.CHECKBOX and paragraph.checked):
                span_tags.append("strike")
            if span.link:
                span_tags.append(self._link_tag(span.link))
            text.insert("end", span.text, tuple(span_tags))
        text.insert("end", "\n", tuple(tags))

    def _link_tag(self, url):
        self._url_tags += 1
        name = f"url{self._url_tags}"
        self.body.tag_configure(name, foreground=_LINK, underline=True)
        if url.strip().lower().startswith(("http://", "https://",
                                           "mailto:", "tel:")):
            self.body.tag_bind(name, "<Button-1>",
                               lambda e, u=url: webbrowser.open(u))
            self.body.tag_bind(name, "<Enter>", lambda e: self.body.configure(
                cursor="hand2"))
            self.body.tag_bind(name, "<Leave>", lambda e: self.body.configure(
                cursor="arrow"))
        return name

    def _insert_attachment(self, text, attachment, tags):
        if attachment is None:
            text.insert("end", "[attachment]", tuple(tags) + ("chip",))
            return
        if attachment.kind == "inline":
            text.insert("end", attachment.label, tuple(tags) + ("chip",))
            return
        if attachment.kind == "url":
            label = attachment.title or attachment.url or "link"
            text.insert("end", label, tuple(tags) + (
                self._link_tag(attachment.url),))
            return
        number = len(self._pictures)
        tag = f"att{number}"
        self._pictures[tag] = attachment
        text.mark_set(f"ats{number}", "end-1c")
        text.mark_gravity(f"ats{number}", "left")
        text.insert("end", f"[{attachment.label}]",
                    tuple(tags) + ("attachment", tag))
        text.mark_set(f"ate{number}", "end-1c")
        text.mark_gravity(f"ate{number}", "right")
        text.tag_bind(tag, "<Button-1>",
                      lambda e, a=attachment: self._attachment_menu(e, a))
        text.tag_bind(tag, "<Enter>",
                      lambda e: text.configure(cursor="hand2"))
        text.tag_bind(tag, "<Leave>",
                      lambda e: text.configure(cursor="arrow"))

    def _attachment_menu(self, event, attachment):
        menu = tk.Menu(self, tearoff=False)
        has_file = bool(attachment.path)
        state = "normal" if has_file else "disabled"
        menu.add_command(label="Open", state=state,
                         command=lambda: self.open_backup_file(attachment.path))
        menu.add_command(
            label="Save as...", state=state,
            command=lambda: self.save_backup_file(
                attachment.path, attachment.name or "attachment"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── Pictures inside notes ────────────────────────────────

    def _load_pictures(self, note, request):
        wanted = {tag: a for tag, a in self._pictures.items()
                  if a.kind == "image" and a.path
                  and imaging.can_show(a.name or a.path)}
        if not wanted:
            return
        paths = list(dict.fromkeys(a.path for a in wanted.values()))
        post_when_done(self.ctx.post,
                       self.ctx.fetch_local(paths, "notes-media"),
                       self._pictures_fetched, request, wanted)

    def _pictures_fetched(self, done, request, wanted):
        if request != self._request or done.exception() is not None:
            return
        local = done.result()
        for tag, attachment in wanted.items():
            path = local.get(attachment.path)
            if not path:
                continue
            photo = imaging.photo_for_tk(path, PICTURE_BOX)
            if photo is not None:
                self._show_picture(tag, photo)

    def _show_picture(self, tag, photo):
        number = int(tag[3:])
        text = self.body
        try:
            start, end = text.index(f"ats{number}"), text.index(f"ate{number}")
        except tk.TclError:
            return                        # the note changed meanwhile
        text.configure(state="normal")
        text.delete(start, end)
        text.image_create(start, image=photo, padx=2, pady=4)
        text.tag_add(tag, start)
        text.configure(state="disabled")
        self._photos.append(photo)

    # ── Searching ────────────────────────────────────────────

    def _search(self):
        text = self.search_var.get().strip()
        if not text:
            self._show_tree()
            return
        if self.source is None:
            return
        self._request += 1
        self.state_var.set("Searching...")
        self.run_query(lambda reader: reader.search(text), self._on_results,
                       self._request, text)

    def _on_results(self, done, request, text):
        if request != self._request or self.search_var.get().strip() != text:
            return
        error = done.exception()
        if error is not None:
            self.fail("Search failed", error)
            return
        results = done.result()
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        for note in results:
            self._add_note_row("", note, show_folder=True)
        self.state_var.set(f"{len(results):,} matching notes")

    # ── Exporting ────────────────────────────────────────────

    def _selected_folder(self):
        selection = self.tree.selection()
        if selection:
            kind, item = self._items.get(selection[0], (None, None))
            if kind == "folder":
                return item
            if kind == "note":
                return self.folders.get(item.folder)
        return None

    def _notes_in(self, folder):
        children, _roots = self._folder_children()
        wanted, stack = set(), [folder]
        while stack:
            current = stack.pop()
            wanted.add(current.pk)
            stack.extend(children.get(current.pk, ()))
        return [n for n in self.notes if n.folder in wanted]

    def export(self, default_scope=None):
        if not self.notes:
            messagebox.showinfo("Info", "There are no notes to export.")
            return
        scopes = {}
        if self.current is not None:
            scopes["one"] = f"Only “{self.current.display_title}”"
        folder = self._selected_folder()
        if folder is not None:
            scopes["folder"] = (f"Everything in “{folder.title}” "
                                f"({len(self._notes_in(folder)):,})")
        scopes["all"] = f"All {len(self.notes):,} notes"
        if default_scope not in scopes:
            default_scope = next(iter(scopes))
        choice = ask_export(self, "Export notes", nx.formats(), scopes,
                            default_scope)
        if choice is None:
            return
        fmt, scope, destination = choice
        chosen = {"one": lambda: [self.current],
                  "folder": lambda: self._notes_in(folder),
                  "all": lambda: list(self.notes)}[scope]()
        self.export_to(chosen, fmt, destination)

    def export_to(self, notes, fmt, destination):
        """Export *notes* as *fmt* into *destination* (in the background)."""
        folders = dict(self.folders)
        self.start_export(
            lambda reader: [reader.load(n) for n in notes],
            lambda data, fetch: nx.export(data, folders, fmt, destination,
                                          fetch),
            destination)

    # ── Original files ───────────────────────────────────────

    def extract_originals(self):
        if self.source is None:
            messagebox.showinfo("Info", "Notes are not loaded yet.")
            return
        only = None
        if self.current is not None:
            answer = messagebox.askyesnocancel(
                "Original files",
                f"Extract the originals for “{self.current.display_title}” "
                "only?\n\n"
                "Yes: just this note's attachments\nNo: every attachment\n\n"
                "The Notes database itself is always included.")
            if answer is None:
                return
            only = [self.current] if answer else None
        self.run_query(lambda reader: reader.attachment_paths(only),
                       self._originals_ready)

    def _originals_ready(self, done):
        error = done.exception()
        if error is not None:
            messagebox.showerror("Original files", str(error))
            return
        self.extract_originals_of(
            [nt.DATABASE, nt.DATABASE + "-wal", nt.DATABASE + "-shm"]
            + done.result())
