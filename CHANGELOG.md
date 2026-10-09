# Changelog

All notable changes to iOS Backup Explorer will be documented in this file.

iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens) by
Eyyup (Eric) Gunes. Entries below the fork point record the original project's history.

## [Unreleased]

### Changed
- Hard fork of BackupLens 1.0.0, renamed to **iOS Backup Explorer**
- Relicensed from MIT to **AGPL-3.0-or-later**; the original MIT notice is preserved in
  `LICENSE-MIT` and `NOTICE`, and the original author is credited in `AUTHORS`
- Renamed `backuplens.py` to `ios_backup_explorer.py` and the main class to `BackupExplorer`

### Fixed
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

### Added
- **Extract Entire Backup** button: writes every file in the backup into `domain/relativePath` folders straight from the manifest, so it is not limited by the file list's row cap (idea from [mrgunes/BackupLens#1](https://github.com/mrgunes/BackupLens/pull/1) by Nikhil-42)
- **Mount Backup** (optional): mount the open backup as a read-only drive or folder with FUSE. Linux and macOS mount on an empty folder; on Windows (WinFsp) the backup appears as a UNC path `\\ios-backup\<name>` with no drive letter. Encrypted files are decrypted into a private cache on first open and the cache is deleted on unmount; unencrypted files are served in place. Needs `pip install -r requirements-mount.txt`. Idea from [mrgunes/BackupLens#2](https://github.com/mrgunes/BackupLens/pull/2) by Nikhil-42; this is an independent implementation that also works on Windows, keeps all backup access on the single worker thread, reads in binary mode and does not rely on `os.O_ACCMODE` or `os.statvfs` (neither exists on Windows)
- **Unencrypted backups** can be opened, browsed and extracted without a password. The backup type is detected from `Manifest.plist`; the password box is disabled for unencrypted backups. They are opened read-only and `immutable`, so the backup folder is never modified (closes [mrgunes/BackupLens#4](https://github.com/mrgunes/BackupLens/issues/4); [#1](https://github.com/mrgunes/BackupLens/pull/1) takes a similar approach)
- Clear messages for folders that are not backups and for old `Manifest.mbdb` backups
- Test suite (`tests/`) that builds a real encrypted backup and runs it end to end, plus CI
- `NOTICE`, `AUTHORS`, `LICENSE-MIT`, SPDX license headers
- CI check that fails if the original author's attribution is removed

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
