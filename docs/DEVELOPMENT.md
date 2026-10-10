# Development guide

How to set up, how to add a tab, and the conventions the code follows. Read
[Architecture](ARCHITECTURE.md) first for the map.

## Setting up

```bash
git clone https://github.com/slammingprogramming/iOS-backup-explorer.git
cd iOS-backup-explorer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-optional.txt
python -m unittest discover -s tests -t .
python ios_backup_explorer.py
```

To try the program without a real backup, make the invented demo backup:

```bash
python tools/make_demo_backup.py "/tmp/Demo iPhone Backup"
```

and open that folder. See [SCREENSHOTS.md](SCREENSHOTS.md).

## The conventions

- **Python 3.9 compatible.** CI runs 3.9 and 3.13. No `match`, no `X | Y` types,
  and *no backslash inside an f-string expression* (valid only from 3.12): put
  the text in a variable or use a helper.
- **No new required dependency.** The program must stay a few plain files that
  anyone can audit. Optional packages are loaded lazily and the program says
  what is missing.
- **No network access, ever.** Not for names, maps, updates or analytics. A pull
  request that adds any is rejected.
- **Never hide failure.** A missing table or column gives fewer rows, not an
  exception (use `fetch_dicts`, `sqlite_rows`); but a corrupt database is
  reported to the user.
- **Never trust the backup.** Its contents can be hostile: names go through
  `safe_filename`, paths through `build_output_path`, HTML is escaped, only
  `http(s)` links are opened, only allow-listed file types are opened.
- **Licence headers.** Every source file starts with
  `# SPDX-License-Identifier: AGPL-3.0-or-later` and the copyright line
  `# Copyright (C) 2026 slammingprogramming and contributors`. Never remove or
  change the original author's notices ([NOTICE](../NOTICE),
  [LICENSE-MIT](../LICENSE-MIT), [AUTHORS](../AUTHORS)).
- **Match the surrounding style:** comment density, naming, idiom. Line length
  about 79.
- **Real data stays out of the repository.** Fixtures are invented. Do not
  paste output of a real backup into code, tests, issues or commits (counts and
  shapes are fine, contents are not).

## Adding a tab

Say you want a **Widgets** tab that reads `HomeDomain/Library/Widgets/w.db`.

### 1. Survey the data

Open the real database with any SQLite browser (or a few lines of Python that
print table and column names and row counts, *not* contents). Note the tables,
what the numbers mean and, importantly, **an independent check** that proves
your reading (a total that must match another table, a count, a known value).
Do not guess meanings: show only what you can verify, and leave the rest out.

### 2. Write the reader

`ios_apps/widgets.py`, no GUI imports:

```python
from .records import Column, Dataset, fetch_dicts

DATABASE = "HomeDomain/Library/Widgets/w.db"

def datasets(conn):
    rows = [{"name": r["ZNAME"] or "", "added": apple_time(r["ZDATE"])}
            for r in fetch_dicts(conn, "ZWIDGET", ["ZNAME", "ZDATE"])]
    if not rows:
        return []
    return [Dataset("widgets", "Widgets", [
        Column("name", "Name", 300),
        Column("added", "Added", 140, "date")],
        rows, sort=("added", True))]

class WidgetsReader:
    def __init__(self, conn):
        self.conn = conn
    def datasets(self):
        return datasets(self.conn)
```

Tips: use `apple_time` for 2001-epoch dates (and `unix_time` for plist
dates); keep `None` for unknown values (they sort last); give a `details=`
function for the details pane; add `formats=` for special exports.

### 3. Write the panel

`ios_apps/widgets_view.py` (the licence header, then):

```python
from . import widgets as m
from .records_view import RecordsPanel

def _load(conn, _book, _index):
    reader = m.WidgetsReader(conn)
    return reader, reader.datasets()

class WidgetsPanel(RecordsPanel):
    DATABASE = m.DATABASE
    ORIGINALS = (m.DATABASE,)
    FOLDER = "widgets"
    LOADER = staticmethod(_load)
    MISSING = "This backup has no widgets."
```

Needs names from the address book? Add `WITH_CONTACTS = True` and use the
`book` argument. Needs several or variable files? Override `discover(index)`
(and `local_name` if names clash).

### 4. Register it

In `ios_apps/registry.py` add the import, a `_create_widgets` function and an
`AppEntry("widgets", "Widgets", lambda index: _has_file(index,
widgets.DATABASE), _create_widgets)`.

### 5. Test it

Add a generated fixture and a test module (see [Testing](TESTING.md)):
`tests/fixture_widgets.py` builds the database with invented rows (include the
awkward cases: missing values, odd types, a missing table); `tests/
test_widgets.py` tests the reader and, with `AppGuiCase`, the tab in the real
window (appears only with data, shows the rows, search, export, extract
originals, works for an encrypted backup).

### 6. Add it to the checks and the docs

- `tools/check_attribution.py`: add the new files to the list.
- `CHANGELOG.md`: an entry under *Unreleased* ([Versioning](VERSIONING.md)).
- `docs/apps/`: describe the tab and add it to the table in `apps/README.md`
  and to [Where the data comes from](DATA_SOURCES.md).
- `tools/demo/`: give the demo backup some invented widgets and `tools/
  make_screenshots.py` a picture of the tab ([SCREENSHOTS.md](SCREENSHOTS.md)).

### 7. Mutation-check it

Break your reader in each place that matters (a conversion, a filter, a sort)
and confirm the tests fail; see [Testing](TESTING.md#mutation-checks).

## Adding an export format

- Rows-only formats: add to `Dataset.formats` a `(label, writer(path_base,
  rows))`; the writer returns the list of paths.
- Formats that copy files (audio, pictures): `Dataset.file_formats` with
  `writer(folder, rows, copy_file)`, returning paths or `(paths, notes)`.
  `copy_file(backup_path, directory, name)` copies one file out of the backup and
  says whether it was there.

## Releasing

See [Versioning and releases](VERSIONING.md).
