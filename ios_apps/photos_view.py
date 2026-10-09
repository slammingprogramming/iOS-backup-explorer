# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Photos view
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

"""The Photos tab: albums on the left, a grid of thumbnails on the right.

Thumbnails are made only for the pictures on screen, as you scroll, so a
camera roll of any size opens at once. Pictures and videos can be opened,
saved, exported (as they are, as JPEG, as a web gallery, as a list), and
the original files can always be extracted untouched.
"""

import math
import os
import sqlite3
import threading
import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict, deque
from tkinter import filedialog, messagebox, ttk

from ui_util import post_when_done, weak_notifier

from . import imaging
from . import photos as ph
from . import photos_export as px
from .common import format_datetime
from .dialogs import ask_export
from .export_util import describe_duration, describe_size
from .panel_base import AppPanel

CELL = 148                       # the space one picture takes in the grid
THUMB = 128                      # the thumbnail itself
CACHE = 700                      # thumbnails kept in memory
IN_FLIGHT = 12                   # thumbnails being made at one time
BATCH = 6                        # fetched from the backup together
_SELECT = "#0b84fe"
_TILE = "#eef0f3"


def _load(conn, _book, index):
    """(runs on the database thread) -> no reader, and ``(items, note)``."""
    items = ph.scan(index)
    note = ""
    try:
        ph.enrich(items, conn)
    except sqlite3.Error as exc:
        note = f"The photo library could not be read ({exc}); " \
               "showing the files only."
    return None, (items, note)


class PhotosPanel(AppPanel):
    DATABASE = ph.DATABASE
    FOLDER = "photos"
    OPTIONAL = True
    LOADER = staticmethod(_load)
    MISSING = "This backup has no photos."

    def __init__(self, master, context):
        super().__init__(master, context)
        self.items = []
        self._note = ""                  # what went wrong reading the library
        self.shown = []
        self.album = ph.ALL
        self.selected = []               # item paths, in the order chosen
        self._anchor = None
        self._cols = 1
        self._album_rows = {}
        self._thumbs = OrderedDict()     # path -> Tk image, or False
        self._queue = deque()
        self._pending = set()
        self._inflight = 0
        self._visible = []
        self._pool_stop = False
        self._notify_thumb = weak_notifier(self.ctx.post, self._thumb_ready)
        self._notify_progress = weak_notifier(self.ctx.post,
                                              self._export_progress)
        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value=next(iter(ph.SORTS)))
        self.info_var = tk.StringVar()
        self.hint_var = tk.StringVar()
        self._build()

    # ── Loading ──────────────────────────────────────────────

    def database_path(self):
        index = self.ctx.index
        node = index.get(ph.DATABASE) if index is not None else None
        return ph.DATABASE if node is not None and not node.is_dir else None

    def load_without_database(self, note=""):
        return ph.scan(self.ctx.index), note

    def on_loaded(self, data):
        self.items, self._note = data
        self._show_albums()
        self.refresh()
        self._set_hint()

    def _set_hint(self):
        if not self.items:
            return
        if not imaging.have_pillow():
            self.hint_var.set(
                "Install Pillow and pillow-heif to see previews of JPEG and "
                "HEIC pictures: pip install Pillow pillow-heif")
        elif not imaging.have_heif() and any(
                i.extension in imaging.HEIF_EXTENSIONS for i in self.items):
            self.hint_var.set(
                "Install pillow-heif to see previews of HEIC pictures: "
                "pip install pillow-heif")

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Search:").pack(side="left")
        ttk.Entry(top, textvariable=self.search_var, width=28).pack(
            side="left", padx=8)
        self.search_var.trace_add(
            "write", lambda *a: self.schedule("search", 300, self.refresh))
        ttk.Label(top, text="Sort by:").pack(side="left", padx=(12, 4))
        self.sort_box = ttk.Combobox(top, textvariable=self.sort_var,
                                     values=list(ph.SORTS), state="readonly",
                                     width=24)
        self.sort_box.pack(side="left")
        self.sort_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(top, textvariable=self.state_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Open", command=self.open_selected).pack(
            side="left")
        ttk.Button(bottom, text="Save as...", command=self.save_selected).pack(
            side="left", padx=6)
        ttk.Button(bottom, text="Export...", command=self.export).pack(
            side="left")
        ttk.Button(bottom, text="Extract original files...",
                   command=self.extract_originals).pack(side="right")
        ttk.Label(self, textvariable=self.hint_var,
                  style="Subtitle.TLabel").pack(side="bottom", anchor="w")
        ttk.Label(self, textvariable=self.info_var,
                  style="Subtitle.TLabel", wraplength=900).pack(
            side="bottom", anchor="w", pady=(4, 0))

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.LabelFrame(paned, text="Albums", padding=6)
        paned.add(left, weight=1)
        self.album_tree = ttk.Treeview(left, show="tree",
                                       selectmode="browse")
        self.album_tree.column("#0", width=190, minwidth=100)
        self.album_tree.pack(fill="both", expand=True)
        self.album_tree.bind("<<TreeviewSelect>>", self._on_album)

        right = ttk.LabelFrame(paned, text="Pictures and videos", padding=6)
        paned.add(right, weight=4)
        self.canvas = tk.Canvas(right, background="#ffffff",
                                highlightthickness=0, takefocus=True)
        scroll = ttk.Scrollbar(right, orient="vertical",
                               command=self._on_scrollbar)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._font = tkfont.Font(family=tkfont.nametofont(
            "TkDefaultFont").actual()["family"], size=8)
        self.canvas.bind("<Configure>", lambda e: self._layout())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Control-Button-1>",
                         lambda e: self._on_click(e, toggle=True))
        self.canvas.bind("<Shift-Button-1>",
                         lambda e: self._on_click(e, extend=True))
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._on_context)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll(3))
        self.canvas.bind("<Control-a>", lambda e: self.select_all())
        self.canvas.bind("<Return>", lambda e: self.open_selected())
        for key, step in (("Left", -1), ("Right", 1)):
            self.canvas.bind(f"<{key}>", lambda e, s=step: self._move(s))
        for key, sign in (("Up", -1), ("Down", 1)):
            self.canvas.bind(f"<{key}>",
                             lambda e, s=sign: self._move(s * self._cols))

    # ── Albums ───────────────────────────────────────────────

    def _count(self, album):
        return sum(1 for i in self.items if ph.in_album(i, album))

    def _show_albums(self):
        tree = self.album_tree
        tree.delete(*tree.get_children())
        self._album_rows.clear()

        def add(parent, key, label, count):
            row = tree.insert(parent, "end", text=f"{label}  ({count:,})",
                              open=True)
            self._album_rows[row] = key
            return row

        for key in (ph.ALL, ph.PHOTOS, ph.VIDEOS, ph.FAVORITES, ph.HIDDEN,
                    ph.DELETED):
            count = self._count(key)
            if key == ph.ALL or count:
                add("", key, ph.SMART_ALBUMS[key], count)
        albums, folders = ph.albums_of(self.items)
        if albums:
            parent = tree.insert("", "end", text="My albums", open=True)
            for key, count in albums:
                add(parent, key, key[1], count)
        if folders and (len(folders) > 1 or not albums):
            parent = tree.insert("", "end", text="Folders on the phone",
                                 open=True)
            for key, count in folders:
                add(parent, key, key[1].replace("DCIM/", ""), count)
        first = next(iter(self._album_rows), None)
        if first is not None:
            tree.selection_set(first)

    def _on_album(self, event):
        selection = self.album_tree.selection()
        if selection and selection[0] in self._album_rows:
            self.album = self._album_rows[selection[0]]
            self.refresh()

    # ── The list and the grid ────────────────────────────────

    def refresh(self):
        """Apply the album, the search and the sort; draw the grid again."""
        self.cancel_timer("search")
        items = [i for i in self.items if ph.in_album(i, self.album)]
        text = self.search_var.get().strip()
        if text:
            items = ph.search_items(items, text)
        self.shown = ph.sort_items(items, self.sort_var.get())
        keep = {i.path for i in self.shown}
        self.selected = [p for p in self.selected if p in keep]
        self._queue.clear()
        self._pending.clear()
        self.canvas.yview_moveto(0)
        self._layout()
        self._describe()
        if self.items:
            self.state_var.set(self._note or f"{len(self.shown):,} of "
                               f"{len(self.items):,} items")

    def _layout(self):
        width = max(self.canvas.winfo_width(), CELL)
        self._cols = max(1, width // CELL)
        rows = math.ceil(len(self.shown) / self._cols) if self.shown else 0
        self.canvas.configure(scrollregion=(0, 0, self._cols * CELL,
                                            max(rows * CELL, 1)))
        self._draw()

    def _on_scrollbar(self, *args):
        self.canvas.yview(*args)
        self._draw()

    def _scroll(self, units):
        self.canvas.yview_scroll(units, "units")
        self._draw()

    def _on_wheel(self, event):
        self._scroll(-3 if event.delta > 0 else 3)

    def _draw(self):
        """Draw the tiles that can be seen (and ask for their thumbnails)."""
        canvas = self.canvas
        canvas.delete("all")
        if not self.shown:
            canvas.create_text(
                canvas.winfo_width() // 2 or 200, 60, fill="#6b7280",
                text="Nothing to show here." if self.items
                else "Opening the camera roll...")
            self._visible = []
            return
        top = canvas.canvasy(0)
        first = max(0, int(top // CELL) - 1)
        last = int((top + canvas.winfo_height()) // CELL) + 1
        start, end = first * self._cols, min(len(self.shown),
                                             (last + 1) * self._cols)
        self._visible = self.shown[start:end]
        chosen = set(self.selected)
        for position in range(start, end):
            item = self.shown[position]
            x = (position % self._cols) * CELL
            y = (position // self._cols) * CELL
            self._draw_tile(item, x, y, item.path in chosen)
        self._request_thumbnails()

    def _draw_tile(self, item, x, y, chosen):
        canvas = self.canvas
        if chosen:
            canvas.create_rectangle(x + 2, y + 2, x + CELL - 2, y + CELL - 2,
                                    fill="#dbeafe", outline=_SELECT, width=2)
        left = x + (CELL - THUMB) // 2
        canvas.create_rectangle(left, y + 6, left + THUMB, y + 6 + THUMB,
                                fill=_TILE, outline="")
        thumb = self._thumbs.get(item.path)
        if thumb:
            canvas.create_image(left + THUMB // 2, y + 6 + THUMB // 2,
                                image=thumb)
        else:
            label = ("▶" if item.kind == ph.VIDEO
                     else item.extension.lstrip(".").upper())
            canvas.create_text(left + THUMB // 2, y + 6 + THUMB // 2,
                               text=label, fill="#6b7280")
        if item.kind == ph.VIDEO and item.duration:
            canvas.create_text(left + THUMB - 4, y + THUMB - 2, anchor="se",
                               text=describe_duration(item.duration),
                               fill="#ffffff" if thumb else "#6b7280",
                               font=self._font)
        marks = ("♥ " if item.favorite else "") + (
            "hidden " if item.hidden else "")
        canvas.create_text(x + CELL // 2, y + THUMB + 14, width=CELL - 8,
                           text=marks + item.name, font=self._font,
                           fill="#1c1c1e")

    # ── Thumbnails ───────────────────────────────────────────

    def _request_thumbnails(self):
        for item in self._visible:
            if (item.path in self._thumbs or item.path in self._pending
                    or item.kind != ph.PHOTO
                    or not imaging.can_show(item.name)):
                continue
            self._pending.add(item.path)
            self._queue.append(item)
        self._pump()

    def _pump(self):
        """Start fetching the next few thumbnails (a handful at a time:
        every fetch is one trip to the backup)."""
        while self._inflight < IN_FLIGHT and self._queue:
            batch = []
            while self._queue and len(batch) < BATCH:
                item = self._queue.popleft()
                if item in self._visible:
                    batch.append(item.path)
                else:                              # scrolled away meanwhile
                    self._pending.discard(item.path)
            if not batch:
                break
            self._inflight += len(batch)
            post_when_done(self.ctx.post,
                           self.ctx.fetch_local(batch, "photo-thumbs"),
                           self._fetched, batch)

    def _fetched(self, done, paths):
        if self._closed:
            return
        found = {} if done.exception() is not None else done.result()
        for path in paths:
            if path not in found:
                self._thumb_ready(path, None, None)
        got = [(p, found[p]) for p in paths if p in found]
        if not got:
            return
        if imaging.have_pillow():
            notify = self._notify_thumb

            def work():                  # decode off the Tk thread
                for path, local in got:
                    image = imaging.make_thumbnail(local, (THUMB, THUMB))
                    _remove(local)
                    notify(path, image, None)

            threading.Thread(target=work, daemon=True,
                             name="thumbnail").start()
        else:                                   # Tk itself shows PNG and GIF
            for path, local in got:
                photo = imaging.photo_for_tk(local, (THUMB, THUMB))
                _remove(local)
                self._thumb_ready(path, None, photo)

    def _thumb_ready(self, path, image, photo):
        if self._closed:
            return
        self._inflight = max(0, self._inflight - 1)
        self._pending.discard(path)
        if photo is None and image is not None:
            photo = imaging.photo_for_tk(image, (THUMB, THUMB))
        self._thumbs[path] = photo or False
        while len(self._thumbs) > CACHE:
            self._thumbs.popitem(last=False)
        if any(i.path == path for i in self._visible):
            self._draw()
        else:
            self._pump()

    # ── Selecting ────────────────────────────────────────────

    def _index_at(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if x < 0 or y < 0 or x >= self._cols * CELL:
            return None
        index = int(y // CELL) * self._cols + int(x // CELL)
        return index if index < len(self.shown) else None

    def _on_click(self, event, toggle=False, extend=False):
        self.canvas.focus_set()
        index = self._index_at(event)
        if index is None:
            if not (toggle or extend):
                self.set_selection([])
            return
        item = self.shown[index]
        if extend and self._anchor in {i.path for i in self.shown}:
            start = next(n for n, i in enumerate(self.shown)
                         if i.path == self._anchor)
            low, high = sorted((start, index))
            self.set_selection([i.path for i in self.shown[low:high + 1]],
                               keep_anchor=True)
        elif toggle:
            chosen = list(self.selected)
            if item.path in chosen:
                chosen.remove(item.path)
            else:
                chosen.append(item.path)
            self.set_selection(chosen)
            self._anchor = item.path
        else:
            self.set_selection([item.path])
            self._anchor = item.path

    def set_selection(self, paths, keep_anchor=False):
        self.selected = list(paths)
        if self.selected and not keep_anchor and self._anchor is None:
            self._anchor = self.selected[0]
        self._draw()
        self._describe()

    def select_all(self):
        self.set_selection([i.path for i in self.shown])
        return "break"

    def _move(self, step):
        if not self.shown:
            return "break"
        positions = {i.path: n for n, i in enumerate(self.shown)}
        current = positions.get(self.selected[-1], -1) if self.selected \
            else -1
        target = min(max(current + step, 0), len(self.shown) - 1) \
            if current >= 0 else 0
        item = self.shown[target]
        self.set_selection([item.path])
        self._anchor = item.path
        self._scroll_to(target)
        return "break"

    def _scroll_to(self, position):
        top = (position // self._cols) * CELL
        view_top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        if top < view_top:
            self.canvas.yview_moveto(top / max(1, self._total_height()))
        elif top + CELL > view_top + height:
            self.canvas.yview_moveto((top + CELL - height)
                                     / max(1, self._total_height()))
        self._draw()

    def _total_height(self):
        return math.ceil(len(self.shown) / self._cols) * CELL

    def selected_items(self):
        chosen = set(self.selected)
        return [i for i in self.shown if i.path in chosen]

    def _describe(self):
        chosen = self.selected_items()
        if not chosen:
            self.info_var.set("")
            return
        if len(chosen) > 1:
            self.info_var.set(
                f"{len(chosen):,} selected, "
                f"{describe_size(sum(i.size for i in chosen))}")
            return
        item = chosen[0]
        bits = [item.name, item.type_label]
        if item.taken:
            bits.append(("taken " if item.taken_from == "library"
                         else "file date ") + format_datetime(item.taken))
        if item.dimensions:
            bits.append(item.dimensions)
        if item.kind == ph.VIDEO and item.duration:
            bits.append(describe_duration(item.duration))
        bits.append(describe_size(item.size) or "empty")
        if item.favorite:
            bits.append("favorite")
        if item.hidden:
            bits.append("hidden")
        if item.trashed:
            bits.append("recently deleted")
        if item.albums:
            bits.append("in " + ", ".join(item.albums))
        if item.location:
            bits.append(item.location)
        bits.append(item.directory)
        self.info_var.set(" · ".join(bits))

    # ── Opening and saving ───────────────────────────────────

    def _on_double(self, event):
        index = self._index_at(event)
        if index is not None:
            self.open_backup_file(self.shown[index].path)

    def _on_context(self, event):
        index = self._index_at(event)
        if index is not None and self.shown[index].path not in self.selected:
            self.set_selection([self.shown[index].path])
        if not self.selected:
            return
        menu = tk.Menu(self, tearoff=False)
        single = len(self.selected) == 1
        menu.add_command(label="Open", command=self.open_selected,
                         state="normal" if single else "disabled")
        menu.add_command(label="Save as...", command=self.save_selected,
                         state="normal" if single else "disabled")
        menu.add_command(
            label="Save as JPEG...", command=self.save_selected_as_jpeg,
            state="normal" if single and imaging.have_pillow() else "disabled")
        menu.add_separator()
        menu.add_command(label="Export selected...",
                         command=lambda: self.export("selected"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _single(self, what):
        chosen = self.selected_items()
        if len(chosen) != 1:
            messagebox.showinfo("Info", f"Choose one picture to {what}.")
            return None
        return chosen[0]

    def open_selected(self):
        item = self._single("open")
        if item is not None:
            self.open_backup_file(item.path)

    def save_selected(self):
        item = self._single("save")
        if item is not None:
            self.save_backup_file(item.path, item.name)

    def save_selected_as_jpeg(self):
        item = self._single("save")
        if item is None:
            return
        destination = filedialog.asksaveasfilename(
            initialfile=os.path.splitext(item.name)[0] + ".jpg",
            defaultextension=".jpg", title="Save as JPEG")
        if not destination:
            return
        post_when_done(self.ctx.post,
                       self.ctx.fetch_local([item.path], "photo-convert"),
                       self._converted_source, item.path, destination)

    def _converted_source(self, done, path, destination):
        local = None if done.exception() is not None \
            else done.result().get(path)
        if not local:
            messagebox.showerror("Save as JPEG", "Could not read the file.")
            return
        notify = weak_notifier(self.ctx.post, self._jpeg_saved)

        def work():
            ok = imaging.to_jpeg(local, destination)
            _remove(local)
            notify(ok, destination)

        threading.Thread(target=work, daemon=True, name="convert").start()

    def _jpeg_saved(self, ok, destination):
        if ok:
            self.ctx.set_status(f"Saved {destination}")
        else:
            messagebox.showerror(
                "Save as JPEG",
                "The picture could not be converted. HEIC pictures need "
                "Pillow and pillow-heif: pip install Pillow pillow-heif")

    # ── Exporting ────────────────────────────────────────────

    def export(self, default_scope=None):
        if not self.items:
            messagebox.showinfo("Info", "There are no pictures to export.")
            return
        scopes = {}
        if self.selected:
            scopes["selected"] = f"The {len(self.selected):,} selected"
        scopes["view"] = f"The {len(self.shown):,} shown"
        scopes["all"] = f"Everything ({len(self.items):,})"
        if default_scope not in scopes:
            default_scope = next(iter(scopes))
        choice = ask_export(self, "Export pictures and videos", px.FORMATS,
                            scopes, default_scope)
        if choice is None:
            return
        fmt, scope, folder = choice
        chosen = {"selected": self.selected_items, "view": lambda: self.shown,
                  "all": lambda: self.items}[scope]()
        self.export_to(chosen, fmt, folder)

    def export_to(self, items, fmt, folder):
        """Export *items* as *fmt* into *folder* (in the background)."""
        items = list(items)
        copy_file = self.ctx.copier()
        scratch = self.ctx.workspace.subfolder("photo-export")
        progress = self._notify_progress
        self.start_export(
            lambda reader: items,
            lambda data, fetch: px.export(data, fmt, folder, copy_file,
                                          scratch, progress),
            folder)

    def _export_progress(self, done, total):
        self.ctx.set_status(f"Exporting {done:,} of {total:,}...")

    def extract_originals(self):
        """Extract the files exactly as the backup has them (with the normal
        extraction, which shows progress and can be cancelled)."""
        chosen = self.selected_items() or list(self.shown)
        paths = [i.path for i in chosen]
        if not paths:
            messagebox.showinfo("Info", "There is nothing to extract.")
            return
        paths += [ph.DATABASE, ph.DATABASE + "-wal", ph.DATABASE + "-shm"]
        self.extract_originals_of(paths)

    # ── Shutdown ─────────────────────────────────────────────

    def close(self):
        self._queue.clear()
        self._pending.clear()
        super().close()


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
