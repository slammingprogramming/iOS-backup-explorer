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

### Added
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
