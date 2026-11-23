# Troubleshooting

## Starting the program

**`ModuleNotFoundError: No module named '_tkinter'` or `tkinter`.** Python was
installed without tkinter. On Debian/Ubuntu: `sudo apt install python3-tk`. On
Windows and macOS reinstall Python from python.org and keep the *tcl/tk*
option ticked.

**`No module named 'iphone_backup_decrypt'`.** Run `pip install -r
requirements.txt`. Only encrypted backups need it.

**The window is too big or cut off.** Resize it or maximise it. With many tabs
the tab row shrinks its labels to fit; a wider window gives roomier tabs.

## Finding and opening a backup

**No backup was found automatically.** Use **Browse...** and choose the
device's folder (the one that contains `Manifest.plist`). On macOS, if the
system refused the program permission to list `MobileSync/Backup`, the program
tells you to use Browse; you can also grant your terminal or Python access
under *System Settings > Privacy & Security*.

**"This folder has no Manifest.plist, so it does not look like an iOS backup."**
You chose the folder above or below the right one. Choose the long hex-named
folder inside `MobileSync/Backup`. (A folder of extracted domain folders such as
`HomeDomain` is accepted too.)

**"This backup uses the old Manifest.mbdb format."** iOS 9 and earlier backups
are not supported.

**"Incorrect password. Please try again."** Retype it carefully: spaces
and capitals count, and leading and trailing spaces are part of a password. It is
the backup's encryption password, not your Apple ID password. See
[Getting started](GETTING_STARTED.md#the-password-of-an-encrypted-backup).

**Opening is slow.** A large backup takes a while to count and index (tens of
seconds for hundreds of thousands of files). It only happens when you open it.

## Tabs

### A tab is missing

A tab appears only if the backup holds that app's data.
Common reasons: the backup is *unencrypted* (Apple leaves Health and some other
data out); the data was only in iCloud; the app was never used; or the iOS
version stores it somewhere this version does not read (please report that).
Open **Files** and look in the domain the tab reads
([Where the data comes from](DATA_SOURCES.md)) to see whether the file is there.

**A tab says "Nothing was found here."** The database exists but holds no
rows (a Maps database with no saved places, for instance).

**"Could not read this data: ..."** The database could not be opened or read,
or it is in a layout this version does not know. Use **Extract original files**
to get the raw file and open it in a SQLite browser, and please report the
message (without your data).

**Health takes a long time the first time.** Its database can be hundreds of
megabytes and is copied (and, for an encrypted backup, decrypted) when you first
click the tab. It is deleted when you close the backup.

**Photos are grey tiles.** Install `Pillow` and `pillow-heif`
(`pip install Pillow pillow-heif`).

**Notes: PDF export is not available.** It needs the optional `fpdf2`: `pip install fpdf2`.

**A call recording cannot be mixed.** The mixed `.m4a` needs
[ffmpeg](https://ffmpeg.org) on your `PATH`. The original `.mov` with the
separate tracks never needs it.

**Dates look wrong by a few hours.** Dates are shown in your computer's time
zone. All-day events and Screen Time days deliberately keep their calendar
date. See [The app tabs](apps/README.md#dates-and-times).

**Messages from a contact show a number, not a name.** The number is not in
the backup's address book, or has a different country code. Names are matched
on the last ten digits.

## Extracting and exporting

**Extraction reports "problems".** The *Done, with problems* box lists the
first ten. Usually the file's data is not in the backup (the backup index
lists it but the phone did not store it).

**Names look changed.** Characters Windows cannot store (`? : *`...) are
replaced, and names that collide get the file ID added.

**A very long path fails.** Windows limits path lengths; the program uses the
long-path form where it can. Extract into a short folder such as `C:\Out`.

**A PDF/HTML export is missing pictures.** The picture was not in the backup,
or it is a HEIC picture and `pillow-heif` is not installed (browsers cannot
show HEIC, so install it to have such pictures converted to JPEG).

## Mounting

**The Mount button reports that something is missing.** Install the package
(`pip install -r requirements-mount.txt`) and WinFsp (Windows), macFUSE or
FUSE-T (macOS) or FUSE (Linux); see
[The file browser](FILE_BROWSER.md#mounting-a-backup). The program names what is
missing.

**Windows: the `\\ios-backup\...` path does not open.** Type it into File
Explorer's address bar (not the Run box on some versions). It has no drive
letter by design.

## Devices and backups

See [Devices and backups](DEVICES.md) for how the window works.

**The Device tab says the tools are not installed.** The program only looks
for libimobiledevice's tools; it never installs them. The tab shows the
command for your system. If they are installed but not on the `PATH` (often on
Windows), use **Tools folder...** to point to the folder that holds
`idevicebackup2` and the others.

**No device is found.** Plug it in with its cable (a charge-only cable shows
nothing), unlock it, tap Trust if it asks, and press **Refresh**. On Linux the
`usbmuxd` service must be running (`systemctl status usbmuxd`). If
`idevice_id -l` in a terminal prints nothing, the window cannot see it either.

**"Trust this computer" keeps waiting.** The question is on the device's
screen: unlock it and tap **Trust**, then enter its passcode. If it was
refused once (Don't Trust), unplug the device and plug it in again.

**A backup fails right away, or stops part-way.** Keep the device unlocked and
plugged in, and make sure the folder it is saving into has room (a backup is
about as big as the data on the device). The window shows the tool's own
message. A very recent iOS may need a newer libimobiledevice than your
distribution ships. Nothing is lost when a backup stops: what was copied is
kept, the backup is listed as *Interrupted*, and the next one carries on.

**A backup says it is encrypted and I never set a password.** The device
keeps one setting for its backup encryption, and iTunes or Finder may have set
it before. **Backup encryption** in the Device tab shows its state; to turn it
off you need the password that was set.

**The Backups tab does not list a backup I know is there.** It looks in
Apple's folders, in this program's own folder, and in the folders you add with
**Add a folder...** (the folder that *holds* backups, not one backup).

## Still stuck?

Open an issue (see [Contributing](../CONTRIBUTING.md#reporting-a-problem)) with
your operating system, Python version, program version
(`python ios_backup_explorer.py --version`), the iOS version of the backup and
what you did. **Never include your password, your data, or file paths that name
you.**
