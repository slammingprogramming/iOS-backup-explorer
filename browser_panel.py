# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Files view
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

"""The Files view: a file manager for the backup.

A folder tree on the left, a sortable listing on the right, back / forward /
up navigation, a location bar, search, a context menu and a properties
dialog. It works on a :class:`file_index.FileIndex` held in memory, so
browsing, sorting and searching never wait on the backup.
"""

import concurrent.futures
import tkinter as tk
from tkinter import messagebox, ttk

from ui_util import post_when_done
from file_index import (
    FileIndex, category_for, format_size, format_time, kind_of, sort_nodes,
)

_HEADINGS = {
    "#0": "Name", "kind": "Kind", "size": "Size",
    "modified": "Date Modified", "created": "Date Created",
    "location": "Location",
}
_SORT_KEY = {"#0": "name", "kind": "kind", "size": "size",
             "modified": "modified", "created": "created",
             "location": "location"}
_COLUMNS = ("kind", "size", "modified", "created", "location")
_PLACEHOLDER = "/…"      # id suffix of a folder's "not loaded yet" child

_PICTURES = {"jpg", "jpeg", "png", "heic", "heif", "gif", "webp", "tiff",
             "dng", "bmp"}
_MEDIA = {"mov", "mp4", "m4v", "m4a", "mp3", "aac", "caf", "wav", "amr"}
_DATABASES = {"sqlite", "sqlite3", "db", "sqlitedb", "storedata",
              "sqlite-wal", "sqlite-shm"}


class FileBrowserPanel(ttk.Frame):
    """The Files view.

    *post(func, *args)* must run ``func`` on the Tk thread (it is how
    background results come back). *on_extract(file_ids)* is called when the
    user asks to extract files. *on_status(text)* shows a status line.
    *page_size()* gives the number of rows shown per page.
    """

    def __init__(self, master, *, post, on_extract, on_status, page_size):
        super().__init__(master)
        self._post = post
        self._on_extract = on_extract
        self._on_status = on_status
        self._page_size = page_size

        self.index = None
        self._scope = None
        self._history = []          # [(scope, recursive)]
        self._position = -1
        self._sort_key = "name"
        self._sort_desc = False
        self._listing = []          # everything the current view holds
        self._page = 0
        self._items = {}            # row id -> Node, for the current page
        self._tree_nodes = {}       # folder-tree id -> Node
        self._node_item = {}        # id(Node) -> folder-tree id
        self._category_scope = {}   # category name -> pseudo-folder
        self._category_item = {}    # category name -> folder-tree id
        self._request = 0
        self._search_job = None
        self._quiet = False
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="browser")

        self.search_var = tk.StringVar()
        self.count_var = tk.StringVar(value="")
        self.location_var = tk.StringVar(value="")
        self.page_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=False)
        self.folders_first_var = tk.BooleanVar(value=True)
        self._icons = self._make_icons()
        self._build()

    # ── Layout ───────────────────────────────────────────────

    def _build(self):
        navigation = ttk.Frame(self)
        navigation.pack(fill="x", pady=(0, 6))
        self.back_btn = ttk.Button(navigation, text="←", width=3,
                                   command=self.go_back)
        self.forward_btn = ttk.Button(navigation, text="→", width=3,
                                      command=self.go_forward)
        self.up_btn = ttk.Button(navigation, text="↑", width=3,
                                 command=self.go_up)
        for button in (self.back_btn, self.forward_btn, self.up_btn):
            button.pack(side="left", padx=(0, 4))
        self.location_entry = ttk.Entry(navigation,
                                        textvariable=self.location_var)
        self.location_entry.pack(side="left", fill="x", expand=True,
                                 padx=(4, 0))
        self.location_entry.bind("<Return>", lambda e: self._go_to_typed())

        options = ttk.Frame(self)
        options.pack(fill="x", pady=(0, 6))
        ttk.Label(options, text="Search:").pack(side="left")
        self.search_entry = ttk.Entry(options, textvariable=self.search_var,
                                      width=32)
        self.search_entry.pack(side="left", padx=8)
        self.search_var.trace_add("write", lambda *a: self._schedule_search())
        ttk.Checkbutton(options, text="Include subfolders",
                        variable=self.recursive_var,
                        command=self._options_changed).pack(side="left",
                                                           padx=(8, 0))
        ttk.Checkbutton(options, text="Folders first",
                        variable=self.folders_first_var,
                        command=self._options_changed).pack(side="left",
                                                           padx=(8, 0))
        ttk.Label(options, textvariable=self.count_var,
                  style="Subtitle.TLabel").pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Extract Selected",
                   command=self.extract_selected).pack(side="left")
        ttk.Button(bottom, text="Extract All in View",
                   command=self.extract_all_in_view).pack(side="left",
                                                         padx=6)
        self.actions = ttk.Frame(bottom)    # the app adds its own buttons
        self.actions.pack(side="right")

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(paned, text="Folders", padding=6)
        paned.add(left, weight=1)
        self.domain_tree = ttk.Treeview(left, show="tree",
                                        selectmode="browse")
        scroll = ttk.Scrollbar(left, orient="vertical",
                               command=self.domain_tree.yview)
        self.domain_tree.configure(yscrollcommand=scroll.set)
        self.domain_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.domain_tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.domain_tree.bind("<<TreeviewOpen>>", self._on_tree_open)

        right = ttk.LabelFrame(paned, text="Files", padding=6)
        paned.add(right, weight=4)
        self.file_tree = ttk.Treeview(right, columns=_COLUMNS,
                                      show=("tree", "headings"),
                                      selectmode="extended")
        # These add up to less than the list is wide at the default window
        # size, so every column (the Location one included) is visible.
        widths = {"#0": 220, "kind": 100, "size": 70, "modified": 115,
                  "created": 115, "location": 170}
        for column, width in widths.items():
            self.file_tree.column(
                column, width=width, minwidth=50,
                anchor="e" if column == "size" else "w")
        self._update_headings()
        self.file_tree.configure(displaycolumns=_COLUMNS[:-1])

        vertical = ttk.Scrollbar(right, orient="vertical",
                                 command=self.file_tree.yview)
        horizontal = ttk.Scrollbar(right, orient="horizontal",
                                   command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=vertical.set,
                                 xscrollcommand=horizontal.set)
        pager = self._pager = ttk.Frame(right)
        self.prev_btn = ttk.Button(pager, text="◀ Previous page",
                                   command=lambda: self._turn_page(-1))
        self.next_btn = ttk.Button(pager, text="Next page ▶",
                                   command=lambda: self._turn_page(1))
        self.prev_btn.pack(side="left")
        ttk.Label(pager, textvariable=self.page_var,
                  style="Subtitle.TLabel").pack(side="left", padx=12)
        self.next_btn.pack(side="left")
        # Pack order matters: bottom scrollbar first, then right, then tree
        self._hscroll = horizontal
        horizontal.pack(side="bottom", fill="x")
        vertical.pack(side="right", fill="y")
        self.file_tree.pack(side="left", fill="both", expand=True)

        self.file_tree.bind("<Double-1>", self._on_double_click)
        self.file_tree.bind("<Return>", lambda e: self._open_selected())
        self.file_tree.bind("<BackSpace>", lambda e: self.go_up())
        self.file_tree.bind("<Control-a>", self._select_all)
        self.file_tree.bind("<Alt-Left>", lambda e: self.go_back())
        self.file_tree.bind("<Alt-Right>", lambda e: self.go_forward())
        for widget in (self.file_tree, self.domain_tree, self.search_entry,
                       self.location_entry):
            widget.bind("<Control-f>", self._focus_search)
        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.file_tree.bind(sequence, self._on_context_menu)
        self._menu = tk.Menu(self, tearoff=0)
        self._update_nav_buttons()

    def _make_icons(self):
        def icon(draw):
            image = tk.PhotoImage(master=self, width=16, height=16)
            draw(image)
            return image

        def page(color):
            def draw(image):
                image.put("#8a94a3", to=(3, 1, 13, 15))
                image.put("#ffffff", to=(4, 2, 12, 14))
                image.put("#c3cad4", to=(9, 1, 13, 5))
                image.put(color, to=(5, 9, 11, 12))
            return draw

        def folder(image):
            image.put("#b45309", to=(1, 3, 7, 5))
            image.put("#f59e0b", to=(1, 4, 15, 13))
            image.put("#fbbf24", to=(2, 6, 14, 12))
        return {"folder": icon(folder), "file": icon(page("#9ca3af")),
                "picture": icon(page("#059669")),
                "media": icon(page("#7c3aed")),
                "database": icon(page("#0e7490"))}

    def _icon_for(self, node):
        if node.is_dir:
            return self._icons["folder"]
        extension = node.name.rsplit(".", 1)[-1].lower() \
            if "." in node.name else ""
        if extension in _PICTURES:
            return self._icons["picture"]
        if extension in _MEDIA:
            return self._icons["media"]
        if extension in _DATABASES:
            return self._icons["database"]
        return self._icons["file"]

    # ── The folder tree ──────────────────────────────────────

    def set_index(self, index):
        """Show *index* (or nothing, if None)."""
        self.index = index
        self._request += 1
        self._scope = None
        self._history, self._position = [], -1
        self._clear_listing()
        self.domain_tree.delete(*self.domain_tree.get_children())
        self._tree_nodes.clear()
        self._node_item.clear()
        self._category_scope.clear()
        self._category_item.clear()
        self._update_nav_buttons()
        if index is None:
            self.location_var.set("")
            return
        self.domain_tree.insert(
            "", "end", iid="__ALL__",
            text=f"All Files ({index.file_count:,})")
        for category, domains in index.categories().items():
            item = f"__CAT__{category}"
            self._category_item[category] = item
            self._category_scope[category] = index.category_scope(category)
            self.domain_tree.insert("", "end", iid=item,
                                    text=f"{category} ({len(domains)})")
            for domain in domains:
                self._insert_folder(item, domain)

    def _insert_folder(self, parent_item, node):
        item = f"n{len(self._tree_nodes)}"
        self._tree_nodes[item] = node
        self._node_item[id(node)] = item
        self.domain_tree.insert(parent_item, "end", iid=item, text=node.name)
        if any(child.is_dir for child in node.children.values()):
            self.domain_tree.insert(item, "end", iid=item + _PLACEHOLDER,
                                    text="…")

    def _populate(self, item):
        """Create the sub-folder entries of *item* the first time it opens."""
        placeholder = item + _PLACEHOLDER
        if not self.domain_tree.exists(placeholder):
            return
        self.domain_tree.delete(placeholder)
        node = self._tree_nodes[item]
        for child in sort_nodes(
                [c for c in node.children.values() if c.is_dir]):
            self._insert_folder(item, child)

    def _on_tree_open(self, event):
        item = self.domain_tree.focus()
        if item in self._tree_nodes:
            self._populate(item)

    def _on_tree_select(self, event):
        selection = self.domain_tree.selection()
        if not selection or self.index is None:
            return
        item = selection[0]
        if item == "__ALL__":
            scope, recursive = self.index.root, True
        elif item.startswith("__CAT__"):
            scope, recursive = self._category_scope[item[7:]], False
        else:
            scope, recursive = self._tree_nodes.get(item), False
        if scope is None or scope is self._scope:
            return          # our own reveal() selecting what is showing
        self.navigate(scope, recursive)

    def _reveal(self, scope):
        """Select *scope* in the folder tree, opening its parents."""
        if scope is self.index.root:
            item = "__ALL__"
        elif scope.parent is None:
            item = self._category_item.get(scope.name)
        else:
            chain = []
            node = scope
            while node is not None and node.parent is not None:
                chain.append(node)
                node = node.parent
            chain.reverse()
            item = self._node_item.get(id(chain[0]))
            for node in chain[1:]:
                if item is None:
                    break
                self._populate(item)
                self.domain_tree.item(item, open=True)
                item = self._node_item.get(id(node))
        if item and self.domain_tree.exists(item):
            self.domain_tree.selection_set(item)
            self.domain_tree.see(item)

    # ── Navigating ───────────────────────────────────────────

    def navigate(self, scope, recursive=False, push=True):
        """Show the contents of *scope* (a folder node)."""
        if self.index is None:
            return
        self._scope = scope
        self.recursive_var.set(bool(recursive))
        if push:
            del self._history[self._position + 1:]
            self._history.append((scope, bool(recursive)))
            self._position = len(self._history) - 1
        self._set_search("")
        self._page = 0
        self._reveal(scope)
        self._update_nav_buttons()
        self.refresh()

    def go_back(self):
        if self._position > 0:
            self._position -= 1
            self._show_history()

    def go_forward(self):
        if self._position < len(self._history) - 1:
            self._position += 1
            self._show_history()

    def _show_history(self):
        scope, recursive = self._history[self._position]
        self.navigate(scope, recursive, push=False)

    def _parent_scope(self, scope):
        if scope is None or scope is self.index.root:
            return None
        if scope.parent is None:                    # a category
            return self.index.root
        if scope.parent is self.index.root:         # a domain
            return self._category_scope.get(category_for(scope.name),
                                            self.index.root)
        return scope.parent

    def go_up(self):
        parent = self._parent_scope(self._scope)
        if parent is not None:
            self.navigate(parent, False)

    def _update_nav_buttons(self):
        def state(enabled):
            return "normal" if enabled else "disabled"

        self.back_btn.configure(state=state(self._position > 0))
        self.forward_btn.configure(
            state=state(self._position < len(self._history) - 1))
        self.up_btn.configure(state=state(
            self.index is not None
            and self._parent_scope(self._scope) is not None))

    def _go_to_typed(self):
        if self.index is None:
            return
        text = self.location_var.get().strip().strip("/\\").replace("\\", "/")
        if text in ("", "All Files"):
            self.navigate(self.index.root, False)
            return
        node = self.index.get(text)
        if node is not None and node.is_dir:
            self.navigate(node, False)
        else:
            self._on_status(f"No such folder: {text}")

    def _on_double_click(self, event):
        item = self.file_tree.identify_row(event.y)
        node = self._items.get(item)
        if node is not None and node.is_dir:
            self.navigate(node, False)

    def _open_selected(self):
        nodes = self.selected_nodes()
        if len(nodes) == 1 and nodes[0].is_dir:
            self.navigate(nodes[0], False)

    # ── Sorting, searching and listing ───────────────────────

    def sort_by(self, key):
        """Sort by *key*; choosing the same column again reverses it."""
        if key == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, False
        self._page = 0
        self._update_headings()
        self.refresh()

    def _update_headings(self):
        for column, label in _HEADINGS.items():
            if _SORT_KEY[column] == self._sort_key:
                label += " ▼" if self._sort_desc else " ▲"
            self.file_tree.heading(
                column, text=label,
                command=lambda c=column: self.sort_by(_SORT_KEY[c]))

    def _options_changed(self):
        self._page = 0
        self.refresh()

    def _set_search(self, text):
        self._quiet = True
        try:
            self.search_var.set(text)
        finally:
            self._quiet = False

    def _schedule_search(self):
        if self._quiet or self.index is None:
            return
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(300, self._run_search)

    def _run_search(self):
        self._search_job = None
        if self._scope is None:     # searching before choosing a folder
            self._scope = self.index.root
            self._history, self._position = [(self._scope, True)], 0
            self._reveal(self._scope)
            self._update_nav_buttons()
        self._page = 0
        self.refresh()

    def refresh(self):
        """Rebuild the listing for the current folder, sort and search."""
        if self.index is None or self._scope is None:
            return
        self._request += 1
        request = self._request
        text = self.search_var.get().strip()
        future = self._executor.submit(
            self._compute, self.index, self._scope,
            self.recursive_var.get(), text, self._sort_key,
            self._sort_desc, self.folders_first_var.get())
        post_when_done(self._post, future, self._on_listing, request)

    @staticmethod
    def _compute(index, scope, recursive, text, key, descending,
                 folders_first):
        return sort_nodes(index.listing(scope, recursive, text), key,
                          descending, folders_first)

    def _on_listing(self, future, request):
        if request != self._request:
            return      # a newer folder, search or sort superseded this
        error = future.exception()
        if error is not None:
            self._on_status(f"Error loading: "
                            f"{str(error) or type(error).__name__}")
            return
        self._listing = future.result()
        self._render()

    # ── Showing the listing ──────────────────────────────────

    def _clear_listing(self):
        self._listing = []
        self._items.clear()
        self.file_tree.delete(*self.file_tree.get_children())
        self.count_var.set("")
        self.page_var.set("")
        self.prev_btn.configure(state="disabled")
        self.next_btn.configure(state="disabled")
        self._set_pager_visible(False)

    def _scope_name(self):
        scope = self._scope
        if scope is self.index.root:
            return "All Files"
        return self.index.path_of(scope) if scope.parent is not None \
            else scope.name

    def _set_pager_visible(self, visible):
        shown = bool(self._pager.winfo_manager())
        if visible and not shown:
            self._pager.pack(side="bottom", fill="x", pady=(4, 0),
                             before=self._hscroll)
        elif shown and not visible:
            self._pager.pack_forget()

    def _turn_page(self, step):
        self._page += step
        self._render()

    def _render(self):
        size = max(1, self._page_size())
        pages = max(1, -(-len(self._listing) // size))
        self._page = min(max(self._page, 0), pages - 1)
        chunk = self._listing[self._page * size:(self._page + 1) * size]

        flat = self.recursive_var.get() or bool(self.search_var.get().strip())
        # Results from many folders need to say where each one lives, so
        # Location sits right beside the name there.
        self.file_tree.configure(
            displaycolumns=(("location",) + _COLUMNS[:-1]) if flat
            else _COLUMNS[:-1])
        self.file_tree.delete(*self.file_tree.get_children())
        self._items.clear()
        for node in chunk:
            item = f"dir:{self.index.path_of(node)}" if node.is_dir \
                else node.file_id
            self._items[item] = node
            self.file_tree.insert(
                "", "end", iid=item, text=node.name,
                image=self._icon_for(node),
                values=(kind_of(node), self._size_text(node),
                        format_time(node.mtime), format_time(node.birth),
                        self.index.path_of(node.parent)))

        total = len(self._listing)
        self.location_var.set(self._scope_name())
        self.count_var.set(f"{total:,} items")
        self.prev_btn.configure(
            state="normal" if self._page > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if self._page < pages - 1 else "disabled")
        self._set_pager_visible(pages > 1)
        searching = bool(self.search_var.get().strip())
        if pages > 1:
            self.page_var.set(f"Page {self._page + 1} of {pages}")
            self._on_status(
                f"Showing {len(chunk):,} of {total:,} "
                f"{'matches' if searching else 'items'} "
                f"(page {self._page + 1} of {pages}). Use the page buttons "
                "or narrow the search to see the rest.")
        else:
            self.page_var.set("")
            self._on_status(
                f"{total:,} {'matches' if searching else 'items'} in "
                f"{self._scope_name()}.")
        self._update_nav_buttons()

    @staticmethod
    def _size_text(node):
        if node.is_dir and not node.total:
            return ""       # an empty folder has nothing worth showing
        return format_size(node.weight)

    # ── Selection and extraction ─────────────────────────────

    def selected_nodes(self):
        return [self._items[i] for i in self.file_tree.selection()
                if i in self._items]

    def file_ids_for(self, nodes):
        """The file IDs of *nodes*; a folder stands for everything in it."""
        seen, ids = set(), []
        for node in nodes:
            files = self.index.walk_files(node) if node.is_dir else (node,)
            for file_node in files:
                if file_node.file_id not in seen:
                    seen.add(file_node.file_id)
                    ids.append(file_node.file_id)
        return ids

    def extract_selected(self):
        nodes = self.selected_nodes()
        if not nodes:
            messagebox.showinfo("Info", "Select files to extract first.")
            return
        ids = self.file_ids_for(nodes)
        if not ids:
            messagebox.showinfo("Info", "The selection contains no files.")
            return
        self._on_extract(ids)

    def extract_all_in_view(self):
        ids = self.file_ids_for(self._listing)
        if not ids:
            messagebox.showinfo("Info", "No files to extract.")
            return
        if len(ids) > 100 and not messagebox.askyesno(
                "Confirm", f"Extract {len(ids):,} files?"):
            return
        self._on_extract(ids)

    def _select_all(self, event=None):
        self.file_tree.selection_set(self.file_tree.get_children())
        return "break"

    def _focus_search(self, event=None):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    # ── Context menu and properties ──────────────────────────

    def _on_context_menu(self, event):
        item = self.file_tree.identify_row(event.y)
        if not item:
            return
        if item not in self.file_tree.selection():
            self.file_tree.selection_set(item)
        node = self._items.get(item)
        menu = self._menu
        menu.delete(0, "end")
        if node is not None and node.is_dir and \
                len(self.file_tree.selection()) == 1:
            menu.add_command(label="Open",
                             command=lambda: self.navigate(node, False))
        menu.add_command(label="Extract…", command=self.extract_selected)
        menu.add_separator()
        menu.add_command(label="Copy name",
                         command=lambda: self.copy_text(node.name))
        menu.add_command(label="Copy path",
                         command=lambda: self.copy_text(
                             self.index.path_of(node)))
        menu.add_command(label="Properties",
                         command=lambda: self.show_properties(node))
        menu.tk_popup(event.x_root, event.y_root)

    def copy_text(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def properties_text(self, node):
        lines = [f"Name:      {node.name}",
                 f"Kind:      {kind_of(node)}",
                 f"Location:  {self.index.path_of(node.parent) or '-'}",
                 f"Domain:    {self.index.domain_of(node)}"]
        if node.is_dir:
            lines.append(f"Contains:  {node.count:,} files, "
                         f"{format_size(node.total)}")
        else:
            lines.append(f"Size:      {format_size(node.size)} "
                         f"({node.size:,} bytes)")
        lines.append(f"Modified:  {format_time(node.mtime) or 'unknown'}")
        lines.append(f"Created:   {format_time(node.birth) or 'unknown'}")
        if not node.is_dir:
            lines.append(f"File ID:   {node.file_id}")
        return "\n".join(lines)

    def show_properties(self, node):
        messagebox.showinfo("Properties", self.properties_text(node))

    # ── Shutdown ─────────────────────────────────────────────

    def cancel_timers(self):
        if self._search_job is not None:
            self.after_cancel(self._search_job)
            self._search_job = None

    def close(self):
        self.cancel_timers()
        self._executor.shutdown(wait=False)
