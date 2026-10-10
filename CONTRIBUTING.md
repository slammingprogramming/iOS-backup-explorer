# Contributing

Thank you for wanting to help. This project handles some of the most sensitive
data a person has, so it has a few firm rules; they are short, and they are why
people can trust it.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## The rules

1. **Security and privacy come first.** The program makes **no network
   connections** and stores nothing but what the user asks for. Any change that
   adds network access, telemetry, analytics or a hidden file is rejected.
2. **Keep it auditable.** The program is plain Python with no build step and
   one required dependency. New required dependencies are rejected; optional
   ones are welcome if they are loaded lazily and the program says what is
   missing.
3. **Never include real data.** Not in code, tests, fixtures, screenshots,
   issues, pull requests or commit messages: no messages, names, numbers,
   places, health values, paths that name you, passwords. Tests use *invented*
   data only (see [Testing](docs/TESTING.md)). Counts and shapes of a real
   backup are fine to describe; contents are not.
4. **Credit and licence.** Contributions are licensed under
   **AGPL-3.0-or-later**. Never remove or alter the original author's copyright
   notices ([LICENSE-MIT](LICENSE-MIT), [NOTICE](NOTICE), [AUTHORS](AUTHORS));
   CI enforces this. Every new source file starts with the SPDX line and the
   project's copyright line (copy one from an existing file).
5. **Be honest about what is verified.** A reader that was written from a
   documented layout rather than a real backup must say so in its documentation.
   Do not show a value whose meaning or unit you could not verify.

## Reporting a problem

Open an issue using the bug template, and include:

- your operating system, Python version, and the program's version
  (`python ios_backup_explorer.py --version`);
- the **iOS version** of the backup, whether it is encrypted, and whether it is
  a folder of extracted files;
- what you did, what you expected and what happened (the exact message);
- for something missing or wrong in a tab: the tab, the table, and *the shape*
  of the problem (for example "the Notes tab lists 12 notes but the phone had
  40", "the dates are all 2001").

**Do not include** your backup password, your data, screenshots of your data, or
paths that identify you. If a screenshot is needed, use the
[demo backup](docs/SCREENSHOTS.md) to reproduce it.

**Security problems** are reported privately; see [SECURITY.md](SECURITY.md).
Never open a public issue for one.

## Suggesting a feature

Open an issue with the feature template. Tell us what you want to *do* ("see
which apps used mobile data last month") before how. If you know where the data
lives in a backup, say which file (not its contents).

## Sending a change

1. Fork the repository and create a branch (`git checkout -b feature/widgets`).
2. Read the [Development guide](docs/DEVELOPMENT.md) (how to add a tab or an
   export, and the conventions) and [Architecture](docs/ARCHITECTURE.md).
3. Make the change, with **tests** and **documentation**:
   - new behaviour has tests on invented data, including the awkward cases;
   - break your code on purpose and check the tests notice (mutation checks, in
     [Testing](docs/TESTING.md));
   - update the docs under `docs/`, the table in
     [Where the data comes from](docs/DATA_SOURCES.md) and the
     [changelog](CHANGELOG.md) under *Unreleased*.
4. Run the checks:
   ```bash
   python -m unittest discover -s tests -t .
   python tools/check_attribution.py
   python tools/check_version.py
   ```
   (CI runs them on Windows and Linux with Python 3.9 and 3.13.)
5. Open a pull request that says what changed and why, and how you checked it.

Small, focused pull requests are reviewed faster than large ones.

### Commits

Write a title in the imperative ("Add the Widgets tab"), a body that explains
*why* and what was verified, and no personal information. The maintainers sign
their commits; you are not required to.

## Versions and releases

The project uses [Semantic Versioning](https://semver.org). Maintainers make
releases; see [Versioning and releases](docs/VERSIONING.md) for what counts as a
major, minor or patch change.

## Upstream

This is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens).
Fixes that fit the original project are welcome there too, as separate changes
that do not carry this project's relicensing or renaming.
