# Changelog

All notable changes to iOS Backup Explorer will be documented in this file.

iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens) by
Eyyup (Eric) Gunes. Entries below the fork point record the original project's history.

## [Unreleased]

### Fixed
- **The status bar could tell you to "Click Open Backup" after the backup was open.** Choosing a folder schedules a check of its kind 300 ms later; an open that finished sooner than that (a small backup, a fast disk) was followed by that late message over its own. Opening now applies the check first. This was also the cause of a test (`Save as JPEG`) that failed now and then on CI: its "Saved" message was overwritten before the test saw it

### Changed
- When a test of a window times out, it now says which dialogs had been shown, so a failure on a machine we cannot look at is explained by its log

## [2.3.2] - 2026-10-14

**The first release since 2.2.0 that is published with everything in it.** The releases of 2.3.0 and 2.3.1 could not be published (the tests of 2.3.0 failed on Linux; one Windows job of 2.3.1 ran for 21 minutes and failed, on a run that was otherwise green), so what they hold comes out here: **iOS 12 backups are read and checked** against a real iOS 12.4.8 backup (Reminders, Permissions, Safari, Health and Maps differences handled, the Keychain accounted for item by item, Maps places less sure than the rest and documented as such), and **anyone can help without sharing anything private** (issue forms, a guide, and tools that print the shape of a backup and none of its contents). The full lists are in the 2.3.0 and 2.3.1 sections of the changelog. The program itself is unchanged from 2.3.1; this release repairs the project's automation and writes down why the code-scanning findings are not weaknesses.

### Changed
- The workflows use the current versions of the GitHub actions (`checkout` 7, `setup-python` 7, `upload-artifact` 7), which also ends the "Node.js 20 is deprecated" warning of every run. A test keeps every workflow on the same version of each action
- Dependabot no longer raises the minimum versions in `requirements*.txt` to the newest release (`versioning-strategy: increase-if-necessary`): fpdf2 2.8.9 and pillow-heif 1.8.1 need Python 3.10, and the program supports 3.9, where pip already picks the newest version that fits
- [SECURITY.md](SECURITY.md) lists the code-scanning findings that are by design (AES in ECB mode as the block operation of key wrapping and GCM, and the exports of your own data) and why

## [2.3.1] - 2026-10-14

A fix to the tests only; the program itself is unchanged from 2.3.0.

### Fixed
- **The Linux jobs of CI failed on 2.3.0**: the tests of `tools/compat_report.py` open a window and had lost their "needs a display" skip when the password-window tests were added, so they failed wherever there is no display (Windows always has one, which hid it). They skip again
- A test of the Messages tab assumed a wrapped line could never be as wide as the limit plus two spaces of padding; a line wrapped right up to the limit is wider, which fonts on Linux produce. The test now allows the four spaces of padding every line has. The tab itself was always correct

### Changed
- [Testing](docs/TESTING.md) explains how to run the suite without a display, as CI does, and with one on Linux, before sending a change

## [2.3.0] - 2026-10-14

**iOS 12 backups are now read and checked** against a real iOS 12.4.8 backup (every tab; the counts match the raw tables), with the Reminders, Permissions, Safari, Health and Maps differences of that version handled, and the Keychain of that backup accounted for item by item. **Anyone can now help without sharing anything private**: issue forms, a guide and three tools that print the shape of a backup and none of its contents. Maps on iOS 12 is less sure than the rest, and the documentation says why.

### Added
- **Ways to help without sharing anything private.** Issue forms for a bug, a feature, a *compatibility report*, *a tab that is empty or wrong* (with a layout report), *naming a Health data type*, *volunteering to test another iOS version* and a documentation problem; every form opens with the rule that nobody should post a backup, its password or anything in it, and asks for counts and layouts. They come with three tools that print the shape of a backup and none of its contents: `tools/schema_report.py` (tables, columns and row counts of the databases the program reads, with `--sql` the `CREATE` statements, `--find` to locate an app's database), `tools/health_kinds_report.py` (the Health data types that cannot be named) and the existing `tools/compat_report.py`. A new page, [How to help](docs/HELPING.md), explains them, how to read the output before posting it and what to do if something private was posted by mistake
- **Repository files**: labels the forms attach (`.github/labels.yml`, created by the *Labels* workflow or `tools/sync_labels.py`, which only creates or updates), Dependabot for the actions and the Python packages, `CODEOWNERS` that watch the credit and licence files, `SUPPORT.md`, a pull request checklist that asks what a change was verified on, and an issue chooser that sends security problems to private reporting. Tests (`tests/test_github_templates.py`) keep the forms consistent with the tools, the labels and the tab list
- **iOS 12 backups are checked** against a real iOS 12.4.8 backup (every tab; the counts of Messages, Calls, Contacts, Voicemail, Calendar, Reminders, Safari bookmarks, Voice Memos, Wi-Fi, Bluetooth, data usage, Accounts, Privacy, Apps and Keychain match the raw tables), and what was found is handled:
  - **Reminders of iOS 12 and earlier**, which live in the Calendar database, now show in the Calendar tab as the tables *Reminders* and *Reminder lists* (67 of 67)
  - **Privacy**: the older permissions table (`allowed`) is read (17 permissions that did not show)
  - **Safari**: the history and open tabs of iOS 12, which live in Safari's own app folder, are read (layout only: the backup had none)
  - **Health**: a database that does not name its kinds (iOS 12 and earlier) is named from a table of the 172 kind numbers that the iOS 16.7 and 26.6 databases both name identically. The sleep, body measurements and nights of the iOS 12 backup now show
  - **Maps of iOS 12 and earlier**: the places and searches in `GeoBookmarks.plist` (Apple's undocumented binary records, read by field numbers identified on a real iOS 12.4 backup and checked with its owner) show as *Saved places* and *Searches*. Less sure than the rest: the file does not say which places are favorites, and entries of kinds not identified yet are counted, not shown; the history file is not read (see [iOS versions](docs/IOS_VERSIONS.md))
- `tools/compat_report.py --password-window` asks for the password in a small window (for when there is no terminal to type in), and an extracted folder that holds the backup's key bag now says at once that it needs the password instead of waiting for it

## [2.2.0] - 2026-10-11

Much more of **Health** is read (sleep per night, medications, the contents of health records and the files of clinical documents, hearing tests, symptoms and cycle tracking, awards, friends' activity), the program is checked against real backups of **iOS 16.7 and 26.6** (every tab, with the Health database of iOS 26 read in full), and four things that broke or showed nothing on iOS 26 are fixed. Medication names, forms and ingredients were confirmed by the owner of the backup; dose statuses other than "Not answered" and "Taken" are still shown as numbers.

### Added
- **Sleep per night** in the Health tab: the sleep stages added up for each night, placed on the day you woke up by the clock where the phone was, overlapping records of two devices counted once. It needs a time zone database; macOS and Linux have one, **Windows needs the optional `tzdata` package** (`pip install tzdata`, now in `requirements-optional.txt`), and without it the table says why it is missing. See [Health data](docs/HEALTH.md#sleep-per-night)
- **More of the Health database**: medications and their dose log; the contents of health records (lab results, immunizations, conditions and allergies, prescriptions, clinical documents, whose files can be exported); awards; sleep schedules; hearing tests (audiograms); events, symptoms and cycle tracking; and the activity and workouts that friends in Activity sharing sent. What is still not covered (ECG waveforms, the files inside clinical records, a few unverified values) is listed in [Health data](docs/HEALTH.md#still-not-covered)
- **The files of clinical documents** (PDF reports, notes as HTML or RTF) can be saved from the Health tab: Health keeps them in Apple's encrypted archive format, with the key in its own database, and they are opened and checked before they are written (*Clinical documents*, *Export...*, *The documents' files*; a *Files* column counts them). Checked byte for byte against another implementation of the format on all 13 files of a real backup; the Health database of an iOS 26 backup is now read in full too (**the first time it was examined**)
- **`tools/compat_report.py`**: opens a backup, visits every tab and prints only counts and the program's own messages, so a report of what a backup shows can be shared without any of its content
- **[iOS versions](docs/IOS_VERSIONS.md)**: the aim of covering every iOS version, which were checked on real backups (iOS 16.7 and 26.6 this time), what differs between them, and how to help

### Fixed
- **Health on iOS 26**: the workout routes were not found (the table that links a workout to its route names its columns differently); medication doses now show their unit
- **iOS 26 backups**: Reminders (now in an app group, with the lists in another table) were not found; the data-usage table failed without Wi-Fi counters; the places in Maps guides were not found under their renamed join table
- Opening an encrypted backup is much faster for large backups: the lookup of files by path used a full scan of the manifest for every file; it is indexed now

### Changed
- The "Checked" column of [Where the data comes from](docs/DATA_SOURCES.md) now says which tabs were verified on real backups and on which iOS version. Photos, Voice Memos, Maps (favorites, guides, history), Books (collections) and Reminders were run against a real iOS 26 backup; Podcasts still has no real library to test against

## [2.1.0] - 2026-10-11

Two things that a backup holds but that were closed until now: the **keychain**
(saved passwords, Wi-Fi passwords, certificates and keys) and **notes locked
with a password**, with their attachments. The Keychain tab was run on a real
encrypted backup; the locked notes were not (none of the backups at hand held
one), and the documentation says so.

### Added
- **Credits** for the projects whose published research the Keychain tab and the opening of locked notes build on (iphone-dataprotection, the Apple Cloud Notes Parser, hashcat, Apple's Platform Security Guide, the RFC 3394 and NIST SP 800-38D standards, PyCryptodome), in [AUTHORS](AUTHORS), [NOTICE](NOTICE) and the README. No code was copied from them
- **A Keychain tab.** The saved passwords of an encrypted backup (websites, apps, Wi-Fi networks), certificates and keys, with every stored attribute, shown in the clear; items that are locked to the phone ("this device only", which no backup can open) are counted and explained in a table of their own. The tab opens at once for an encrypted backup. **Extract Entire Backup** from an encrypted backup now also keeps the backup's key bag in a small `Manifest.plist`, so the extracted folder can be opened again here with the backup password and still show its keychain (the key bag is locked by the password; no password or key is written). Exporting passwords asks you to confirm and warns first, and nothing readable is written to the working folder. Opening a folder that holds only such a `Manifest.plist` now counts as an extracted backup. **Run on a real encrypted backup**: every item that a backup can open opened, and only the "this device only" items stayed locked (see [docs/apps/keychain.md](docs/apps/keychain.md))
- **Locked notes can be opened.** A note protected with a password in Notes is listed as *(locked)*; click it and type its password, and it opens, along with every other note locked with the same password. The passwords you type are remembered in memory while the backup is open, so you are asked again only for a note with a different password; *Unlock notes...* tries one password on all of them, and *Forget passwords* locks them again. Searching includes the open notes. Exporting a selection with locked notes tries the remembered passwords, then lets you try more, one after another, until all are open, or export everything but the still-locked ones, or only the locked notes that are open. The files attached to a locked note open with it (previews, Open, Save and exports; *Extract original files* still gives them locked). **Not yet checked against a real locked note** (none of the backups used had one): see [docs/apps/notes.md](docs/apps/notes.md#locked-notes)

## [2.0.1] - 2026-10-10

The first release made by GitHub Actions, and a fix for tabs that read only property lists. Three pre-releases (2.0.1-rc.1 to rc.3, below) tried the release workflow; only rc.3 was published.

### Added
- **Releases are made by GitHub Actions.** Pushing a version tag (`v2.1.0`) checks that the tag matches `__version__` and the changelog, runs the tests, and publishes a GitHub release with the changelog section as its notes, a `.zip` and a `.tar.gz` of the tagged files, and a `SHA256SUMS` file; a tag with a suffix (`v2.1.0-rc.1`) makes a pre-release. The steps are in `tools/release.py`, described in [docs/VERSIONING.md](docs/VERSIONING.md)

### Fixed
- **Tabs whose data is only property lists did not load with the older SQLite that comes with Python 3.9 on Windows**: Screen Time, and Network, Accounts, Health and Privacy when the backup held only plists and no database, showed "file is not a database". The copy of the main file is no longer required to be a database
- A backup folder whose file or domain names hold a backslash is refused on every system, as it was on Windows (on Linux and macOS the name was accepted)
- Python 3.9 compatibility of the release tool and of two window tests; two tests of the suite that failed only on GitHub's machines

## [2.0.1-rc.3] - 2026-10-10

The third try. rc.2 got further (the tests pass on Linux with Python 3.9) but
was stopped by two tests that only fail on GitHub's machines. The program is
the same as rc.2.

### Fixed
- Two tests of the test suite itself: one compared file paths without allowing for Windows' short folder names, and one asked for the logged-in user where there is no terminal

## [2.0.1-rc.2] - 2026-10-10

The second try at a pre-release through the release workflow: the first
(2.0.1-rc.1) was stopped, as designed, by tests that failed on Python 3.9 and
on Linux. Nothing was published for it.

### Fixed
- **Tabs whose data is only property lists did not load with the older SQLite that comes with Python 3.9 on Windows**: Screen Time, and Network, Accounts, Health, Privacy when the backup held only plists and no database, showed "file is not a database". The copy of the main file is no longer required to be a database
- A backup folder whose file or domain names hold a backslash is refused on every system, as it was on Windows (on Linux and macOS the name was accepted)
- Python 3.9 compatibility of the release tool and two window tests

## [2.0.1-rc.1] - 2026-10-10

A pre-release that tries out the new release workflow. The program itself is
the same as 2.0.0.

### Added
- **Releases are made by GitHub Actions.** Pushing a version tag (`v2.1.0`) checks that the tag matches `__version__` and the changelog, runs the tests, and publishes a GitHub release with the changelog section as its notes, a `.zip` and a `.tar.gz` of the tagged files, and a `SHA256SUMS` file; a tag with a suffix (`v2.1.0-rc.1`) makes a pre-release. The steps are in `tools/release.py`, described in [docs/VERSIONING.md](docs/VERSIONING.md)

## [2.0.0] - 2026-10-10

The first release of iOS Backup Explorer as a project of its own, and a major
version: everything below is new since BackupLens 1.0.0, the project this
is a hard fork of. In short:

- the app is split into a file manager and **one tab for each app on the
  phone** (21 of them: Messages, Notes, Calls, Contacts, Photos, Voice Memos,
  Safari, Calendar, Voicemail, Reminders, Network, Accounts, Screen Time,
  Health, Maps, Podcasts, Books, Recents, Privacy, Apps and iCloud Drive),
  each able to export what it shows;
- **unencrypted backups** and **already-extracted backup folders** open as
  well as encrypted ones, and a backup can be **mounted** as a read-only drive;
- extraction was fixed (it used to copy still-encrypted files) and made
  faster and safer;
- relicensed from MIT to **AGPL-3.0-or-later**, with the original author's
  copyright and credit preserved.

From now on versions follow [Semantic Versioning](https://semver.org); see
[docs/VERSIONING.md](docs/VERSIONING.md).

### Added
- **Full documentation** in [`docs/`](docs/README.md): installation, getting started, the file browser, a page for every group of tabs, exporting, where each tab's data comes from (and how well it was checked), Health data (how it is read and what is not covered yet), the FAQ, troubleshooting, how an iPhone backup is built, a glossary, the architecture, a development guide, testing, versioning and releases, plus `CONTRIBUTING.md`, a pull request template and updated issue templates. All pictures are screenshots of the program on an invented demo backup, free of any metadata
- **A demo backup** (`tools/make_demo_backup.py`): an invented backup of an invented person, with data for all 21 tabs, to try the program on and to take the documentation's screenshots (`tools/make_screenshots.py`) from
- **Versioning from this release on**: Semantic Versioning, the version in one place (`__version__`), `python ios_backup_explorer.py --version`, and a check (`tools/check_version.py`, run in CI and in the tests) that the changelog and the README badge agree with it
- The row of tabs shrinks (less padding, a smaller font) to fit when there are many of them
- **Privacy, Apps, Recents and iCloud Drive tabs.** Which apps may use the camera, photos, local network and so on (and when that was set); the apps the home screen knew of; the people last called, messaged or emailed; and the names of the files that were in iCloud Drive. Privacy also lists which apps may use the location
- **A Screen Time tab.** Time per day and week, per app and per website, pickups and notifications, and the most recent hours, from the small files the phone keeps for each. Days are dated where the phone was (found from when its days begin), and a week's total is the sum of its days
- **A Health tab.** The daily activity (steps, active energy, exercise, stand hours, flights, walking distance), workouts with distance, energy and heart rate and **their routes as a GPX file**, body measurements and vitals (weight, body fat, BMI, resting heart rate, blood oxygen, VO2 max...), sleep stages, health records, the Medical ID card, and a count of every kind of data. The kinds of data are named from the database's own shared summaries, and only the kinds whose units were checked against the stored values are interpreted; the rest is listed as "Type N". See the README for what is not covered yet
- **Maps, Podcasts and Books tabs** (favorites, guides and search history with a GPX export; shows and episodes; the library, highlights and collections). Written from the tables of the apps; the backup they were written against held no places, episodes or books, so they are tested on generated databases only
- Working copies of files of the same name from different folders can be given their own names (`AppPanel.local_name`)
- **A Voicemail tab.** Who called (with names from the address book), when, how long, and the words the phone wrote down; play or save the recording, or export the audio with the words beside it
- **A Reminders tab.** Every reminder from every account (list, due date, priority, flag, notes, sub-tasks, completed and deleted ones) and the lists; export as a to-do file (.ics) that task programs import
- **A Network tab.** The Wi-Fi networks the phone joined (security, when joined, the last place it was seen at), the Bluetooth devices it knows, and the data each app used over Wi-Fi and the mobile network
- **An Accounts tab.** The accounts set up on the phone (iCloud, calendars, Game Center and the services behind them) and what the backup says about the device: name, model, iOS version, serial number, when it was backed up
- Tabs whose data is spread over many files (one database for each account, one file for each recording) copy the files they find; export formats that copy files out of the backup (the voicemail audio) join the table formats
- **A Safari tab and a Calendar tab.** Safari: history, sites visited, bookmarks (with folders), the reading list and the open tabs, each a sortable, searchable table with details; bookmarks export as a file browsers import. Calendar: the events and calendars, with repeats and places, all-day events kept as dates, and birthdays without a year; export as an iCalendar (.ics) file or as a spreadsheet, web page, text or JSON
- **Backups that were already decrypted and extracted** (a folder of `HomeDomain`, `AppDomain-...` folders and so on, with no `Manifest.db`) open like any other backup, read-only. The index is made in memory from what is on disk, so every tab and extraction works, and symbolic links are never followed
- A shared table framework (`ios_apps/records*.py`) that new tabs use: columns, sorting, searching, a details pane, exports and extracting the originals, plus a reader for the archives iOS stores some values in (`keyed_archive.py`)
- **A Notes tab.** Folders, sub-folders and *Recently Deleted*; the formatting of a note (title and headings, bullet, dashed, numbered and checklist items, bold, italic, links) and the pictures in it; voice recordings and other attachments you can open or save; search; notes locked with a password are listed with an explanation. Export as text, Markdown, a web page, PDF (optional fpdf2), JSON or a spreadsheet, with the attachments, following the Notes folders; the originals can always be extracted
- Call recordings are kept by the phone as a movie file with a separate track for each side of the call. Choose when you export (and when you extract the originals) between the mixed audio, the original file with the separate tracks, or both; opening or saving a recording offers the same. The mixed `.m4a` is made from the tracks with ffmpeg when it is installed; the original is never changed
- Call recordings in Notes (iOS 18): the audio file, title, length and the words that were said are found, shown under the recording and included in exports and search. They are stored as a recording with no file of its own and a child entry that holds the audio, which was missed at first
- **A Calls tab and a Contacts tab.** The call history as a sortable, filterable, searchable table with names from the address book and missed calls marked; contacts with their full cards. Export calls as CSV, a web page, text or JSON, and contacts as a **vCard (.vcf) file**, CSV, a web page, text or JSON
- **A Photos tab and a Voice Memos tab.** The camera roll as a thumbnail grid made only for what is on screen (optional Pillow and pillow-heif; HEIC supported), with the library's albums, favourites, hidden and recently deleted items; recordings with title, date and length. Open, save, export as originals, JPEG, a web gallery or a list, or extract the originals with the normal extraction
- Optional packages in `requirements-optional.txt`: Pillow, pillow-heif, fpdf2
- **A Messages tab** (the first of the iOS-style app views). Conversations with contact names, chat bubbles (blue for iMessage, green for SMS), tapbacks, group events, attachments you can save, paging for long conversations, and a search that jumps to the match. iMessage and SMS chats with the same number are merged like in the Messages app. Text that newer iOS versions keep only in `attributedBody` is decoded, and the database's `-wal` file is copied with it so recent messages are not lost
- **Export Messages** to text (a file per conversation), a web page with the attachments beside it, a CSV spreadsheet or JSON, and **Extract original files** for the untouched database and attachments
- Tabs: the Files view and each app view are tabs. The connection box folds away once a backup is open
- **A file-manager style browser.** Folders on the left, a sortable list on the right, back / forward / up navigation, a typeable location bar, file-type icons, a context menu (extract, copy name, copy path, properties) and keyboard shortcuts. The whole backup is indexed once when it is opened, so browsing, sorting and searching are instant and no longer wait behind a running extraction
- **Sort by Name, Kind, Size, Date Modified, Date Created or Location**, ascending or descending. Names sort naturally, folders can be kept on top, a folder's size is the total of what is in it, and items with an unknown date always sort last. Creation dates are shown where iOS recorded them
- Folders can be extracted (everything inside them), "Include subfolders" shows a flat list, and long lists are paged instead of being cut off
- **Extract Entire Backup** button: writes every file in the backup into `domain/relativePath` folders straight from the manifest, so it is not limited by the file list's row cap (idea from [mrgunes/BackupLens#1](https://github.com/mrgunes/BackupLens/pull/1) by Nikhil-42)
- **Mount Backup** (optional): mount the open backup as a read-only drive or folder with FUSE. Linux and macOS mount on an empty folder; on Windows (WinFsp) the backup appears as a UNC path `\\ios-backup\<name>` with no drive letter. Encrypted files are decrypted into a private cache on first open and the cache is deleted on unmount; unencrypted files are served in place. Needs `pip install -r requirements-mount.txt`. Idea from [mrgunes/BackupLens#2](https://github.com/mrgunes/BackupLens/pull/2) by Nikhil-42; this is an independent implementation that also works on Windows, keeps all backup access on the single worker thread, reads in binary mode and does not rely on `os.O_ACCMODE` or `os.statvfs` (neither exists on Windows)
- **Unencrypted backups** can be opened, browsed and extracted without a password. The backup type is detected from `Manifest.plist`; the password box is disabled for unencrypted backups. They are opened read-only and `immutable`, so the backup folder is never modified (closes [mrgunes/BackupLens#4](https://github.com/mrgunes/BackupLens/issues/4); [#1](https://github.com/mrgunes/BackupLens/pull/1) takes a similar approach)
- Clear messages for folders that are not backups and for old `Manifest.mbdb` backups
- Test suite (`tests/`) that builds a real encrypted backup and runs it end to end, plus CI
- `NOTICE`, `AUTHORS`, `LICENSE-MIT`, SPDX license headers
- CI check that fails if the original author's attribution is removed

### Changed
- Hard fork of BackupLens 1.0.0, renamed to **iOS Backup Explorer**
- The README now shows this program (screenshots of the invented demo backup) instead of a screenshot of the original BackupLens 1.0.0 interface, and is shorter, pointing to the new documentation. The Python version needed is stated as 3.9 or newer, which is what the tests cover
- Relicensed from MIT to **AGPL-3.0-or-later**; the original MIT notice is preserved in
  `LICENSE-MIT` and `NOTICE`, and the original author is credited in `AUTHORS`
- Renamed `backuplens.py` to `ios_backup_explorer.py` and the main class to `BackupExplorer`

### Fixed
- Dates before 1970 (such as the placeholder year birthdays use) made some views fail on Windows; they are now shown correctly
- Buttons that cannot be used now look disabled, the password box greys out for an unencrypted backup, and the buttons under the file list were squashed away on a short window
- An error raised inside the library's manifest cursor could keep the library object alive (through its traceback) until it was finalised on another thread, leaving the decrypted temporary `Manifest.db` behind. The backup is now cleaned up explicitly on the thread that owns it
- **Extracted files were the still-encrypted backup blobs** (unplayable videos, unreadable
  databases). Extraction passed `domain=` instead of `domain_like=` to `iphone_backup_decrypt`;
  the resulting `TypeError` was swallowed and the raw encrypted file was copied out instead.
  Files are now really decrypted, and a failure is reported instead of silently copying
  encrypted data
- `SQLite objects created in a thread can only be used in that same thread` when browsing a
  backup: every backup operation now runs on one dedicated worker thread
- Errors while loading files were replaced by `NameError: cannot access free variable 'e'`,
  hiding the real message
- File lists were silently cut off at 10,000 rows, and search only filtered those rows. The
  status bar now says when a list is truncated, and search queries the whole backup
- Backup passwords with leading or trailing spaces were rejected (the password was stripped)
- Extraction failed for names Windows cannot store (`? : *` ...) and for paths over 260
  characters, such as Notes attachments
- Auto-detect missed backups made by Microsoft Store iTunes / the Apple Devices app
  (`%USERPROFILE%\Apple\MobileSync\Backup`)
- Startup crash on macOS when the OS refuses to list `MobileSync/Backup`; the app now asks you
  to use Browse instead (also reported and fixed upstream in
  [mrgunes/BackupLens#5](https://github.com/mrgunes/BackupLens/pull/5))
- Wrong-password detection no longer matches any error that merely contains "key"
- Two domains differing only at a `_`/`%` could extract the wrong domain's file
- Zero-byte files failed to extract
- The decrypted temporary `Manifest.db` was never deleted; it is now removed on exit or when
  another backup is opened, and `SECURITY.md` documents it
- Extraction now shows progress and lists which files failed and why

## [1.0.0 — BackupLens, original project] - 2026-04-03

### Added
- Initial release
- Decrypt encrypted iPhone/iPad backups (iOS 13+)
- Browse files by category (Camera Roll, Apps, Health, Messages, etc.)
- Search across all files
- Extract individual files or bulk export
- Auto-detect backup location on Windows and macOS
- Cross-platform support (Windows, macOS, Linux)
- Path traversal protection during extraction
- Warm, trustworthy GUI with platform-native fonts
