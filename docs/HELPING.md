# How to help: share the shape of your backup, never its contents

This project can only read an iOS version well if someone has looked at a real
backup of it. You do not have to send anything private for that. The program
comes with small tools that print the **shape** of a backup (which tabs fill,
how its databases are built, how many rows they have) and **nothing from inside
it**. You run them on your own computer, read what they print, and paste it into
an issue.

> **The rule.** Never post your backup, its password, or anything it contains:
> no messages, names, numbers, places, photos, health values, or file paths that
> name you. Counts, versions and layouts are welcome; contents never are.
> Nobody will ask you for the backup itself. If someone does, it is not this
> project.

## What helps most

| You have... | Run | Then open |
|---|---|---|
| A backup of any iOS version, and you want to know what the program shows | [`compat_report.py`](#1-which-tabs-your-backup-fills) | the *Compatibility report* form |
| A backup of an iOS version listed as **not checked** in [iOS versions](IOS_VERSIONS.md) | the same | the same, or the *I can test another iOS version* form |
| A tab that is empty, or shows too little | [`schema_report.py`](#2-how-your-databases-are-built) | the *A tab is empty or wrong (layout report)* form |
| "Type N" in the Health tab that you can recognise | [`health_kinds_report.py`](#3-health-data-types-the-program-cannot-name) | the *Help name a Health data type* form |
| An error message or something that looks wrong | nothing to run | the *Bug report* form |
| An idea | nothing to run | the *Feature request* form |
| A mistake in these pages | nothing to run | the *Documentation problem* form |

If you can write code, [CONTRIBUTING](../CONTRIBUTING.md) says how to send a
change. A layout report with `--sql` is the best starting point for a fix, and
a pull request that comes with one is very welcome.

## 1. Which tabs your backup fills

```
python tools/compat_report.py "<your backup folder>" --password-window --markdown
```

It opens the backup in the real program (in a window you do not see), visits
every tab and prints a table: the iOS version and the kind of device, and for
each tab whether it loaded, what it says ("92 conversations, 1,278 messages")
and how many rows each of its tables has. Use `--password-prompt` to type the
password in the terminal instead. For a folder of extracted files add
`--ios 15.8`. It needs a display and takes a minute or two.

## 2. How your databases are built

```
python tools/schema_report.py "<your backup folder>" --password-window
```

It reports on every database the program reads: the tables, their columns and
types, and how many rows each has (for a database made with Core Data, also the
names of its record kinds). It also lists the files the program reads that your
backup does *not* have, which is often the whole answer.

- `--path "HomeDomain/Library/SMS/sms.db"` looks at one file (repeat it for
  more). Add `--sql` to also print the `CREATE` statements, which are the layout
  as SQLite itself writes it and the most useful thing to attach.
- `--find notes` lists the database files whose path contains a word, to find
  where an app keeps its data. **A path can name an app you have installed**,
  so read the list before you post it.
- For a property list it shows only the names and kinds of the top-level keys
  (a key such as a Wi-Fi name could identify you, so nothing below the top level
  is shown).

## 3. Health data types the program cannot name

```
python tools/health_kinds_report.py "<your backup folder>" --password-window
```

Health stores each sample with a number for its kind. The program names a
number only when the database names it, or when it has been checked against an
independent fact (see [Health data](HEALTH.md)); it never guesses. The tool
lists the kinds that are still unnamed: how many samples, in which years,
whether they look like a measurement or an event, their smallest and largest
value and the values an event takes. If you can say how you know what one is
("it only appears when I use that app"), that is what turns a number into a
name.

This one is **your health data**, summarised. Delete any row you would rather
not share.

## Before you post

1. **Read the whole output.** The tools print only what is described above, but
   you are the one who decides what to share.
2. **Look for anything that names you**: a device name, an account, a path with
   your user name, an app you would rather not mention. Remove it, or ask in the
   issue how to describe it.
3. **Do not attach files.** Not the backup, not a database, not a screenshot of
   your own data. A screenshot is fine only of the
   [demo backup](SCREENSHOTS.md).

## If you posted something by mistake

Do not try to fix it in the issue text: GitHub keeps the edit history. Instead
**report it privately** (the *Security advisories* link in the issue chooser, or
[SECURITY.md](../SECURITY.md)) with the link, so it can be removed for good, and
change anything that was a secret (a password, a key).

## What happens to what you share

The reports are read by people, in the open. They are used to find out how a
version stores its data, and a fix is checked the same way: by running it on a
real backup and describing the result. Nothing you post is used for anything
else. If you want to be thanked by name in the changelog when your report leads
to a fix, say so in the issue; otherwise you stay anonymous.

## How the tools keep to the rule

- They make **no network connection**; they run entirely on your computer, like
  the program.
- They copy the few files they need into a temporary folder, read them, and
  delete the folder when they finish.
- They print counts, names of tables and columns, and versions. The tests check,
  on invented backups, that no row, text, name or date comes out
  (`tests/test_report_tools.py`, `tests/test_compat_report.py`).
- They read the source of your backup only; they never change it.
