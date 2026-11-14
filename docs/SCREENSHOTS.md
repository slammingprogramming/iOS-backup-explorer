# The demo backup and the screenshots

Every picture in this documentation is a screenshot of the real program
running on an **invented** backup. This page explains how both are made, so
the pictures can be refreshed when the window changes, and states the rules
that keep them safe to publish.

## The rules

1. **Only invented data.** The people (Taylor Morgan, Alex Rivera...), places,
   messages, notes, photos, numbers and health values are made up by
   `tools/demo/`. Phone numbers are in area code 555, which does not
   exist, so none can belong to a real person; addresses use `example.com`, `example.org`, `example.net`. Public
   landmarks (a tower, a market in Lisbon) and public-domain book titles are
   used as ordinary names.
2. **No path that says anything about a person.** The demo backup lives in a
   neutral folder (`C:\Demo\Demo iPhone Backup`), and the list of backups found
   on the computer is switched off while the pictures are taken, so no real
   folder, user name or backup is ever shown.
3. **Only the program's window is captured**, not the screen, so nothing else
   (taskbar, other windows, notifications) can be in a picture.
4. **No metadata.** Each PNG is rewritten from its pixels alone, so it carries
   no text chunks, no resolution, no colour profile, no timestamps. (Check with
   any PNG chunk viewer: only `IHDR`, `IDAT` and `IEND` remain.)

## The demo backup

```bash
python tools/make_demo_backup.py "C:\Demo\Demo iPhone Backup"
```

(Run it from a clone of the repository; it needs Pillow, and uses the test
fixtures for the layout of each database.) It writes about 340 files in domain
folders (`HomeDomain`, `CameraRollDomain`, `AppDomainGroup-...`): messages with
photos and tapbacks, notes with checklists and a recipe, calls, contacts,
29 photos and videos (drawn by the program: landscapes made of gradients and shapes),
voice memos, Safari history and bookmarks, a calendar, voicemails with
transcripts, reminders, Wi-Fi and Bluetooth, accounts, permissions, Screen
Time for 60 days, Health (90 days of activity, workouts with routes, body
measurements, sleep, records, Medical ID), Maps, Podcasts and Books, and a
keychain of invented passwords (the Keychain tab asks for the demo's backup
password, `demo-backup-password`, which the file `tools/demo/keychain.py`
states). It also holds what later versions of the program learned to read:

- **a locked note**, "Private", really locked (with the same code the tests of
  locked notes use) with the invented password `demo-note-password` and a hint
  that says so (`tools/demo/media.py`);
- **four messages that no conversation lists**, the rest of a deleted one;
- in Health: **sleep per night** (the sources carry a time zone), **medications**
  and two weeks of doses, the **contents of health records** (lab results,
  vaccines, a prescription, a condition) with **two clinical documents** whose
  files are kept encrypted as on a phone, a **hearing test**, **events and
  symptoms**, **awards**, **sleep schedules** and two **friends** in Activity
  sharing (`tools/demo/health_extra.py`).

The result opens like any backup (it is an *extracted* backup folder), so it is
also a safe way to try the program.

The code is in `tools/demo/`:

| Module | Content |
|---|---|
| `__init__.py` | `Writer`, the time helpers, the fixed "backup made" moment |
| `communication.py` | Contacts, messages, calls, voicemail, recents |
| `media.py` | Photos, voice memos, notes |
| `web.py` | Safari, calendar, reminders |
| `device.py` | Device information, networks, accounts, permissions, apps, iCloud Drive, Screen Time |
| `health.py` | Health and the Medical ID |
| `health_extra.py` | The rest of Health: medications, health records and clinical documents, hearing, events, awards, sleep schedules, friends, time zones for sleep per night |
| `extras.py` | Maps, Podcasts, Books |
| `keychain.py` | The keychain, and the key bag that opens it |
| `pictures.py` | The drawn photos (Pillow) |

Dates are relative to a fixed moment (2026-10-09 18:30 UTC), so the demo is
the same every time.

## The screenshots

```bash
python tools/make_screenshots.py "C:\Demo\Demo iPhone Backup" docs/images ^
    --encrypted "C:\Demo\Encrypted\00000000-0000000000000000"
```

(Windows only: it uses the window's own painting through the Win32 API.) It
opens the demo in the real program, 1280 x 860, visits each tab, selects a row
where details help, takes a picture of the window, and writes
`docs/images/NN-name.png`. `--encrypted` is a folder made with the test
fixtures' `build_backup` (an encrypted backup with a few files) so that the
picture of the password box can be taken.

The dialogs are the real ones, opened and captured before they are closed
again: the export dialog, the password boxes of the locked note and of the
Keychain tab (the tool types the demo's own invented passwords into them, so
nothing waits for a person), the **About & support** window (it shows the
project's real donation addresses, which are public by design and belong to the
project, not to the computer the pictures are made on), and the three tabs of
the **Forgot password?** window. In that window hashcat and CUPP are shown as not found, as they are
on most computers, so that no path of the computer the pictures were made on
can appear in them.

## When to refresh them

When a tab's look changes, a tab is added, or the major or minor version
changes (the title bar shows the version; the pictures may keep showing the
number of an earlier patch release, such as 2.0.0 in 2.0.1, as long as the
window looks the same). Run the two commands, look at every picture, and commit
the changed PNGs. Look at them before publishing: the tool cannot know whether a
future tab shows something it should not.

## Adding a picture

Add a method to `Shooter` in `tools/make_screenshots.py` that selects the tab
and calls `self.shoot("NN-name")`, make sure the demo backup has something to
show for it, and reference the file from the documentation page.
