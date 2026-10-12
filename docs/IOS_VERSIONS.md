# iOS versions

The goal of this project is to read backups of **every iOS version**. It cannot
be done from documentation: the databases inside a backup change between
versions, Apple does not document them, and a reader that is right for one
version can silently show nothing on another. So each version is checked
against a **real backup of that version**, and this page records which
versions have been, and what was found.

## What has been checked

| iOS | Device | Checked | Notes |
|---|---|---|---|
| 26.6 | iPhone14,7 | Every tab run on it; the counts of Photos, Voice Memos, Maps, Books, Reminders compared with the raw tables; Health in full (every table, the routes, the files of clinical documents) | |
| 16.7 | iPhone10,6 | Every tab run on it, Health in full | No Maps, Books, Photos or Voice Memos data in the backup |
| 17, 18 | | The first checks of Messages, Notes, Calls, Contacts, Safari, Calendar... | Before this page; not repeated |
| 12 | | Some of the author's older backups | Not re-examined for this page; the 12.4 backup at hand cannot be opened (its password is lost) |
| 13, 14, 15, 19-25 | | **Not checked** | Backups of these are wanted, see below |

Newer and older versions of the same major number are expected to behave alike;
a tab that does not is exactly what this page is meant to find.

## What differs between versions

Found so far, and handled (each has a test that builds the older and the newer
layout):

- **Reminders**: iOS 26 keeps its databases in an app group
  (`AppDomainGroup-group.com.apple.reminders`) instead of in `HomeDomain`, and
  its lists in a table of their own (`ZREMCDBASELIST`) instead of among the
  other objects.
- **Data used by apps**: iOS 26 records only mobile data; the Wi-Fi columns are
  missing from the database. The table then shows no Wi-Fi columns.
- **Maps guides**: the table that joins guides to the places in them is named
  after the numbers of the two kinds it joins, which changed (`Z_5PLACES` to
  `Z_6PLACES`); it is found by its columns.
- **Health, workout routes**: iOS 26 names the columns of the table that links
  a workout to its route by direction (`destination_object_id` for the
  workout, `source_object_id` for the route, and a `deleted` flag) where iOS 16
  has `parent_id` and `child_id`. Before this was handled, no route was found
  on iOS 26 (16 of 179 workouts have one in the backups used).
- **Health, medications**: iOS 26 records the unit of a dose (`unit_string`,
  for example "tablet") and has a dose status that iOS 16 did not show.
- **Screen Time** and **Podcasts**: the iOS 26 backup had no Screen Time
  activity files and no Podcasts library, so those tabs show nothing there.
  Whether that is the version or the phone is not known yet.

## Helping: a report that contains no personal data

`tools/compat_report.py` opens a backup in the real program (in a hidden
window), visits every tab, and prints **only counts and the program's own
messages**: the iOS version and kind of device, whether each tab loaded, how
many rows each table has. Nothing from the backup's content (names, texts,
places, dates) is written.

```
python tools/compat_report.py "<backup folder>" --markdown
```

For an encrypted backup it asks for the password in the terminal (not stored);
for a folder extracted by this program, say the version with `--ios 15.8`. The
output can be pasted into an issue, for example "Notes: nothing on iOS 14". It
runs on Windows, macOS and Linux, and needs a display.

A backup of an iOS version not in the table above is the most useful thing
anyone can bring; so is a version that is in the table but whose phone was used
differently (a different region, apps installed, a watch paired). **Do not post
the backup or anything from it.**
