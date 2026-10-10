# Architecture

iOS Backup Explorer is plain Python (about 17,000 lines in 70 files, plus the
tests) with **no build step** and one required dependency. This page maps the
code so that you can find your way around and know the rules that keep it
correct.

## The big picture

```
 ios_backup_explorer.py        the window, BackupSession, the three backends
   |-- browser_panel.py        the Files tab (file manager)
   |-- file_index.py           the backup as a tree of nodes (no GUI)
   |-- folder_backup.py        the backend for already-extracted folders
   |-- backup_mount.py         optional: mount a backup (FUSE / WinFsp)
   |-- ui_util.py              thread-safe callbacks that hold panels weakly
   `-- ios_apps/               everything for the app tabs
         registry.py           the list of tabs and when each appears
         context.py            what a tab gets from the window (AppContext)
         panel_base.py         AppPanel: loading, exporting, extracting
         records*.py           the shared table framework
         <app>.py              a READER for an app (no GUI)
         <app>_view.py         the PANEL (tab) for an app
         <app>_export.py       exporters, for the apps that have their own
         common.py, export_util.py, dialogs.py, keyed_archive.py, ics.py,
         imaging.py, audio_tools.py, pdf_export.py   shared helpers
 tools/                        checks, the release tool, and the demo backup /
                               screenshot makers
 tests/                        the test suite and its generated fixtures
```

**The rule of the design:** a *reader* knows an app's database and nothing
about windows; a *panel* knows windows and nothing about the database layout.
Readers are therefore testable without a display, and panels are small.

## Opening a backup

`BackupSession` (in `ios_backup_explorer.py`) is the one object that touches the
backup. It runs everything on **one dedicated worker thread** (a
single-thread executor), because the decryption library keeps a SQLite
connection that may only be used on the thread that made it. Each method
(`open`, `scan`, `extract`, `extract_all`, `export_files`) returns a `Future`.

`detect_backup(folder)` decides what the folder is and returns one of:

| Constant | Meaning | Backend |
|---|---|---|
| `ENCRYPTED` | `Manifest.plist` says encrypted | `EncryptedBackend` (wraps `iphone_backup_decrypt`) |
| `UNENCRYPTED` | `Manifest.db` plain | `PlainBackend` (opens the index read-only, `immutable`) |
| `EXTRACTED` | domain folders, no manifest | `FolderBackend` (`folder_backup.py`) |

All three offer the same few methods (`manifest_db_cursor`, `extract`,
`materialize`, `close`), and the index rows they give are the same:
`(file_id, domain, relative_path, flags, size, mtime, birth)`. `FolderBackend`
builds an in-memory `Files` table by walking the disk and never follows
symbolic links or accepts a path that leaves the folder.

`FileIndex` (`file_index.py`) turns those rows into a tree of `Node`s (a
folder has `children`, a file has `file_id` and `size`) with natural sorting,
search, category grouping and kind names.

## The Files tab

`browser_panel.FileBrowserPanel` is the file manager: it takes the index and
callbacks for status and extraction, and knows nothing else. Large operations
(searching, listing) run on a thread pool and come back through the window's
post queue.

## Threads (the rules)

1. **Only the Tk thread touches Tk.** Workers never call into widgets; they put
   work on a queue (`post`) that the Tk thread drains.
2. **One thread per database.** A panel's `SqliteSource` runs every query on its
   own single thread (`app-db`); the reader lives there. A connection is never
   used from another thread.
3. **Callbacks hold panels weakly** (`ui_util.post_when_done`, `weak_notifier`).
   A closure that captured a widget would keep it alive inside a worker's work
   item; if the widget was closed meanwhile, the worker would free it and
   finalise its Tk variables off the Tk thread, which Tk forbids. A panel that
   is gone when a result arrives is skipped. Panels also set `_closed`.
4. **No worker closure captures `self`.** Pass what it needs.

## The app tabs

### AppContext

Each panel gets one `AppContext` (`ios_apps/context.py`): the session, `post`,
`set_status`, `extract`, the `index`, the `backup_dir`, and helpers:

- `workspace`: a private temporary folder for working copies (deleted when the
  backup closes);
- `copy_database(path, folder, local_name=None)`: copy a database (with its
  `-wal`/`-shm`) into the workspace;
- `fetch_local(paths, folder)`: copies of files for opening or previews, each
  call in a folder of its own;
- `fetcher(...)` / `copier()`: functions for exporters to pull files out of the
  backup from a worker thread;
- `file_id_for(path)`, `save_file(path, destination)`;
- `load_contacts(callback)`: the address book, loaded once and shared.

### AppPanel

`ios_apps/panel_base.py`. A panel declares what it reads and the base class
does the rest. Class attributes: `DATABASE` or `DATABASES`, `FOLDER` (the
working-copy folder), `WITH_CONTACTS`, `LOADER`, `MISSING`, `OPTIONAL`. Hooks:
`discover(index)` (files whose names depend on the backup: one database per
account, one file per recording), `local_name(path)` (give same-named files
different working names), `on_loaded(data)`.

Flow when the tab is first shown (`activate`): copy the main database and the
others (`DATABASES`) to the workspace, wait for the address book if
`WITH_CONTACTS`, open a `SqliteSource`, run `LOADER(conn, book, index)` on the
database thread (it returns `(reader, first data)`), and hand the data to
`on_loaded` on the Tk thread. A main "database" that is really a plist is
fine: the connection is simply never queried.

The base class also provides `run_query`, `schedule` (debounced timers),
`start_export` (load on the DB thread, write on a new thread, report on the Tk
thread), `extract_originals_of`, `open_backup_file`, `save_backup_file`,
`launch_local` (opens only an allow-listed set of safe file types).

### The table framework

Most tabs are just a reader that returns tables:

- `records.Column(key, heading, width, kind, anchor, format)`: `kind` is
  `text`, `date`, `day`, `number`, `duration` or `size`; `format(row)` can
  override how a cell is shown.
- `records.Dataset(key, title, columns, rows, sort, details, actions, formats,
  file_formats, note)`: one table. `rows` are plain dicts. `formats` adds
  export formats whose writer needs only the rows (`{key: (label,
  writer(path_base, rows))}`); `file_formats` adds formats that copy files out
  of the backup (`writer(folder, rows, copy_file)`).
- `records_export`: CSV, HTML, text and JSON writers and `export()`.
- `records_view.RecordsPanel(AppPanel)`: the generic tab: table chooser, search,
  sorting (rows with no value always last), paging (2,000 rows), details pane,
  actions, export and extraction.
- `records.fetch_dicts(conn, table, columns, ...)`: rows as dicts; a missing
  column is `None` and a missing table is no rows, so one reader copes with
  every iOS version. `open_copies(conn, paths)` opens the other databases next
  to the main one.

A concrete tab is then a few lines:

```python
def _load(conn, book, index):
    reader = MyReader(conn)
    return reader, reader.datasets()

class MyPanel(RecordsPanel):
    DATABASE = my.DATABASE
    ORIGINALS = (my.DATABASE,)
    FOLDER = "my"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no ..."
```

### The registry

`ios_apps/registry.py` has `APPS`, a list of `AppEntry(key, title, detect,
create)`. `detect(index)` says whether the backup has the data; `create`
builds the panel. The window adds a tab for each entry that detects.

## Other pieces

- **Notes** (`notes.py`) decodes the notes' compressed protobuf text and
  attributes; **messages** (`messages.py`) decodes `attributedBody`;
  `keyed_archive.py` decodes `NSKeyedArchiver` lists; `ics.py` writes
  iCalendar; `contacts_export.py` writes vCard.
- **Dates:** `common.apple_time` (Cocoa seconds or nanoseconds to Unix time),
  `common.unix_time` (plist dates), `common.utc_datetime` (any year, even on
  Windows), `common.format_datetime`.
- **Safe opening:** `common.OPENABLE` is the allow-list of file types the
  program hands to the operating system; anything else raises `NotOpened`.
- **Names:** `export_util.safe_filename` and friends; `folder_backup`/
  `build_output_path` for extraction paths (refuses `..`, sanitises Windows
  names, handles collisions).

## Where the numbers and formats come from

See [How an iPhone backup is built](HOW_BACKUPS_WORK.md) and
[Where the data comes from](DATA_SOURCES.md).
