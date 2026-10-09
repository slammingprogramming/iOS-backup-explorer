# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — mounting a backup as a read-only file system
# Copyright (C) 2026 slammingprogramming and contributors
#
# The idea of exposing a backup as a mounted <domain>/<relativePath> tree
# (decrypting each file the first time it is opened) comes from Nikhil-42's
# pull request #2 to the upstream BackupLens project, which is MIT-licensed
# (https://github.com/mrgunes/BackupLens/pull/2). This is an independent
# implementation for this project's architecture. Credit to the original
# author and to Nikhil-42 is kept in AUTHORS and NOTICE.
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

"""Mount an opened backup as a read-only file system (FUSE / WinFsp).

* Linux and macOS: the backup appears in an empty folder you choose
  (needs libfuse, or macFUSE / FUSE-T on macOS).
* Windows: the backup appears as a UNC path, ``\\\\ios-backup\\<name>``,
  with no drive letter (needs WinFsp, https://winfsp.dev).

The Python binding, ``mfusepy``, is an optional dependency that is only
imported when a backup is actually mounted.

The file-system logic (:class:`BackupTree`, :class:`BackupFilesystem`) is
plain Python with no FUSE import, so it can be tested anywhere; only
:class:`Mount` talks to FUSE.
"""

import errno
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import time

from ios_backup_explorer import sanitize_component

SERVER_NAME = "ios-backup"
"""The "server" part of the UNC path used on Windows."""

_IS_WINDOWS = os.name == "nt"

# os.O_ACCMODE does not exist on Windows; the access mode is the low two
# bits there too (O_RDONLY=0, O_WRONLY=1, O_RDWR=2).
_O_ACCMODE = getattr(os, "O_ACCMODE", 3)

_HELP = {
    "Windows": (
        "Install WinFsp from https://winfsp.dev (a small driver; it needs "
        "administrator approval once), then:\n"
        "  pip install mfusepy"
    ),
    "Darwin": (
        "Install macFUSE (https://macfuse.github.io) or FUSE-T "
        "(https://www.fuse-t.org), then:\n"
        "  pip install mfusepy"
    ),
    "Linux": (
        "Install FUSE (for example: sudo apt install fuse3) and then:\n"
        "  pip install mfusepy"
    ),
}


class MountUnavailableError(RuntimeError):
    """Mounting is not possible on this computer as it is set up."""


class MountError(RuntimeError):
    """The mount could not be created."""


def load_fuse():
    """Import ``mfusepy``, or explain what to install."""
    help_text = _HELP.get(platform.system())
    if help_text is None:
        raise MountUnavailableError(
            f"Mounting is not supported on {platform.system()}."
        )
    try:
        import mfusepy
    except ImportError as exc:
        raise MountUnavailableError(
            "Mounting needs the optional 'mfusepy' package.\n\n" + help_text
        ) from exc
    except Exception as exc:  # the FUSE library itself is missing or broken
        raise MountUnavailableError(
            f"The FUSE library could not be loaded ({exc}).\n\n" + help_text
        ) from exc
    return mfusepy


def default_share_name(backup_dir):
    """A UNC-safe share name taken from the backup folder's name."""
    name = os.path.basename(os.path.normpath(backup_dir))
    if name in ("", ".", ".."):
        name = "backup"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:40]


def unc_path(share):
    return f"\\\\{SERVER_NAME}\\{share}"


# ── The tree ─────────────────────────────────────────────────

class _Dir:
    __slots__ = ("children",)

    def __init__(self):
        self.children = {}   # lookup key -> (display name, node)


class _File:
    __slots__ = ("file_id", "size", "mtime")

    def __init__(self, file_id, size, mtime):
        self.file_id = file_id
        self.size = size
        self.mtime = mtime


class BackupTree:
    """The backup as ``<domain>/<relativePath>`` directories and files.

    *rows* are ``(file_id, domain, relative_path, size, mtime)``. Names are
    made valid for the host (Windows cannot store ``? : *`` and similar),
    and names that would collide, including by letter case where the host
    ignores case, get the file ID appended instead of hiding one another.
    """

    def __init__(self, rows, windows=None, case_insensitive=None):
        if windows is None:
            windows = _IS_WINDOWS
        if case_insensitive is None:
            case_insensitive = windows or platform.system() == "Darwin"
        self._windows = windows
        self._fold = case_insensitive
        self.root = _Dir()
        self.file_count = 0
        self.total_size = 0
        for file_id, domain, rel_path, size, mtime in rows:
            self._add(file_id, domain, rel_path, size, mtime)

    def _key(self, name):
        return name.casefold() if self._fold else name

    def _add(self, file_id, domain, rel_path, size, mtime):
        parts = [domain] + [p for p in rel_path.split("/")
                            if p not in ("", ".", "..")]
        if len(parts) < 2:
            return
        parts = [sanitize_component(p, self._windows) for p in parts]
        node = self.root
        for name in parts[:-1]:
            node = self._subdirectory(node, name, file_id)
        self._put_file(node, parts[-1], _File(file_id, size, mtime))
        self.file_count += 1
        self.total_size += size

    def _subdirectory(self, node, name, file_id):
        entry = node.children.get(self._key(name))
        if entry is None:
            child = _Dir()
            node.children[self._key(name)] = (name, child)
            return child
        if isinstance(entry[1], _Dir):
            return entry[1]
        # A file already has this name: put the directory beside it.
        return self._subdirectory(node, f"{name}_{file_id[:8]}", file_id)

    def _put_file(self, node, name, entry):
        stem, ext = os.path.splitext(name)
        candidate, counter = name, 0
        while self._key(candidate) in node.children:
            suffix = entry.file_id[:8] + (f"-{counter}" if counter else "")
            candidate = f"{stem}_{suffix}{ext}"
            counter += 1
        node.children[self._key(candidate)] = (candidate, entry)

    def lookup(self, path):
        """The directory or file at *path* (``/a/b``), or None."""
        node = self.root
        for part in path.split("/"):
            if not part:
                continue
            if not isinstance(node, _Dir):
                return None
            entry = node.children.get(self._key(part))
            if entry is None:
                return None
            node = entry[1]
        return node

    @staticmethod
    def names(directory):
        return [display for display, _node in directory.children.values()]

    @staticmethod
    def is_dir(node):
        return isinstance(node, _Dir)


# ── The file system ──────────────────────────────────────────

def _oserror(code):
    return OSError(code, os.strerror(code))


class BackupFilesystem:
    """Read-only FUSE operations over a :class:`BackupTree`.

    *fetch(file_id)* must return the path of a readable local file holding
    that file's data (it may block while the data is being decrypted).
    Errors are plain ``OSError`` with an errno, which FUSE bindings turn
    into the matching error code.
    """

    use_ns = True   # mfusepy: timestamps are nanoseconds

    def __init__(self, tree, fetch):
        self._tree = tree
        self._fetch = fetch
        self._mounted_ns = time.time_ns()
        self._read_lock = threading.Lock()
        self._exit_requested = False
        self.exit_hook = None   # set by Mount: asks FUSE to stop serving
        self.on_ready = None    # set by Mount: called once FUSE is serving

    # -- lifecycle --------------------------------------------

    def request_exit(self):
        """Stop serving at the next request (see Mount.stop)."""
        self._exit_requested = True

    def _maybe_exit(self):
        if self._exit_requested and self.exit_hook is not None:
            self.exit_hook()

    def init(self, path):
        if self.on_ready is not None:
            self.on_ready()

    # -- reading ----------------------------------------------

    def getattr(self, path, fh=None):
        self._maybe_exit()
        node = self._tree.lookup(path)
        if node is None:
            raise _oserror(errno.ENOENT)
        owner = {}
        if hasattr(os, "getuid"):
            owner = {"st_uid": os.getuid(), "st_gid": os.getgid()}
        if self._tree.is_dir(node):
            return dict(st_mode=stat.S_IFDIR | 0o500, st_nlink=2, st_size=0,
                        st_ctime=self._mounted_ns, st_mtime=self._mounted_ns,
                        st_atime=self._mounted_ns, **owner)
        when = (int(node.mtime * 1_000_000_000) if node.mtime
                else self._mounted_ns)
        return dict(st_mode=stat.S_IFREG | 0o400, st_nlink=1,
                    st_size=node.size, st_ctime=when, st_mtime=when,
                    st_atime=when, **owner)

    def readdir(self, path, fh):
        node = self._tree.lookup(path)
        if node is None:
            raise _oserror(errno.ENOENT)
        if not self._tree.is_dir(node):
            raise _oserror(errno.ENOTDIR)
        return [".", ".."] + self._tree.names(node)

    def open(self, path, flags):
        node = self._tree.lookup(path)
        if node is None:
            raise _oserror(errno.ENOENT)
        if self._tree.is_dir(node):
            raise _oserror(errno.EISDIR)
        if (flags & _O_ACCMODE) != os.O_RDONLY:
            raise _oserror(errno.EROFS)
        try:
            local = self._fetch(node.file_id)
            return os.open(local, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        except FileNotFoundError:
            raise _oserror(errno.ENOENT) from None
        except OSError:
            raise
        except Exception:
            raise _oserror(errno.EIO) from None

    def read(self, path, size, offset, fh):
        if hasattr(os, "pread"):
            return os.pread(fh, size, offset)
        with self._read_lock:   # Windows: no pread
            os.lseek(fh, offset, os.SEEK_SET)
            return os.read(fh, size)

    def release(self, path, fh):
        os.close(fh)
        return 0

    def statfs(self, path):
        block = 4096
        blocks = -(-self._tree.total_size // block)
        return dict(f_bsize=block, f_frsize=block, f_blocks=blocks,
                    f_bfree=0, f_bavail=0, f_files=self._tree.file_count,
                    f_ffree=0, f_namemax=255)

    # -- everything that would change the backup is refused -----

    def _read_only(self, *args, **kwargs):
        raise _oserror(errno.EROFS)

    write = create = unlink = mkdir = rmdir = truncate = _read_only
    chmod = chown = rename = symlink = link = mknod = utimens = _read_only


# ── Mounting ─────────────────────────────────────────────────

class Mount:
    """A mounted backup. ``start()`` mounts it; ``stop()`` unmounts it."""

    def __init__(self, filesystem, mountpoint=None, share=None,
                 cache_dir=None, fuse=None):
        if _IS_WINDOWS:
            if not share:
                raise ValueError("a share name is required on Windows")
        elif not mountpoint:
            raise ValueError("a mount point is required")
        self.filesystem = filesystem
        self._mountpoint = mountpoint
        self._share = share
        self._cache_dir = cache_dir
        self._fuse = fuse
        self._ready = threading.Event()
        self._finished = threading.Event()
        self._error = None
        self._thread = None
        self.on_stopped = None   # called (on the serving thread) when FUSE ends

    @property
    def display_path(self):
        """Where the user finds the mounted backup."""
        return unc_path(self._share) if _IS_WINDOWS else self._mountpoint

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout=20):
        fuse = self._fuse or load_fuse()
        self.filesystem.exit_hook = fuse.fuse_exit
        self.filesystem.on_ready = self._ready.set
        options = {"foreground": True, "ro": True,
                   "fsname": "ios-backup-explorer"}
        if _IS_WINDOWS:
            # An empty mount point plus a volume prefix gives a UNC-only
            # mount. The prefix needs forward slashes: FUSE's option parser
            # treats a backslash as an escape character.
            target = ""
            options["VolumePrefix"] = f"/{SERVER_NAME}/{self._share}"
            # Owner and group are "the user who mounted it" (-1), so the
            # private permission bits below keep other accounts out.
            options["uid"] = -1
            options["gid"] = -1
            options["volname"] = "iOS-Backup"
        else:
            target = self._mountpoint

        def serve():
            try:
                fuse.FUSE(self.filesystem, target, **options)
            except BaseException as exc:  # noqa: BLE001
                self._error = exc
            finally:
                self._finished.set()
                self._ready.set()
                if self.on_stopped is not None:
                    self.on_stopped()

        self._thread = threading.Thread(target=serve, daemon=True,
                                        name="backup-mount")
        self._thread.start()

        deadline = time.monotonic() + timeout
        self._ready.wait(timeout)
        if self._finished.is_set():
            self._cleanup()
            raise MountError(self._explain(self._error))
        if _IS_WINDOWS:   # serving has begun; wait for the share to appear
            while not os.path.exists(self.display_path):
                if self._finished.is_set() or time.monotonic() > deadline:
                    self.stop()
                    raise MountError("The share did not become available.")
                time.sleep(0.1)

    def _explain(self, error):
        if _IS_WINDOWS:
            return ("WinFsp could not create the mount. The name "
                    f"{self.display_path} may already be in use by another "
                    "mount, or WinFsp may not be running."
                    + (f" ({error})" if error else ""))
        return f"Mounting failed: {error or 'FUSE exited immediately'}"

    def stop(self, timeout=15):
        """Unmount and remove the decrypted cache. True if fully stopped."""
        if self._thread is None:
            return True
        self.filesystem.request_exit()
        poke = threading.Thread(target=self._poke_or_unmount, daemon=True)
        poke.start()
        self._thread.join(timeout)
        stopped = not self._thread.is_alive()
        if stopped:
            self._cleanup()
        return stopped

    def _poke_or_unmount(self):
        if not _IS_WINDOWS:
            command = self._unmount_command()
            if command:
                try:
                    subprocess.run(command, check=False, capture_output=True,
                                   timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
        # Touching the mount runs a FUSE callback, which sees the exit
        # request. This is how WinFsp is stopped, and a fallback elsewhere.
        try:
            os.stat(self.display_path)
        except OSError:
            pass

    def _unmount_command(self):
        if platform.system() == "Darwin":
            return ["umount", self._mountpoint]
        helper = shutil.which("fusermount3") or shutil.which("fusermount")
        return [helper, "-u", self._mountpoint] if helper else None

    def _cleanup(self):
        if self._cache_dir:
            shutil.rmtree(self._cache_dir, ignore_errors=True)
            self._cache_dir = None
