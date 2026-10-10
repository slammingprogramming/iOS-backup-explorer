# iOS Backup Explorer documentation

Documentation for **iOS Backup Explorer 2.0.0**. Every picture in these pages
was taken from the program running on an *invented* demo backup (see
[SCREENSHOTS.md](SCREENSHOTS.md)); nothing in them is a real person's data.

## Using the program

| Page | What it covers |
|---|---|
| [Installation](INSTALL.md) | Python, the one required package, the optional extras, running the program |
| [Getting started](GETTING_STARTED.md) | Finding a backup, opening it (encrypted, unencrypted or already extracted), the window, a first look around |
| [The file browser](FILE_BROWSER.md) | Folders, sorting, searching, extracting files, extracting the entire backup, mounting a backup as a drive |
| [The app tabs](apps/README.md) | One page for each group of tabs: what is shown, how to use it, what it cannot show |
| [Exporting](EXPORTING.md) | Every export format, which tab offers it, and what the files contain |
| [Where the data comes from](DATA_SOURCES.md) | The file each tab reads, which iOS versions, and how well each was checked |
| [Health data](HEALTH.md) | How Health is read, and what is not covered yet and why |
| [FAQ](FAQ.md) | Short answers |
| [Troubleshooting](TROUBLESHOOTING.md) | When something does not show or does not work |
| [Privacy and data handling](../SECURITY.md) | What the program writes to your computer, and the security policy |

## Understanding it

| Page | What it covers |
|---|---|
| [How an iPhone backup is built](HOW_BACKUPS_WORK.md) | Domains, `Manifest.db`, file IDs, encryption, and the oddities of the databases inside |
| [Glossary](GLOSSARY.md) | The words used in the program and these pages |

## Working on it

| Page | What it covers |
|---|---|
| [Contributing](../CONTRIBUTING.md) | How to propose a change, and the rules that keep the project trustworthy |
| [Architecture](ARCHITECTURE.md) | The modules, the threads, the backends, and the table framework most tabs are built on |
| [Development guide](DEVELOPMENT.md) | Setting up, adding a tab, the conventions to follow |
| [Testing](TESTING.md) | The test suite, the generated fixtures, and mutation checks |
| [The demo backup and screenshots](SCREENSHOTS.md) | Making the invented backup and the pictures, and the rules they follow |
| [Versioning and releases](VERSIONING.md) | Semantic Versioning, what counts as a major, minor or patch change, how a release is made |
| [Changelog](../CHANGELOG.md) | What changed in each version |

## About the project

iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens)
by Eyyup (Eric) Gunes, relicensed under the AGPL-3.0-or-later with the
original author's copyright and credit preserved ([NOTICE](../NOTICE),
[AUTHORS](../AUTHORS), [LICENSE-MIT](../LICENSE-MIT)).
