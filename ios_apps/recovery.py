# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — helping with a forgotten password (optional hashcat
# and CUPP)
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Turning the backup password or a note's password into something
`hashcat <https://hashcat.net>`_ can try to crack, for someone who has
forgotten it and has every right to the backup or note they are locked out
of. Nothing here helps open anyone else's backup or notes: both hash kinds
need the file (``Manifest.plist`` or the Notes database) that only someone
who already holds the backup has.

Neither hashcat nor `CUPP <https://github.com/Mebus/cupp>`_ (a wordlist
generator, used here only to build a *candidate list* from things the owner
remembers about themselves) is a dependency of this program. Both are
external programs the person installs and runs themselves; this module only
looks for one already on the computer (``locate_hashcat``, ``locate_cupp``)
or at a path the person points to, and never downloads or installs
anything. See ``docs/RECOVERY.md``.

Hash formats
------------
``$itunes_backup$*10*WPKY*ITER*SALT*DPIC*DPSL`` (hashcat mode 14800) is the
backup key bag's own password check: the same PBKDF2-HMAC-SHA256 then
PBKDF2-HMAC-SHA1 stretch, and the same RFC 3394 key-unwrap integrity check,
that :func:`ios_apps.keychain_crypto.unlock_keybag` uses (built from the
same :func:`ios_apps.keychain_crypto.parse_keybag`, so the two can never
disagree about what a correct password is). Confirmed against the format
`itunes_backup2hashcat <https://github.com/philsmd/itunes_backup2hashcat>`_
and `a worked example <https://irq5.io/2017/03/07/cracking-itunes-backup-passwords-with-hashcat/>`_
describe, and hashcat's own wiki (mode 14800 is "iTunes backup >= 10.0",
which is the only kind this program's own ``unlock_keybag`` reads, since it
already requires ``DPIC``/``DPSL``). A
`hashcat forum thread <https://hashcat.net/forum/thread-8977.html>`_ shows
the same ``$itunes_backup$*10*...`` form still made on iOS 12 and 13, and
is a reminder that each backup gets its own random salt and key: cracking
one backup's hash says nothing about a different backup of the same
device, even with the same password, and finding the password needs a
fresh hash from that backup's own ``Manifest.plist``.

``$ASN$*Z_PK*ITERATIONS*SALT*WRAPPEDKEY`` (hashcat mode 16200, "Apple Secure
Notes") is the same PBKDF2-HMAC-SHA256 and key-unwrap check that
:func:`ios_apps.notes_crypto.decrypt` uses for a locked note. The field
names and the format come from John the Ripper's
`applenotes2john.py <https://github.com/openwall/john>`_, which hashcat's
mode is built to accept (without its ``name:`` prefix or ``:::::hint``
suffix, which are that script's own, not hashcat's).
"""

import dataclasses
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading

from . import keychain_crypto

_QUIET = {"creationflags": 0x08000000} if sys.platform.startswith("win") \
    else {}                                       # no console window flashes

BACKUP_MODE = "14800"
NOTE_MODE = "16200"


class RecoveryUnavailable(Exception):
    """Hashcat cannot help with this particular backup or note (the reason
    is in the message); hashcat itself may still be perfectly installed."""


# The "Official"/"Workaround" wording for a backup password: shared by the
# main window (asking to open a backup) and the Keychain tab (asking for
# the same password, for an already-open backup or extracted folder), so
# the two can never say something different about the one same password.
BACKUP_OFFICIAL = (
    "This password is never sent to Apple, so Apple cannot recover or "
    "reset it; it only ever existed on the computer that made this "
    "backup.",
    "On iOS 11 or later (or iPadOS), resetting all settings on the "
    "device removes its backup password, so the device can make a new "
    "encrypted backup with a new one. This does not erase your data, "
    "and does not unlock this backup, which stays locked with the "
    "password it already has; it only lets you move on from it.",
    "On iOS 10 or earlier there is no such reset either.",
    ("Apple's own page on a forgotten backup password",
     "https://support.apple.com/ht213037"),
)
BACKUP_WORKAROUND = (
    "On a Mac, open Keychain Access and search for \"iOS Backup\"; the "
    "password may be saved there from when the backup was made, and "
    "Finder or iTunes would have filled it in automatically.",
    "Check any password manager you use for an entry made around the "
    "date of this backup.",
)


# ── Finding the optional tools ────────────────────────────────

def find_tool(name, explicit=None):
    """The full path of *name*, trying *explicit* first, then the ``PATH``.
    Nothing is ever downloaded or installed; this only looks."""
    if explicit:
        path = os.path.abspath(explicit)
        return path if os.path.isfile(path) else None
    return shutil.which(name)


def locate_hashcat(explicit=None):
    """hashcat's full path, or None. Tries the names a Windows download and
    a Linux/macOS package both use."""
    if explicit:
        return find_tool(None, explicit)
    for name in ("hashcat", "hashcat.exe", "hashcat64.exe", "hashcat32.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def locate_cupp(explicit=None):
    """CUPP's full path (its ``cupp.py``), or None. CUPP is a single script,
    not a package, so this only recognises a file someone points to or one
    already on the ``PATH``."""
    if explicit:
        return find_tool(None, explicit)
    for name in ("cupp.py", "cupp"):
        found = shutil.which(name)
        if found:
            return found
    return None


def tool_version(path, *args, timeout=10):
    """The first line *path* prints for *args* (``--version`` by default),
    or None if it could not be run."""
    try:
        done = subprocess.run(
            [path, *(args or ("--version",))], capture_output=True,
            timeout=timeout, stdin=subprocess.DEVNULL, **_QUIET)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (done.stdout or done.stderr or b"").decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else None


# ── Building the hash hashcat is asked to crack ───────────────

@dataclasses.dataclass
class RecoveryHash:
    """One line for hashcat to crack, and the ``-m`` mode that reads it."""

    text: str
    mode: str
    kind: str                 # "backup" or "note", for the dialog's wording


def backup_hash_from_keybag(keybag_blob):
    """The hashcat hash for a backup's key bag (``Manifest.plist``'s
    ``BackupKeyBag``), or raises :class:`RecoveryUnavailable` if this key
    bag is not one this program's own ``unlock_keybag`` could ever check a
    password against either (a backup from before iOS 10, which never
    carries ``DPIC``/``DPSL``)."""
    try:
        attrs, classes = keychain_crypto.parse_keybag(keybag_blob)
        dpic, dpsl = attrs[b"DPIC"], attrs[b"DPSL"]
        iterations, salt = attrs[b"ITER"], attrs[b"SALT"]
    except KeyError:
        raise RecoveryUnavailable(
            "This backup's key bag has no DPIC/DPSL round count, so it is "
            "older than this program can check a password against at all "
            "(see Help). Hashcat's mode 14700 can still try one, but this "
            "program could not tell you whether it was right.") from None
    wpky = next((entry[b"WPKY"] for entry in classes.values()
                if entry.get(b"WRAP", 0) & 2 and entry.get(b"WPKY")), None)
    if wpky is None:
        raise RecoveryUnavailable(
            "This key bag has no password-protected class key to try a "
            "password against.")
    text = (f"$itunes_backup$*10*{wpky.hex()}*{iterations}*{salt.hex()}*"
            f"{dpic}*{dpsl.hex()}")
    return RecoveryHash(text, BACKUP_MODE, "backup")


def backup_hash_from_manifest(manifest_path):
    """The hashcat hash for the backup whose ``Manifest.plist`` is at
    *manifest_path*. Reads only that one file: no password is needed and
    none is used."""
    with open(manifest_path, "rb") as handle:
        manifest = plistlib.load(handle)
    keybag = manifest.get("BackupKeyBag")
    if not keybag:
        raise RecoveryUnavailable(
            "This backup's Manifest.plist has no key bag (it may not "
            "actually be encrypted).")
    return backup_hash_from_keybag(keybag)


def note_hash(pk, salt, iterations, wrapped_key):
    """The hashcat hash for one locked note, from the same values
    :func:`ios_apps.notes_crypto.decrypt` is given (a :class:`~ios_apps.notes.Note`
    that is locked carries them in ``note.crypto``, and its own primary key
    in ``note.pk``)."""
    if not (salt and iterations and wrapped_key):
        raise RecoveryUnavailable(
            "This note is missing one of its encryption details, so there "
            "is nothing to build a hash from.")
    text = f"$ASN$*{pk}*{iterations}*{salt.hex()}*{wrapped_key.hex()}"
    return RecoveryHash(text, NOTE_MODE, "note")


# ── Running hashcat ────────────────────────────────────────────

ATTACK_WORDLIST = 0
ATTACK_MASK = 3

#: Attack modes: the caller chooses one of these.


class HashcatRun:
    """One hashcat process, started in the background. *on_line* is called
    (from a worker thread; the caller posts it to its own thread) with each
    line hashcat prints; *on_done* with ``(found_password_or_None, note)``
    once it exits, where *note* explains a non-zero exit when there is
    nothing clearer to say.

    The password hashcat found is read from its own output file, in the
    plain ``--outfile-format 2`` (just the candidate, nothing else), rather
    than parsed from its status screen, which is formatted for reading, not
    for a program to rely on. The trailing newline that format always ends
    with is removed; nothing else about the password is touched (it may
    begin or end with spaces, like any backup password this program asks
    for elsewhere).
    """

    def __init__(self, hashcat_path, recovery_hash, *, wordlist=None,
                mask=None, rules=None, extra_args=(), on_line=None,
                on_done=None):
        self.folder = tempfile.mkdtemp(prefix="ios-backup-explorer-crack-")
        self.hash_path = os.path.join(self.folder, "recovery.hash")
        self.outfile_path = os.path.join(self.folder, "found.txt")
        with open(self.hash_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(recovery_hash.text + "\n")
        attack = ATTACK_MASK if mask else ATTACK_WORDLIST
        prefix = [hashcat_path] if isinstance(hashcat_path, str) \
            else list(hashcat_path)
        argv = prefix + ["-m", recovery_hash.mode, "-a", str(attack),
                        self.hash_path]
        if attack == ATTACK_WORDLIST:
            argv.append(wordlist)
            if rules:
                argv += ["-r", rules]
        else:
            argv.append(mask)
        argv += ["--outfile", self.outfile_path, "--outfile-format", "2",
                "--potfile-disable", "--status", "--status-timer", "5",
                *extra_args]
        self.command = argv
        self._on_line = on_line
        self._on_done = on_done
        self._process = None
        self._thread = None
        self._stop_requested = False

    def start(self):
        self._process = subprocess.Popen(
            self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=self.folder, stdin=subprocess.DEVNULL,
            **_QUIET)
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="hashcat")
        self._thread.start()

    def _pump(self):
        try:
            for line in self._process.stdout:
                if self._on_line:
                    self._on_line(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        finally:
            self._process.stdout.close()
            self._process.wait()
            if self._on_done:
                self._on_done(self._found_password(), self._exit_note())

    def _found_password(self):
        # Universal-newline translation (the default) turns whatever line
        # ending hashcat's own platform used into a single "\n", which is
        # then the only character trimmed: the password itself is never
        # touched, however it begins or ends.
        try:
            with open(self.outfile_path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return None
        return text[:-1] if text.endswith("\n") else text or None

    def _exit_note(self):
        code = self._process.returncode
        if self._stop_requested:
            return "Stopped."
        if code == 0:
            return None    # exhausted every candidate without a match
        if code == 1:
            return None     # "exhausted" is also reported as 1 by some builds
        return f"hashcat exited with status {code}."

    def stop(self):
        """Ask hashcat to stop. Already-found results are kept."""
        self._stop_requested = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass

    def close(self):
        """Stop the process if it is still running and remove the working
        folder (the hash file and anything hashcat wrote)."""
        self.stop()
        if self._thread:
            self._thread.join(timeout=5)
        shutil.rmtree(self.folder, ignore_errors=True)


# ── CUPP: a wordlist from things the person remembers ─────────

#: The interactive prompts CUPP asks, in order, as (field, required, is_date).
#: Matches the upstream ``Mebus/cupp`` ``interactive()`` function; a fork
#: that asks something else will not be driven correctly by this, and the
#: run is given a timeout so it cannot hang the dialog forever if so.
CUPP_PROFILE_FIELDS = (
    ("first_name", True, False),
    ("surname", False, False),
    ("nickname", False, False),
    ("birthdate", False, True),
    ("partner_name", False, False),
    ("partner_nickname", False, False),
    ("partner_birthdate", False, True),
    ("child_name", False, False),
    ("child_nickname", False, False),
    ("child_birthdate", False, True),
    ("pet_name", False, False),
    ("company", False, False),
)


def _valid_date(value):
    return value == "" or (len(value) == 8 and value.isdigit())


def cupp_answers_valid(profile):
    """Whether *profile* (a ``{field: text}`` dict) is complete enough to
    send to CUPP without it waiting for more than this module will give
    it: the first name is not empty, and every date is blank or exactly 8
    digits (``DDMMYYYY``, CUPP's own format)."""
    if not profile.get("first_name", "").strip():
        return False
    return all(_valid_date(profile.get(field, "").strip())
              for field, _required, is_date in CUPP_PROFILE_FIELDS
              if is_date)


def _cupp_stdin(profile, extra_words, add_special_chars, add_numbers,
               use_leet):
    lines = [profile.get(field, "").strip()
             for field, _required, _is_date in CUPP_PROFILE_FIELDS]
    lines.append("y" if extra_words else "n")
    if extra_words:
        lines.append(extra_words)
    lines.append("y" if add_special_chars else "n")
    lines.append("y" if add_numbers else "n")
    lines.append("y" if use_leet else "n")
    return "\n".join(lines) + "\n"


def run_cupp(cupp_path, profile, output_path, *, extra_words="",
            add_special_chars=False, add_numbers=False, use_leet=False,
            timeout=120):
    """Run CUPP's interactive profiling with the answers in *profile* (see
    :data:`CUPP_PROFILE_FIELDS`), and move the wordlist it writes to
    *output_path*. Raises :class:`RecoveryUnavailable` if CUPP did not
    produce a wordlist in time (a different version asking something this
    module does not know how to answer, most likely)."""
    if not cupp_answers_valid(profile):
        raise RecoveryUnavailable(
            "A name is needed, and a birthdate must be blank or exactly "
            "8 digits (DDMMYYYY).")
    folder = tempfile.mkdtemp(prefix="ios-backup-explorer-cupp-")
    try:
        before = set(os.listdir(folder))
        stdin_text = _cupp_stdin(profile, extra_words, add_special_chars,
                                 add_numbers, use_leet)
        try:
            done = subprocess.run(
                [sys.executable, cupp_path, "-i"], input=stdin_text,
                capture_output=True, text=True, timeout=timeout, cwd=folder,
                **_QUIET)
        except subprocess.TimeoutExpired as exc:
            raise RecoveryUnavailable(
                "CUPP did not finish within the time given; it may be a "
                "different version than this program expects. Its own "
                f"output so far:\n{(exc.stdout or '')[-2000:]}") from None
        new_files = [name for name in set(os.listdir(folder)) - before
                    if name.lower().endswith(".txt")]
        if not new_files:
            raise RecoveryUnavailable(
                "CUPP did not write a wordlist. Its own output:\n"
                f"{(done.stdout or '') + (done.stderr or '')}"[-2000:])
        # the newest, in case more than one appeared
        new_files.sort(key=lambda name: os.path.getmtime(
            os.path.join(folder, name)))
        shutil.move(os.path.join(folder, new_files[-1]), output_path)
        return output_path
    finally:
        shutil.rmtree(folder, ignore_errors=True)
