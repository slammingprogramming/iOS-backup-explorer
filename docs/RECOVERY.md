# Forgot a password?

Two things in a backup can need a password you no longer have: the backup
itself (if it is encrypted) and a note locked from inside the Notes app.
Next to where the program asks for either, a **Forgot password?** button
opens a window with three tabs.

## Official

What Apple itself says about it, and a link to Apple's own page. For both
kinds of password, that answer is short: Apple never holds either one, so
Apple cannot recover or reset them. The one partial exception is a backup
password, which resetting the device's settings clears (letting it make a
new encrypted backup with a new password) without ever unlocking the old
one.

## Workaround

Places the password might already be sitting: a Mac's Keychain Access
(backups only), a password manager, a note where it was written down, or
a hint shown next to a locked note.

## Hashcat

If neither of those helps, the last tab can try the password itself,
with [hashcat](https://hashcat.net/hashcat/): a free program that tries
candidate passwords very quickly. It is **not included with this program**
and is never downloaded by it; the tab only looks for a copy already on
the computer, or lets you point to one.

This only works on a password that is short, or that can be narrowed down
to a manageable number of guesses. hashcat cannot find a long, random
password in any useful time, and nothing here changes that.

What the tab does:

1. It builds the one line hashcat needs from the backup's key bag (its
   `Manifest.plist`) or from the locked note's own row, using exactly the
   same values this program's own password check uses — never your
   password, since neither of them yet has one. A backup's line is for
   hashcat's mode 14800 (`$itunes_backup$...`, the format
   [itunes_backup2hashcat](https://github.com/philsmd/itunes_backup2hashcat)
   describes); a note's is for mode 16200 (`$ASN$...`, the format John the
   Ripper's `applenotes2john.py` describes, which hashcat's own mode is
   built to accept).
2. It asks what to try: a wordlist you already have, or a pattern for a
   short, PIN-like password (a few digits, typed on its own or guided by
   one of the presets). Rules (hashcat's own, such as `rules/best64.rule`)
   can be combined with a wordlist.
3. If you would rather build a list from things you remember about
   yourself — names, a birthdate, a pet, words that come to mind — the
   **Build one with CUPP...** button does that with
   [CUPP](https://github.com/Mebus/cupp), another free program, also not
   included and not downloaded by this one. None of what you type into
   that short form is a secret; it is just the kind of thing CUPP turns
   into guesses.
4. Clicking Start runs hashcat (the command it runs is shown first, so
   you can check it), and streams its own progress. If it finds the
   password, **Use this password** fills it in where you were asked for
   it, the same as typing it yourself.

### Getting hashcat and CUPP

Links in the Hashcat tab open [hashcat.net](https://hashcat.net/hashcat/)
and [github.com/Mebus/cupp](https://github.com/Mebus/cupp) in your browser,
the same way a link in Notes or Safari history does; nothing is fetched by
this program itself. Download and install either one yourself, the way you
would any other program, then point the tab at it if it is not found on its
own.

### A concession, honestly stated

Making this easier helps the person who forgot the password to their own
backup of their own family's photos. It does not stop anyone determined,
since hashcat and CUPP already exist, are free, and already work on a
backup or a note exactly as this program reads them — a technically able
person loses nothing by this feature not existing. What changes is that a
less technical person, recovering their own data, no longer needs to be
one.
