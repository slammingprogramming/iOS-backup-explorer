# Exporting

There are two ways to get data out, and both are always available:

- **Export** writes what a tab *shows* in a format other programs understand.
  It is the right choice when you want to read, search, print, import or
  analyse the data.
- **Extract original files** copies the *files exactly as the backup has
  them* (decrypted, untouched). It is the right choice when you want the raw
  data, or a file the tabs do not interpret. See
  [The file browser](FILE_BROWSER.md#extracting-files).

![The export dialog: a format, what to export, and a folder](images/40-export-dialog.png)

## The export dialog

1. **Format:** the formats the tab offers (the table below).
2. **What to export:** *the selected rows/items*, *the rows shown* (after a
   search) or *all*. Only the choices that make sense are listed.
3. **Save into folder:** a folder you choose. Files are written there; existing
   files of the same name are replaced by files of the same export.

The status line and a message at the end tell you how many files were written.
Something that could not be exported (a missing attachment, a picture that could
not be converted) is reported, and does not stop the rest.

**Exports are your data in readable form.** Protect them or delete them when you
are done. Exported web pages load nothing from the internet and contain no
scripts.

## Formats by tab

| Tab | Formats |
|---|---|
| **Messages** | Text (a file per conversation), web page (with the attachments beside it), spreadsheet (CSV), JSON |
| **Notes** | Text, Markdown, web page (with pictures), PDF *(needs fpdf2)*, JSON, spreadsheet (CSV); call recordings as mixed audio, the original, or both |
| **Calls** | Spreadsheet (CSV), web page, text, JSON |
| **Contacts** | **vCard (.vcf)**, spreadsheet (CSV), web page, text, JSON |
| **Photos** | Original files, pictures as **JPEG**, web gallery, a list (CSV) |
| **Voice Memos** | Audio files (named by date and title), web page with players, a list (CSV) |
| **Voicemail** | **Audio files with the transcript as text**, spreadsheet, web page, text, JSON |
| **Calendar** (events) | **iCalendar (.ics)**, spreadsheet, web page, text, JSON |
| **Reminders** (reminders) | **To-do file (.ics)**, spreadsheet, web page, text, JSON |
| **Safari** (bookmarks) | **Bookmarks file for browsers**, spreadsheet, web page, text, JSON |
| **Health** (workouts) | **GPX routes**, spreadsheet, web page, text, JSON |
| **Maps** (favorites, places, history) | **GPX waypoints**, spreadsheet, web page, text, JSON |
| **Every other table** | Spreadsheet (CSV), web page, text, JSON |

## What the formats contain

| Format | Details |
|---|---|
| **Spreadsheet (CSV)** | UTF-8 with a byte-order mark so that Excel opens accents correctly; one header row; dates are in your local time (the calls and voice memos lists add the same date in UTC in a second column) |
| **Web page (.html)** | One self-contained page (styles inside), no scripts, nothing loaded from the internet; text is escaped so nothing inside your data can run |
| **Text (.txt)** | Plain UTF-8, one record on a line or a block |
| **JSON** | UTF-8, indented, with dates as ISO-8601 UTC strings and missing values as `null` |
| **Markdown** | Notes only: headings, lists, checklists (`- [x]`), bold and italic |
| **PDF** | Notes only |
| **vCard (.vcf)** | vCard 3.0: names, numbers, emails, addresses, URLs, birthday, notes, with labels mapped to the standard types; no photos |
| **iCalendar (.ics)** | Version 2.0; events as `VEVENT` (timed events in UTC, all-day events as dates, repeat rules kept), reminders as `VTODO` (due date, priority, notes, category, completion) |
| **GPX 1.1** | Workouts: one track with a segment of points (latitude, longitude, altitude, time). Maps: waypoints |
| **Bookmarks (.html)** | The Netscape bookmark format Chrome, Firefox, Edge and Safari import, with your folders |
| **Audio** | The recording exactly as the phone made it; **never converted** (voice memos and voicemails), except a call recording's optional mixed `.m4a` |
| **JPEG** | Pictures converted for compatibility; needs Pillow (and pillow-heif for HEIC) |

## File names

Names are made safe for every operating system: characters Windows cannot
store (`< > : " / \ | ? *`) are replaced, trailing dots and spaces are removed,
reserved names (`CON`, `NUL`...) are avoided, and over-long names are shortened
(keeping the extension). Names that would collide get a number added.
