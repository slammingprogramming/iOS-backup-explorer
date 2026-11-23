# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — a connected iPhone or iPad, through libimobiledevice
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

"""Pairing with, backing up and looking after a device plugged in by USB, on
every system that has `libimobiledevice <https://libimobiledevice.org>`_'s
command-line tools: ``idevice_id``, ``ideviceinfo``, ``idevicepair``,
``idevicebackup2`` and ``idevicecrashreport``. On Linux they come from the
distribution (``libimobiledevice-utils`` and ``usbmuxd``); on macOS from
Homebrew; Windows builds exist too. They are the same programs the Linux
desktop's own backup tools use.

Nothing here is a dependency of the program. It only looks for the tools
(``Toolbox``), never downloads or installs one, and runs each as a separate
program, so their licence (LGPL-2.1-or-later) stays theirs. Talking to a
device is talking to a USB cable, through the local ``usbmuxd`` service; no
network is involved and nothing leaves the computer.

Backups made this way are ordinary iTunes/Finder backups (the same folder of
``Info.plist``, ``Manifest.plist``, ``Status.plist`` and hashed files named
by the device's UDID), which the rest of the program, and Apple's own
software, open as they open any other.

What is deliberately *not* here: restoring a backup to a device. It is the
one operation that can destroy what is on the phone, and Apple's own
software does it well.

Passwords never appear on a command line (where any other program of the
computer could read them): they go to the tool through its environment
(``BACKUP_PASSWORD``, ``BACKUP_PASSWORD_NEW``), which ``idevicebackup2``
reads for this purpose.
"""

import codecs
import dataclasses
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading

_QUIET = {"creationflags": 0x08000000} if sys.platform.startswith("win") \
    else {}                                       # no console window flashes

TOOL_NAMES = ("idevice_id", "ideviceinfo", "idevicepair", "idevicebackup2",
              "idevicecrashreport")

#: Where a program started from a desktop icon may not look, but the package
#: managers of macOS (Homebrew, Apple silicon and Intel) put these tools.
FALLBACK_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

# What went wrong, as the kind of an error (the window picks its wording and
# its advice from this, never from the tool's own text).
TOOL_MISSING = "tool-missing"
NO_DEVICE = "no-device"
NOT_TRUSTED = "not-trusted"
DENIED = "denied"
LOCKED = "locked"
FAILED = "failed"
TIMEOUT = "timeout"
CANCELLED = "cancelled"

# The state of the pairing of this computer with a device.
PAIRED = "paired"
UNPAIRED = "unpaired"

UDID_PATTERN = re.compile(
    r"^(?:[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}|[0-9A-Fa-f]{40})$")
_UDID_IN_TEXT = re.compile(
    r"\b(?:[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}|[0-9A-Fa-f]{40})\b")

# Colour and cursor-movement codes that idevicebackup2 draws its progress
# with (save/restore cursor, "move up", "clear line", ...).
_ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|[78=>cDEHMNOZ])")

HINTS = {
    TOOL_MISSING: (
        "The libimobiledevice tools are not installed. On Debian and Ubuntu: "
        "sudo apt install libimobiledevice-utils usbmuxd; on Fedora: sudo "
        "dnf install libimobiledevice-utils usbmuxd; on Arch: sudo pacman "
        "-S libimobiledevice usbmuxd; on macOS: brew install "
        "libimobiledevice."),
    NO_DEVICE: (
        "No device was found. Plug it in with its cable, unlock it and, if "
        "it asks, tap Trust. On Linux the usbmuxd service must be running "
        "(systemctl status usbmuxd) and you may need to be allowed to use "
        "USB devices."),
    NOT_TRUSTED: (
        "The device is waiting for you. Unlock it, tap Trust on its screen "
        "and enter its passcode, then try again."),
    DENIED: (
        "The device refused this computer (Don't Trust was tapped). Unplug "
        "it, plug it in again and tap Trust."),
    LOCKED: (
        "The device is locked. Unlock it, keep the screen on, and try "
        "again."),
}


class DeviceError(Exception):
    """Something the device or the tools reported. ``kind`` is one of the
    constants above; ``str(error)`` says what happened and, where it can,
    what to do."""

    def __init__(self, kind, message=None, detail=""):
        self.kind = kind
        self.detail = detail
        text = message or HINTS.get(kind, "The operation failed.")
        super().__init__(text)


def clean_output(text):
    """*text* without the control codes a tool draws its progress with, and
    with carriage returns made into line ends."""
    text = _ANSI.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def valid_udid(udid):
    """Is *udid* the identifier of a device (and so safe to hand to a tool,
    which would take anything starting with a dash for an option)?"""
    return bool(udid) and bool(UDID_PATTERN.match(udid))


def explain(text):
    """The kind of error a tool's output describes, or None when it does not
    describe one. Matches what libimobiledevice itself prints."""
    low = text.lower()
    if any(s in low for s in ("no device found", "no device with udid",
                              "unable to retrieve device list",
                              "device not found")):
        return NO_DEVICE
    if "user denied the trust dialog" in low:
        return DENIED
    if "trust dialog" in low or "pairing_dialog_response_pending" in low:
        return NOT_TRUSTED
    if "passcode" in low and "confirm" not in low \
            and ("enter the passcode" in low or "passcode is set" in low):
        return LOCKED
    if "password protected" in low:
        return LOCKED
    return None


# ── Finding and running the tools ─────────────────────────────

@dataclasses.dataclass
class Result:
    """What a finished tool printed: *stdout* and *stderr* as text."""
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def text(self):
        """Everything it printed, cleaned, for showing or for matching."""
        return clean_output(self.stdout + self.stderr)


def default_runner(argv, env, timeout):
    """Run *argv* to completion; ``(returncode, stdout, stderr)`` as bytes."""
    try:
        done = subprocess.run(
            argv, capture_output=True, timeout=timeout, env=env,
            stdin=subprocess.DEVNULL, **_QUIET)
    except subprocess.TimeoutExpired:
        raise DeviceError(TIMEOUT, "The device did not answer in time.")
    except OSError as error:
        raise DeviceError(FAILED, f"The tool could not be started: {error}")
    return done.returncode, done.stdout, done.stderr


class Toolbox:
    """The libimobiledevice tools found on this computer, and the way to run
    them. *folder* is where to look first (a folder the person chose);
    *which* and *runner* exist so that tests need no real tools."""

    def __init__(self, folder=None, which=shutil.which, runner=None):
        self.folder = folder or None
        self._runner = runner or default_runner
        self.paths = {name: self._find(name, which) for name in TOOL_NAMES}

    def _find(self, name, which):
        if self.folder:
            for candidate in (name, name + ".exe"):
                path = os.path.join(self.folder, candidate)
                if os.path.isfile(path):
                    return path
        found = which(name)
        if found:
            return found
        extra = os.pathsep.join(d for d in FALLBACK_DIRS if os.path.isdir(d))
        return which(name, path=extra) if extra else None

    def has(self, name):
        return self.paths.get(name) is not None

    @property
    def missing(self):
        return [n for n in TOOL_NAMES if not self.has(n)]

    @property
    def can_list(self):
        return self.has("idevice_id")

    @property
    def can_backup(self):
        return self.has("idevicebackup2") and self.has("idevice_id")

    def argv(self, name, *args):
        path = self.paths.get(name)
        if not path:
            raise DeviceError(TOOL_MISSING, f"{name} was not found. "
                              + HINTS[TOOL_MISSING])
        return [path, *args]

    def run(self, name, args, *, env_extra=None, timeout=30):
        """Run tool *name* with *args* (a list; never a shell line)."""
        env = None
        if env_extra:
            env = dict(os.environ)
            env.update(env_extra)
        code, out, err = self._runner(self.argv(name, *args), env, timeout)
        return Result(code, (out or b"").decode("utf-8", "replace"),
                      (err or b"").decode("utf-8", "replace"))

    # ── The device ────────────────────────────────────────────

    def devices(self):
        """The UDIDs of the devices plugged in, in the order the tool gave
        them."""
        result = self.run("idevice_id", ["-l"])
        kind = explain(result.text)
        if kind or result.returncode != 0:
            raise DeviceError(kind or FAILED, None if kind else
                              "The list of devices could not be read. "
                              + HINTS[NO_DEVICE], result.text)
        found = []
        for line in result.text.splitlines():
            token = line.strip().split(" ")[0]
            if valid_udid(token) and token not in found:
                found.append(token)
        return found

    def _query(self, udid, *domain_args):
        """``ideviceinfo -x`` for one domain, as a dict."""
        self._need_udid(udid)
        result = self.run("ideviceinfo", ["-u", udid, "-x", *domain_args])
        text = result.stdout.lstrip()
        if not text.startswith(("<?xml", "<plist", "bplist")):
            kind = explain(result.text) or FAILED
            raise DeviceError(kind, None if kind != FAILED else
                              "The device's details could not be read.",
                              result.text)
        try:
            data = plistlib.loads(result.stdout.encode("utf-8"))
        except Exception as error:
            raise DeviceError(FAILED, "The device's details were not in a "
                              f"form that could be read ({error}).")
        return data if isinstance(data, dict) else {}

    def info(self, udid):
        """A :class:`DeviceInfo`. The basic part must be readable; the
        storage, battery and backup-encryption parts are left out (None)
        when the device does not give them."""
        base = self._query(udid)
        info = DeviceInfo(
            udid=str(base.get("UniqueDeviceID") or udid),
            name=str(base.get("DeviceName") or ""),
            model=str(base.get("ProductType") or ""),
            product=str(base.get("ProductName") or ""),
            version=str(base.get("ProductVersion") or ""),
            build=str(base.get("BuildVersion") or ""),
            serial=str(base.get("SerialNumber") or ""),
            passcode_set=base.get("PasswordProtected"))
        for domain, fill in (
                ("com.apple.disk_usage", info._fill_storage),
                ("com.apple.mobile.battery", info._fill_battery),
                ("com.apple.mobile.backup", info._fill_backup)):
            try:
                fill(self._query(udid, "-q", domain))
            except DeviceError:
                pass
        return info

    def encrypts_backups(self, udid):
        """True when the device encrypts its backups, False when it does
        not, None when it did not say."""
        info = DeviceInfo(udid=udid)
        info._fill_backup(self._query(udid, "-q", "com.apple.mobile.backup"))
        return info.encrypts_backups

    # ── Pairing ───────────────────────────────────────────────

    def pairing(self, udid):
        """PAIRED or UNPAIRED for this computer; raises DeviceError when the
        device is not there or is locked."""
        self._need_udid(udid)
        result = self.run("idevicepair", ["-u", udid, "validate"])
        text = result.text
        if "SUCCESS" in text and "alidated" in text:
            return PAIRED
        if "not paired" in text.lower():
            return UNPAIRED
        kind = explain(text)
        if kind:
            raise DeviceError(kind, detail=text)
        raise DeviceError(FAILED, "Whether this computer is paired with the "
                          "device could not be told.", text)

    def pair(self, udid):
        """Ask the device to trust this computer (the person taps Trust on
        the device). Returns PAIRED, or raises DeviceError (NOT_TRUSTED
        while the question on the device is unanswered)."""
        self._need_udid(udid)
        result = self.run("idevicepair", ["-u", udid, "pair"], timeout=60)
        text = result.text
        if "SUCCESS" in text and "aired" in text:
            return PAIRED
        raise DeviceError(explain(text) or FAILED,
                          None if explain(text) else
                          "Pairing with the device failed.", text)

    def unpair(self, udid):
        """Make the device forget this computer."""
        self._need_udid(udid)
        result = self.run("idevicepair", ["-u", udid, "unpair"])
        if "SUCCESS" in result.text and "npaired" in result.text:
            return UNPAIRED
        raise DeviceError(explain(result.text) or FAILED,
                          None if explain(result.text) else
                          "The device could not be unpaired.", result.text)

    # ── Backup encryption ─────────────────────────────────────

    def set_encryption(self, udid, enable, password):
        """Turn the device's backup encryption on (with *password*) or off
        (*password* is the current one). The device may ask for its passcode
        to confirm. Raises DeviceError if it did not take."""
        self._need_udid(udid)
        if not password:
            raise DeviceError(FAILED, "A backup password is needed.")
        word = "on" if enable else "off"
        result = self.run(
            "idevicebackup2", ["-u", udid, "encryption", word],
            env_extra={"BACKUP_PASSWORD": password}, timeout=180)
        text = _no_secret(result.text, password)
        done = ("has been enabled successfully" if enable
                else "has been disabled successfully")
        if done in text:
            return True
        raise DeviceError(explain(text) or FAILED, _last_problem(text) or
                          "The device did not change its backup encryption.",
                          text)

    def change_password(self, udid, old, new):
        """Change the device's backup password from *old* to *new*."""
        self._need_udid(udid)
        if not old or not new:
            raise DeviceError(FAILED, "The old and the new password are "
                              "both needed.")
        result = self.run(
            "idevicebackup2", ["-u", udid, "changepw"],
            env_extra={"BACKUP_PASSWORD": old, "BACKUP_PASSWORD_NEW": new},
            timeout=180)
        text = _no_secret(_no_secret(result.text, old), new)
        if "password has been changed successfully" in text:
            return True
        raise DeviceError(explain(text) or FAILED, _last_problem(text) or
                          "The device did not change its backup password. "
                          "Was the old password right?", text)

    # ── Crash reports ─────────────────────────────────────────

    def crash_reports(self, udid, folder, keep=True):
        """Copy the crash reports the device holds into *folder* (they are
        left on the device unless *keep* is false, which asks it to remove
        what it handed over). Returns the number of files copied."""
        self._need_udid(udid)
        os.makedirs(folder, exist_ok=True)
        before = _count_files(folder)
        args = ["-u", udid, "-e"] + (["-k"] if keep else []) + [folder]
        result = self.run("idevicecrashreport", args, timeout=600)
        count = _count_files(folder) - before
        text = result.text
        if count == 0 and (kind := explain(text)):
            raise DeviceError(kind, detail=text)
        if result.returncode != 0 and count == 0 \
                and "ERROR" in text:
            raise DeviceError(FAILED, _last_problem(text) or
                              "The crash reports could not be copied.", text)
        return count

    # ── Backup ────────────────────────────────────────────────

    def start_backup(self, udid, folder, full=False, **callbacks):
        """Start a backup of the device into *folder* (a folder that holds
        backups; this one's own folder, named by the UDID, is made inside
        it) and return the :class:`BackupRun`, already running. See
        ``BackupRun`` for the callbacks."""
        self._need_udid(udid)
        os.makedirs(folder, exist_ok=True)
        args = ["-u", udid, "backup"] + (["--full"] if full else []) \
            + [folder]
        run = BackupRun(self.argv("idevicebackup2", *args), udid, folder,
                        **callbacks)
        run.start()
        return run

    @staticmethod
    def _need_udid(udid):
        if not valid_udid(udid):
            raise DeviceError(FAILED, "That is not a device identifier.")


def _count_files(folder):
    total = 0
    for _root, _dirs, files in os.walk(folder):
        total += len(files)
    return total


def _last_problem(text):
    """The most telling line of a tool's output about what went wrong."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in reversed(lines):
        if line.startswith(("ERROR", "ErrorCode", "Could not")) \
                or "Failed" in line or "Aborted" in line:
            return line
    return ""


def _no_secret(text, secret):
    """*text* with every copy of a password removed, for what is kept to
    show or to report."""
    return text.replace(secret, "…") if secret else text


@dataclasses.dataclass
class DeviceInfo:
    """What a device says about itself; None where it did not say."""
    udid: str = ""
    name: str = ""
    model: str = ""
    product: str = ""
    version: str = ""
    build: str = ""
    serial: str = ""
    passcode_set: object = None
    storage_total: object = None
    storage_free: object = None
    battery: object = None
    encrypts_backups: object = None

    def _fill_storage(self, data):
        total = data.get("TotalDataCapacity")
        free = data.get("TotalDataAvailable")
        self.storage_total = total if isinstance(total, int) else None
        self.storage_free = free if isinstance(free, int) else None

    def _fill_battery(self, data):
        level = data.get("BatteryCurrentCapacity")
        self.battery = level if isinstance(level, int) else None

    def _fill_backup(self, data):
        will = data.get("WillEncrypt")
        self.encrypts_backups = will if isinstance(will, bool) else None


# ── A backup in progress ──────────────────────────────────────

_OVERALL = re.compile(r"^Backup\b.*?(\d{1,3}(?:\.\d+)?)\s*%")
_OLD_BAR = re.compile(r"^\[[=> ]*\]\s*(\d{1,3}(?:\.\d+)?)\s*%")
_SUCCESS = "Backup Successful."


def parse_progress(line):
    """The overall percentage (0 to 100) a progress *line* of
    ``idevicebackup2`` shows, or None. Newer versions label the whole
    backup's bar "Backup"; older ones print only a bar."""
    for pattern in (_OVERALL, _OLD_BAR):
        found = pattern.match(line.strip())
        if found:
            return max(0.0, min(100.0, float(found.group(1))))
    return None


class BackupRun:
    """One ``idevicebackup2 backup`` process, running in the background.

    *on_progress(percent)* is called as the overall progress moves;
    *on_line(text)* with every other line worth showing (what the device
    asks for, errors); *on_done(outcome)* once, when it exits. All three are
    called from a worker thread: a window posts them to its own thread.

    The *outcome* is a :class:`BackupOutcome`. Success is when the tool says
    "Backup Successful.", not merely when it exits cleanly (it can exit with
    a failure code and still have said so, and the reverse).
    """

    def __init__(self, argv, udid, folder, *, on_progress=None, on_line=None,
                 on_done=None, popen=subprocess.Popen):
        self.argv = argv
        self.udid = udid
        self.folder = folder
        self._on_progress = on_progress
        self._on_line = on_line
        self._on_done = on_done
        self._popen = popen
        self._process = None
        self._thread = None
        self._stopped = False
        self.lines = []

    @property
    def backup_folder(self):
        """Where this device's backup is (or will be)."""
        return os.path.join(self.folder, self.udid)

    def start(self):
        self._process = self._popen(
            self.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, bufsize=0, **_QUIET)
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="idevicebackup2")
        self._thread.start()

    def _emit(self, text):
        text = text.strip()
        if not text:
            return
        percent = parse_progress(text)
        if percent is not None:
            if self._on_progress:
                self._on_progress(percent)
            return
        if self.lines and self.lines[-1] == text:
            return
        self.lines.append(text)
        if len(self.lines) > 400:
            del self.lines[:100]
        if self._on_line:
            self._on_line(text)

    def _pump(self):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        stream = self._process.stdout
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                pending += clean_output(decoder.decode(chunk))
                *complete, pending = pending.split("\n")
                for part in complete:
                    self._emit(part)
            pending += decoder.decode(b"", final=True)
            for part in clean_output(pending).split("\n"):
                self._emit(part)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass
            code = self._process.wait()
            if self._on_done:
                self._on_done(self._outcome(code))

    def _outcome(self, code):
        text = "\n".join(self.lines)
        if self._stopped or "Backup Aborted." in text:
            return BackupOutcome(False, CANCELLED, "The backup was stopped.",
                                 self.backup_folder, code)
        if _SUCCESS in text:
            return BackupOutcome(True, None, "The backup is complete.",
                                 self.backup_folder, code)
        kind = explain(text) or FAILED
        if kind == FAILED:
            message = _last_problem(text) or "The backup did not finish."
        else:
            message = HINTS[kind]
        return BackupOutcome(False, kind, message, self.backup_folder, code)

    def stop(self):
        """Ask the tool to stop. What it already copied stays in the
        folder; the backup is then marked unfinished and the next one
        carries on from it."""
        self._stopped = True
        process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)
        return not (self._thread and self._thread.is_alive())


@dataclasses.dataclass
class BackupOutcome:
    ok: bool
    kind: object          # None, or one of the error kinds above
    message: str
    folder: str           # this device's backup folder
    returncode: int = 0
