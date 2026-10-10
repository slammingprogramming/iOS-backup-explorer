# Testing

The suite has about 1,140 tests and runs in a few minutes. It uses only
**generated** data: nothing from a real device is, or may ever be, in the
repository.

```bash
python -m unittest discover -s tests -t .            # everything
python -m unittest tests.test_health                  # one module
python -m unittest tests.test_health.WorkoutTests     # one class
python -W error::ResourceWarning -m unittest discover -s tests -t .
```

The last form turns "unclosed database" warnings into failures; keep the suite
clean under it.

## Layout

| Kind | Files | What they do |
|---|---|---|
| **Fixtures** | `tests/fixture_*.py` | Build invented databases and files that follow the layout iOS uses, trimmed to what a reader looks at, *including the awkward cases* (missing columns, odd types, empty values, a missing table) |
| **Reader tests** | `tests/test_<app>.py` | Test a reader with no window: the numbers, the conversions, the edge cases, the export files |
| **Window tests** | the same modules, classes using `AppGuiCase` | Open a generated backup in the real window and drive the tab: it appears only with data, shows the rows, searches, exports, extracts the originals, works for an encrypted backup. They skip themselves when there is no display |
| **Backup tests** | `test_backup_session.py`, `test_unencrypted.py`, `test_folder_backup.py`, `test_gui*.py`, `test_mount.py` | Build a real encrypted backup (`fixture_backup.py`, with a real key bag and AES) and run it through the real decryption library; open unencrypted and extracted folders; the file browser; mounting |
| **Helpers** | `tests/gui_apps.py`, `tests/keyed_builder.py` | `AppGuiCase`; a writer of `NSKeyedArchiver` lists |
| **Checks** | `tools/check_attribution.py`, `tools/check_version.py` | Run in CI, and from `test_version.py` |
| **Release** | `test_release.py` | The release notes, the tag check and the archives (`tools/release.py`), and the shape of `release.yml` (who may write, what runs first) |

### `AppGuiCase`

```python
class WindowTests(AppGuiCase):
    def test_the_tab(self):
        self.open_files(my_fixture.backup_files())     # [(domain, path, bytes)]
        tab = self.show_tab("Widgets")                  # select the tab
        self.wait_for(lambda: tab.datasets, "the tables")
        ...
```

`open_files(files, encrypted=False)` writes a real backup folder (encrypted
or not), opens it in the window and waits for the index; `self.ids[(domain,
path)]` gives a file's ID. Message boxes are replaced by a list,
`self.dialogs`, so tests can assert on them. `ask_export` is patched to return
a chosen `(format, scope, folder)`.

## What a good test checks

- The **numbers**, with the expected value written out (not computed with the
  function under test). A test that compares a helper with itself proves
  nothing; write the literal `DTSTART:20250828T000640Z`.
- **Every branch** a real database could take: a column missing, a value
  `NULL`, a value of the wrong type, a table missing, a damaged file.
- **Safety**: hostile names, paths with `..`, HTML in a title, addresses that
  are not `http(s)`.
- **The window**: that what the reader found reaches the screen, and that
  exports and extractions are asked for the right files.

## Mutation checks

Passing tests only matter if they would *fail* for a wrong program. Before
finishing a reader, break it on purpose, one place at a time, in a **copy** of
the repository, and run that module's tests:

```python
for (file, original, broken, test_module) in mutations:
    copy the repo (without .git) to a temporary folder
    replace `original` by `broken` in `file` (once)
    run: python -m unittest test_module
    KILLED if it fails, SURVIVED if it passes
```

Typical mutations: swap two values in a mapping, drop a `NULL` guard, change a
`>=` to `<=`, remove a sort, skip a filter, multiply by the wrong factor. Every
**survivor** is either a missing test (add one, then re-run) or an *equivalent
mutant* (a change that cannot alter behaviour, such as removing a redundant
check) that you can note and move on from. The suite as released had every
mutation of the new readers killed except a handful of equivalents.

## Checking against a real backup (without publishing it)

Readers are written against a real backup, then checked against it:

1. Survey: table and column names and row counts only.
2. Read with your reader and compare counts and a few values with the raw
   database.
3. Look for an *independent* anchor that proves the meaning of a column (for
   example the active energy of each Health day matched the phone's own
   activity summary exactly).
4. Write the fixture to reproduce what you learned, with invented values.

Keep what you see in your own notes. **Never commit it, paste it, or post it.**

## Continuous integration

`.github/workflows/tests.yml` runs the suite on Ubuntu and Windows with Python
3.9 and 3.13, once without the optional packages and once with them.
`attribution.yml` runs `tools/check_attribution.py` (the original author's credit
and the licence notices must be intact) and `tools/check_version.py` (the
version is consistent). `release.yml` runs both of these workflows again on a
tagged commit before it publishes a release
([Versioning and releases](VERSIONING.md)).
