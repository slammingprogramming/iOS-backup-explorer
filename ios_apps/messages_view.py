# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Messages view
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

"""The Messages tab: conversations on the left, a chat on the right.

Looks like the Messages app: your messages on the right in blue (green for
SMS), theirs on the left in grey, day headings, tapbacks, and attachments
you can click to save. Everything can be exported, and the original
database and attachments can always be extracted untouched.
"""

import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import messages as ms
from . import messages_export as mx
from ui_util import post_when_done, weak_notifier

from .common import SqliteSource, format_datetime
from .dialogs import ask_export

PAGE = 500
"""How many messages are drawn at once; older ones load on request."""

_SENT_IMESSAGE = "#0b84fe"
_SENT_SMS = "#34c759"
_RECEIVED = "#e5e5ea"
_MUTED = "#6b7280"


def wrap_text(text, measure, max_width):
    """Break *text* into lines no wider than *max_width*.

    *measure(string)* gives the width of a string. Existing line breaks are
    kept, words are never split unless a single word is wider than the whole
    line, and an empty paragraph stays as one empty line.
    """
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}" if current else word
            if not current or measure(candidate) <= max_width:
                current = candidate
                if measure(current) <= max_width:
                    continue
            else:
                lines.append(current)
                current = word
            while measure(current) > max_width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and measure(current[:cut]) > max_width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current)
    return lines


class _ReaderHolder:
    """Where the reader (made on the database thread) is kept."""

    reader = None


class MessagesPanel(ttk.Frame):
    @property
    def _reader(self):
        return self._holder.reader

    def __init__(self, master, context):
        super().__init__(master)
        self.ctx = context
        self.source = None
        self._holder = _ReaderHolder()   # its reader lives on the source's
                                         # thread; closures use the holder,
                                         # never the panel
        self._loaded = False
        self._request = 0
        self._search_job = None
        self._resize_job = None
        self._rendered_width = 0
        self.conversations = []
        self._items = {}                 # conversation tree row -> Conversation
        self._result_items = {}          # search result row -> (conv, message)
        self.current = None
        self._messages = []
        self._shown_from = 0
        self._ranges = {}                # message rowid -> (start, end) index
        self._attachment_tags = {}
        self.search_var = tk.StringVar()
        self.title_var = tk.StringVar(value="")
        self.info_var = tk.StringVar(value="")
        self.state_var = tk.StringVar(value="")
        self._build()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        search = ttk.Frame(self)
        search.pack(fill="x", pady=(0, 6))
        ttk.Label(search, text="Search messages:").pack(side="left")
        self.search_entry = ttk.Entry(search, textvariable=self.search_var,
                                      width=40)
        self.search_entry.pack(side="left", padx=8)
        self.search_var.trace_add("write", lambda *a: self._schedule_search())
        ttk.Label(search, textvariable=self.state_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Export this conversation...",
                   command=lambda: self.export("one")).pack(side="left")
        ttk.Button(bottom, text="Export all...",
                   command=lambda: self.export("all")).pack(side="left",
                                                           padx=6)
        ttk.Button(bottom, text="Extract original files...",
                   command=self.extract_originals).pack(side="right")

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(paned, text="Conversations", padding=6)
        paned.add(left, weight=2)
        self.list_frame = ttk.Frame(left)
        self.list_frame.pack(fill="both", expand=True)
        columns = ("last", "count")
        self.conversation_tree = ttk.Treeview(
            self.list_frame, columns=columns, show=("tree", "headings"),
            selectmode="browse")
        self.conversation_tree.heading("#0", text="Conversation")
        self.conversation_tree.heading("last", text="Last message")
        self.conversation_tree.heading("count", text="Messages")
        self.conversation_tree.column("#0", width=210, minwidth=100)
        self.conversation_tree.column("last", width=110, minwidth=70)
        self.conversation_tree.column("count", width=70, minwidth=50,
                                      anchor="e")
        scroll = ttk.Scrollbar(self.list_frame, orient="vertical",
                               command=self.conversation_tree.yview)
        self.conversation_tree.configure(yscrollcommand=scroll.set)
        self.conversation_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.conversation_tree.bind("<<TreeviewSelect>>",
                                    self._on_conversation_select)

        self.result_frame = ttk.Frame(left)       # shown while searching
        self.result_tree = ttk.Treeview(
            self.result_frame, columns=("when", "text"),
            show=("tree", "headings"), selectmode="browse")
        self.result_tree.heading("#0", text="Conversation")
        self.result_tree.heading("when", text="Date")
        self.result_tree.heading("text", text="Message")
        self.result_tree.column("#0", width=130, minwidth=80)
        self.result_tree.column("when", width=110, minwidth=70)
        self.result_tree.column("text", width=200, minwidth=80)
        result_scroll = ttk.Scrollbar(self.result_frame, orient="vertical",
                                      command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=result_scroll.set)
        self.result_tree.pack(side="left", fill="both", expand=True)
        result_scroll.pack(side="right", fill="y")
        self.result_tree.bind("<Double-1>", lambda e: self._open_result())
        self.result_tree.bind("<Return>", lambda e: self._open_result())

        right = ttk.LabelFrame(paned, text="Messages", padding=6)
        paned.add(right, weight=5)
        header = ttk.Frame(right)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.title_var,
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, textvariable=self.info_var,
                  style="Subtitle.TLabel").pack(anchor="w")
        self.earlier_btn = ttk.Button(right, text="", command=self._show_more)
        self.chat_text = tk.Text(right, wrap="word", state="disabled",
                                 cursor="arrow", borderwidth=0,
                                 highlightthickness=0, padx=8, pady=6,
                                 background="#ffffff")
        chat_scroll = ttk.Scrollbar(right, orient="vertical",
                                    command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=chat_scroll.set)
        chat_scroll.pack(side="right", fill="y")
        self.chat_text.pack(side="left", fill="both", expand=True)
        self._configure_tags()

    def _configure_tags(self):
        text = self.chat_text
        base = tkfont.nametofont("TkDefaultFont").actual()
        family, size = base["family"], max(9, abs(base["size"]))
        self._body_font = tkfont.Font(family=family, size=size)
        self._space = max(1, self._body_font.measure(" "))
        body, small = (family, size), (family, size - 2)
        text.tag_configure("day", justify="center", foreground=_MUTED,
                           font=small, spacing1=14, spacing3=4)
        text.tag_configure("event", justify="center", foreground=_MUTED,
                           font=(family, size - 1, "italic"), spacing1=6,
                           spacing3=6)
        # Where a line sits (these never have a background: Tk paints the
        # margin and the alignment padding with the first character's
        # background, so a bubble's first character must stay plain)
        for side, justify, left, right in (("recv", "left", 8, 8),
                                           ("sent", "right", 8, 8)):
            text.tag_configure(f"{side}_line", justify=justify, lmargin1=left,
                               lmargin2=left, rmargin=right, spacing1=1,
                               spacing3=1, font=body)
            text.tag_configure(f"meta_{side}", foreground=_MUTED, font=small,
                               justify=justify, lmargin1=left,
                               lmargin2=left, rmargin=right, spacing1=6)
        # What the bubble looks like
        for name, colour, fg in (("recv_bg", _RECEIVED, "#1c1c1e"),
                                 ("sent_bg", _SENT_IMESSAGE, "#ffffff"),
                                 ("sent_sms_bg", _SENT_SMS, "#ffffff")):
            text.tag_configure(name, background=colour, foreground=fg)
        text.tag_configure("react", foreground=_MUTED, font=small)
        text.tag_configure("attachment", underline=True)
        text.tag_configure("hit", background="#fde68a", foreground="#1c1c1e")
        text.tag_raise("hit")
        text.bind("<Configure>", self._on_resize)

    def _bubble_width(self):
        """The widest a bubble may be: about 60% of the chat pane."""
        width = self.chat_text.winfo_width()
        return int((width if width > 100 else 760) * 0.6)

    def _on_resize(self, event):
        if abs(event.width - self._rendered_width) < 40 or not self._messages:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(250, self._rewrap)

    def _rewrap(self):
        self._resize_job = None
        if self._messages:
            self._render()

    # ── Loading ──────────────────────────────────────────────

    def activate(self):
        """Called when the tab is first shown; loads the data once."""
        if self._loaded:
            return
        self._loaded = True
        self.state_var.set("Loading messages...")
        future = self.ctx.copy_database(ms.DATABASE, "messages")
        if future is None:
            self.state_var.set("This backup has no Messages database.")
            return
        post_when_done(self.ctx.post, future, self._database_copied)

    def _database_copied(self, done):
        error = done.exception()
        if error is not None:
            self.state_var.set(
                f"Could not read Messages: {str(error) or type(error).__name__}")
            return
        self.ctx.load_contacts(self._with_contacts)

    def _with_contacts(self, book):
        path = os.path.join(self.ctx.workspace.subfolder("messages"),
                            "sms.db")
        self.source = SqliteSource(path)

        holder = self._holder

        def start(conn):
            holder.reader = ms.MessagesReader(conn, book)
            return holder.reader.conversations()

        post_when_done(self.ctx.post, self.source.run(start),
                       self._on_conversations)

    def _on_conversations(self, done):
        error = done.exception()
        if error is not None:
            self.state_var.set(
                f"Could not read Messages: {str(error) or type(error).__name__}")
            return
        self.conversations = done.result()
        self._items.clear()
        self.conversation_tree.delete(*self.conversation_tree.get_children())
        for number, conv in enumerate(self.conversations):
            item = f"c{number}"
            self._items[item] = conv
            self.conversation_tree.insert(
                "", "end", iid=item, text=conv.title,
                values=(format_datetime(conv.last_when), f"{conv.count:,}"))
        total = sum(c.count for c in self.conversations)
        self.state_var.set(f"{len(self.conversations):,} conversations, "
                           f"{total:,} messages")

    # ── Showing a conversation ───────────────────────────────

    def _on_conversation_select(self, event):
        selection = self.conversation_tree.selection()
        if selection:
            self.select_conversation(self._items[selection[0]])

    def select_conversation(self, conv, highlight=None):
        """Show *conv*; *highlight* is the row id of a message to scroll to."""
        self._request += 1
        request = self._request
        self.current = conv
        self.title_var.set(conv.title)
        self.info_var.set(self._describe(conv))
        reader = self._reader
        post_when_done(self.ctx.post,
                       self.source.run(lambda conn: reader.messages(conv)),
                       self._on_messages, request, highlight)

    @staticmethod
    def _describe(conv):
        bits = [f"{conv.count:,} messages"]
        if conv.services:
            bits.append(conv.service_label)
        if conv.is_group and conv.participants:
            bits.append("with " + ", ".join(conv.participants))
        elif conv.identifier and conv.identifier != conv.title:
            bits.append(conv.identifier)
        return " · ".join(bits)

    def _on_messages(self, done, request, highlight):
        if request != self._request:
            return                    # another conversation was chosen
        error = done.exception()
        if error is not None:
            self.state_var.set(
                f"Could not read the conversation: "
                f"{str(error) or type(error).__name__}")
            return
        self._messages = done.result()
        self._shown_from = max(0, len(self._messages) - PAGE)
        if highlight is not None:
            for position, message in enumerate(self._messages):
                if message.rowid == highlight:
                    self._shown_from = min(self._shown_from, position)
                    break
        self._render(highlight)

    def _show_more(self):
        self._shown_from = max(0, self._shown_from - PAGE)
        self._render()

    def _render(self, highlight=None):
        text = self.chat_text
        self._rendered_width = text.winfo_width()
        text.configure(state="normal")
        text.delete("1.0", "end")
        self._ranges.clear()
        self._attachment_tags.clear()
        for mark in text.mark_names():
            if mark.startswith("m"):
                text.mark_unset(mark)

        hidden = self._shown_from
        if hidden:
            self.earlier_btn.configure(
                text=f"Show {min(PAGE, hidden):,} earlier messages "
                     f"({hidden:,} not shown)")
            self.earlier_btn.pack(fill="x", pady=(4, 0), before=self.chat_text)
        else:
            self.earlier_btn.pack_forget()

        group = bool(self.current and self.current.is_group)
        day = None
        for message in self._messages[self._shown_from:]:
            stamp = format_datetime(message.when)
            if stamp[:10] != day and stamp:
                day = stamp[:10]
                text.insert("end", f"{day}\n", "day")
            start = text.index("end-1c")
            text.mark_set(f"m{message.rowid}", start)
            text.mark_gravity(f"m{message.rowid}", "left")
            if message.kind == "event":
                text.insert("end", f"{message.text}\n", "event")
            else:
                self._insert_message(text, message, group, stamp)
            self._ranges[message.rowid] = (start, text.index("end-1c"))
        text.configure(state="disabled")

        if highlight is not None and highlight in self._ranges:
            start, end = self._ranges[highlight]
            text.tag_add("hit", start, end)
            text.see(start)
        else:
            text.see("end")

    def _insert_bubble(self, text, lines, side, colour, extra=()):
        """Insert *lines* as one rectangular bubble."""
        measure = self._body_font.measure
        widest = max(measure(f"  {line}  ") for line in lines)
        for line in lines:
            padding = " " * int((widest - measure(f"  {line}  "))
                                / self._space)
            text.insert("end", " ", f"{side}_line")      # plain: see above
            text.insert("end", f"  {line}{padding}  ",
                        (f"{side}_line", colour, *extra))
            text.insert("end", "\n")

    def _insert_message(self, text, message, group, stamp):
        side = "sent" if message.from_me else "recv"
        colour = ("sent_sms_bg" if (message.service or "").upper() == "SMS"
                  else "sent_bg") if message.from_me else "recv_bg"
        who = message.sender if group and not message.from_me else ""
        clock = stamp[11:]
        text.insert("end", (f"{who}  " if who else "") + clock + "\n",
                    f"meta_{side}")
        limit = self._bubble_width()
        if message.text:
            self._insert_bubble(
                text, wrap_text(message.text, self._body_font.measure, limit),
                side, colour)
        for attachment in message.attachments:
            tag = f"att{len(self._attachment_tags)}"
            self._attachment_tags[tag] = attachment
            detail = ", ".join(x for x in (
                attachment.mime, mx.describe_size(attachment.size)) if x)
            label = f"Attachment: {attachment.name}" \
                + (f" ({detail})" if detail else "")
            self._insert_bubble(text, [label], side, colour,
                                ("attachment", tag))
            text.tag_bind(tag, "<Button-1>",
                          lambda e, a=attachment: self.save_attachment(a))
            text.tag_bind(tag, "<Enter>",
                          lambda e: text.configure(cursor="hand2"))
            text.tag_bind(tag, "<Leave>",
                          lambda e: text.configure(cursor="arrow"))
        if message.reactions:
            line = ", ".join(f"{r.kind} by {r.sender}"
                             for r in message.reactions)
            text.insert("end", f"{line}\n", ("react", f"meta_{side}"))

    # ── Searching ────────────────────────────────────────────

    def _schedule_search(self):
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(400, self._run_search)

    def _run_search(self):
        self._search_job = None
        text = self.search_var.get().strip()
        if not text:
            self.result_frame.pack_forget()
            self.list_frame.pack(fill="both", expand=True)
            return
        if self.source is None:
            return
        self._request += 1
        request = self._request
        reader = self._reader
        self.state_var.set("Searching...")
        post_when_done(self.ctx.post,
                       self.source.run(lambda conn: reader.search(text)),
                       self._on_results, request, text)

    def _on_results(self, done, request, text):
        if request != self._request or self.search_var.get().strip() != text:
            return
        error = done.exception()
        if error is not None:
            self.state_var.set(f"Search failed: {error}")
            return
        results = done.result()
        self.list_frame.pack_forget()
        self.result_frame.pack(fill="both", expand=True)
        self.result_tree.delete(*self.result_tree.get_children())
        self._result_items.clear()
        for number, (conv, message) in enumerate(results):
            item = f"r{number}"
            self._result_items[item] = (conv, message)
            snippet = (message.text or "").replace("\n", " ")[:80]
            self.result_tree.insert(
                "", "end", iid=item, text=conv.title,
                values=(format_datetime(message.when), snippet))
        self.state_var.set(f"{len(results):,} matching messages")

    def _open_result(self):
        selection = self.result_tree.selection()
        if selection:
            conv, message = self._result_items[selection[0]]
            self.select_conversation(conv, highlight=message.rowid)

    # ── Saving and exporting ─────────────────────────────────

    def save_attachment(self, attachment):
        """Ask where to put one attachment and copy it there."""
        if not attachment.backup_path or \
                self.ctx.file_id_for(attachment.backup_path) is None:
            messagebox.showinfo("Attachment",
                                "This attachment is not in the backup.")
            return
        destination = filedialog.asksaveasfilename(
            initialfile=attachment.name, title="Save attachment as")
        if not destination:
            return
        future = self.ctx.save_file(attachment.backup_path, destination)
        post_when_done(self.ctx.post, future, self._saved, destination)

    def _saved(self, done, destination):
        error = done.exception()
        if error is not None:
            messagebox.showerror("Attachment", f"Could not save it: {error}")
        else:
            self.ctx.set_status(f"Saved {destination}")

    def export(self, default_scope="all"):
        """Export one or all conversations as text, a web page, CSV or JSON."""
        if not self.conversations:
            messagebox.showinfo("Info", "There are no messages to export.")
            return
        scopes = {"all": f"All {len(self.conversations):,} conversations"}
        if self.current is not None:
            scopes = {"one": f"Only “{self.current.title}”", **scopes}
        else:
            default_scope = "all"
        choice = ask_export(self, "Export messages", mx.FORMATS, scopes,
                            default_scope)
        if choice is None:
            return
        fmt, scope, folder = choice
        chosen = [self.current] if scope == "one" else list(self.conversations)
        self.export_to(chosen, fmt, folder)

    def export_to(self, conversations, fmt, folder):
        """Export *conversations* in format *fmt* into *folder* (in the
        background)."""
        self.ctx.set_status(f"Exporting {len(conversations):,} "
                            f"conversation(s)...")
        reader = self._reader

        def load(conn):
            return [(c, reader.messages(c)) for c in conversations]

        post_when_done(self.ctx.post, self.source.run(load),
                       self._start_export, fmt, folder)

    def _start_export(self, done, fmt, folder):
        error = done.exception()
        if error is not None:
            self._export_finished(error, None, folder)
            return
        items = done.result()
        session, index = self.ctx.session, self.ctx.index
        notify = weak_notifier(self.ctx.post, self._export_finished)

        def fetch(wanted):
            pairs = []
            for attachment, name in wanted:
                node = index.get(attachment.backup_path)
                if node is not None and not node.is_dir:
                    pairs.append((node.file_id, name))
            if not pairs:
                return []
            return session.export_files(
                pairs, os.path.join(folder, "attachments")).result()

        def work():
            try:
                paths = mx.export(items, fmt, folder, fetch)
            except Exception as exc:
                notify(exc, None, folder)
            else:
                notify(None, paths, folder)

        threading.Thread(target=work, daemon=True, name="export").start()

    def _export_finished(self, error, paths, folder):
        if error is not None:
            self.ctx.set_status("Export failed.")
            messagebox.showerror("Export failed",
                                 str(error) or type(error).__name__)
            return
        self.ctx.set_status(f"Exported {len(paths):,} file(s) to {folder}")
        messagebox.showinfo("Export finished",
                            f"Wrote {len(paths):,} file(s) to:\n{folder}")

    def extract_originals(self):
        """Extract the database and attachments exactly as the backup has
        them, untouched, using the normal extraction."""
        if self.source is None:
            messagebox.showinfo("Info", "Messages are not loaded yet.")
            return
        only_this = False
        if self.current is not None:
            answer = messagebox.askyesnocancel(
                "Original files",
                f"Extract the originals for “{self.current.title}” "
                "only?\n\nYes: just this conversation's attachments\n"
                "No: every attachment\n\nThe Messages database itself is "
                "always included.")
            if answer is None:
                return
            only_this = answer
        conv, reader = (self.current if only_this else None), self._reader
        post_when_done(
            self.ctx.post,
            self.source.run(lambda conn: reader.attachment_paths(conv)),
            self._originals_ready)

    def _originals_ready(self, done):
        error = done.exception()
        if error is not None:
            messagebox.showerror("Original files", str(error))
            return
        paths = [ms.DATABASE, ms.DATABASE + "-wal",
                 ms.DATABASE + "-shm"] + done.result()
        ids = [fid for fid in (self.ctx.file_id_for(p) for p in paths) if fid]
        if not ids:
            messagebox.showinfo("Original files", "Nothing to extract.")
            return
        self.ctx.extract(list(dict.fromkeys(ids)))

    # ── Shutdown ─────────────────────────────────────────────

    def cancel_timers(self):
        for job in (self._search_job, self._resize_job):
            if job is not None:
                self.after_cancel(job)
        self._search_job = self._resize_job = None

    def close(self):
        self.cancel_timers()
        if self.source is not None:
            self.source.close()
            self.source = None
