# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — mixing a recording's tracks (optional ffmpeg)
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

"""Turns a recording kept as a movie file with a track for each side of a
call into one mixed ``.m4a`` audio file, with the free program ffmpeg
(https://ffmpeg.org) if it is installed. Nothing here is needed to extract
or play the original file, which is never changed.
"""

import os
import shutil
import subprocess
import sys

_QUIET = {"creationflags": 0x08000000} if sys.platform.startswith("win") \
    else {}                                       # no console window flashes


def find_tool(name):
    """The full path of the program *name* (``ffmpeg``), or None."""
    return shutil.which(name)


def available():
    """Whether recordings can be mixed on this computer."""
    return bool(find_tool("ffmpeg") and find_tool("ffprobe"))


def _run(arguments, timeout):
    return subprocess.run(arguments, capture_output=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, **_QUIET)


def audio_stream_count(path, timeout=60):
    """How many audio tracks the file has (0 if it cannot be read)."""
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        return 0
    try:
        done = _run([ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=index", "-of", "csv=p=0",
                     os.path.abspath(path)], timeout)
    except (OSError, subprocess.SubprocessError):
        return 0
    if done.returncode:
        return 0
    return len([line for line in done.stdout.decode(
        "utf-8", "replace").splitlines() if line.strip()])


def mix_to_m4a(source, destination, timeout=600):
    """Write all audio tracks of *source* mixed into one AAC ``.m4a`` file at
    *destination*. Returns True on success; on failure nothing is left at
    *destination*."""
    ffmpeg = find_tool("ffmpeg")
    count = audio_stream_count(source)
    if not ffmpeg or not count:
        return False
    source, destination = os.path.abspath(source), os.path.abspath(destination)
    base = [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", source, "-vn"]
    tail = ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            destination]
    # (a recording with a single track goes through the same mix)
    inputs = "".join(f"[0:a:{n}]" for n in range(count))
    mix = f"{inputs}amix=inputs={count}:duration=longest"
    # newer ffmpeg can mix without turning each track down; older versions
    # do not know the option, so they get the plain mix
    attempts = [
        base + ["-filter_complex", mix + ":normalize=0[a]",
                "-map", "[a]"] + tail,
        base + ["-filter_complex", mix + "[a]", "-map", "[a]"] + tail]
    for arguments in attempts:
        try:
            done = _run(arguments, timeout)
        except (OSError, subprocess.SubprocessError):
            done = None
        if done is not None and done.returncode == 0 \
                and os.path.isfile(destination) \
                and os.path.getsize(destination) > 0:
            return True
        try:
            os.remove(destination)
        except OSError:
            pass
    return False
