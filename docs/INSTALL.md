# Installation

iOS Backup Explorer is plain Python: there is no installer, no build step and
no configuration file. You need Python, one small package, and the files of
this repository.

## What you need

| | Needed for | How |
|---|---|---|
| **Python 3.9 or newer** | everything | [python.org](https://www.python.org/downloads/). The tests run on 3.9 and 3.13 |
| **tkinter** | the window | Included with Python on Windows and macOS. On Linux: `sudo apt install python3-tk` |
| **iphone_backup_decrypt** | encrypted backups | `pip install -r requirements.txt` (the only required package) |

`iphone_backup_decrypt` is only loaded when you open an *encrypted* backup:
unencrypted backups and already-extracted backup folders open without it. It
is small, so install it anyway.

## Get the program

```bash
git clone https://github.com/slammingprogramming/iOS-backup-explorer.git
cd iOS-backup-explorer
pip install -r requirements.txt
python ios_backup_explorer.py
```

Or, without git, download **iOS-Backup-Explorer-X.Y.Z.zip** (or `.tar.gz`) from
the [releases page](https://github.com/slammingprogramming/iOS-backup-explorer/releases),
unpack it and run the same two commands inside the folder. The release also has a
`SHA256SUMS` file to check the download against (`sha256sum -c SHA256SUMS`, or
`Get-FileHash <file>` in PowerShell); see [Versioning and releases](VERSIONING.md).

To see the version without opening the window:

```bash
python ios_backup_explorer.py --version
```

It is a good idea to use a virtual environment so the packages stay out of
your system Python:

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows (PowerShell: .venv\Scripts\Activate.ps1)
source .venv/bin/activate     # macOS and Linux
pip install -r requirements.txt
```

## Optional extras

None of these is needed to run the program; each adds something. Without one,
the program says what is missing and the original files can still be saved.

```bash
pip install -r requirements-optional.txt
```

| Package | What it adds |
|---|---|
| **Pillow** | Picture previews in Photos and in notes, and conversion of pictures to JPEG |
| **pillow-heif** | The same for HEIC pictures, which is what iPhones take by default |
| **fpdf2** | PDF export of notes |
| **ffmpeg** (a separate program, not a pip package; [ffmpeg.org](https://ffmpeg.org)) | Mixing the two sides of a call recording into one `.m4a` |
| **mfusepy** (`pip install -r requirements-mount.txt`) | Mounting a backup as a drive or folder; also needs WinFsp, macFUSE/FUSE-T or FUSE, see [the file browser](FILE_BROWSER.md#mounting-a-backup) |

## Platform notes

- **Windows.** Works as is. Windows has no time zone database, which only
  matters for the one thing [Health](HEALTH.md) leaves out (sleep summed per
  night).
- **macOS.** Works as is. If Python was installed from python.org, tkinter is
  included.
- **Linux.** Install `python3-tk`. Backups have to be copied over from a
  Windows or macOS computer first, because iTunes and Finder do not exist
  there.

## Running the tests

```bash
python -m unittest discover -s tests -t .
```

The window tests need a display and skip themselves without one. See
[Testing](TESTING.md).

## Uninstalling

Delete the folder. The program writes nothing outside the temporary folders
described in [SECURITY.md](../SECURITY.md), which it removes itself when you
close it.
