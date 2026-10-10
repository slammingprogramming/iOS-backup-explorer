#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""What a release is made of; used by .github/workflows/release.yml.

    python tools/release.py verify vX.Y.Z      the tag matches the code
    python tools/release.py notes  vX.Y.Z      the release notes (stdout)
    python tools/release.py build  vX.Y.Z      the files to attach (dist/)

``verify`` fails unless the tag is ``v`` plus ``__version__`` and the
changelog has a section for it. ``notes`` prints that section, with how to
install and check the download underneath. ``build`` writes a ``.zip`` and a
``.tar.gz`` of the tagged files (``git archive``, so only what is committed
and the same bytes every time) and a ``SHA256SUMS`` file for them.

Only the standard library and ``git`` are used. Run from anywhere.
"""

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_version                                     # noqa: E402

NAME = "iOS-Backup-Explorer"
REPOSITORY = "https://github.com/slammingprogramming/iOS-backup-explorer"
TAG = re.compile(r"^v(?P<version>.+)$")


def version_of(tag):
    """``2.1.0`` from ``v2.1.0``; ``ValueError`` if it is not a version tag."""
    match = TAG.match(tag)
    if not match or not check_version.SEMVER.match(match.group("version")):
        raise ValueError(f"{tag!r} is not a version tag like v1.2.3")
    return match.group("version")


def is_prerelease(version):
    """True for ``2.1.0-rc.1``; build metadata (``+x``) does not count."""
    return "-" in version.partition("+")[0]


def problems(tag, root=ROOT):
    """Reasons the tag cannot be released from the files in ``root``."""
    try:
        version = version_of(tag)
    except ValueError as error:
        return [str(error)]
    found = []
    in_code = check_version.code_version(root)
    if in_code != version:
        found.append(f"the tag is {tag} but __version__ is {in_code}")
    if section(version, root) is None:
        found.append(f"CHANGELOG.md has no section for {version}")
    found.extend(check_version.problems(root))
    return found


def section(version, root=ROOT):
    """The changelog text under ``## [version] - date``, or ``None``."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.compile(r"^## \[" + re.escape(version) + r"\][^\n]*\n",
                         re.M)
    start = heading.search(text)
    if start is None:
        return None
    following = re.compile(r"^## ", re.M).search(text, start.end())
    body = text[start.end():following.start() if following else len(text)]
    return body.strip("\n") or None


def notes(version, root=ROOT):
    """The release notes for ``version``: its changelog section and a short
    guide to the download."""
    body = section(version, root)
    if body is None:
        raise ValueError(f"CHANGELOG.md has no section for {version}")
    archive = f"{NAME}-{version}"
    return "\n".join([
        body, "",
        "---", "",
        "### Download and run", "",
        f"Download **{archive}.zip** (or **.tar.gz**) below, unpack it, then:",
        "",
        "```",
        "python -m pip install -r requirements.txt",
        "python ios_backup_explorer.py",
        "```", "",
        "Python 3.9 or newer is needed. Optional extras are in "
        "`requirements-optional.txt` and `requirements-mount.txt`. "
        f"[Installation guide]({REPOSITORY}/blob/v{version}/docs/INSTALL.md).",
        "",
        "To check a download, compare its SHA-256 with **SHA256SUMS** "
        "(`sha256sum -c SHA256SUMS` on Linux and macOS; "
        "`Get-FileHash <file>` in PowerShell). The files are what "
        f"`git archive` makes from the tag, so you can also rebuild them from "
        "a clone.", "",
    ])


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(version, ref, out, root=ROOT):
    """Write the archives and ``SHA256SUMS`` into ``out``; return the paths."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{NAME}-{version}"
    made = []
    for extension, kind in ((".zip", "zip"), (".tar.gz", "tar.gz")):
        target = out / (prefix + extension)
        subprocess.run(
            ["git", "-C", str(root), "archive", f"--format={kind}",
             f"--prefix={prefix}/", "-o", str(target), ref], check=True)
        made.append(target)
    sums = out / "SHA256SUMS"
    # (open(), not Path.write_text(newline=), which needs Python 3.10)
    with open(sums, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("".join(f"{sha256(p)}  {p.name}\n" for p in made))
    return made + [sums]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("verify", "notes", "build",
                                            "prerelease"))
    parser.add_argument("tag", help="the release tag, such as v2.1.0")
    parser.add_argument("--out", default="dist",
                        help="folder for 'build' (default: dist)")
    options = parser.parse_args(argv)
    try:
        version = version_of(options.tag)
    except ValueError as error:
        parser.error(str(error))
    if options.command == "verify":
        found = problems(options.tag)
        for line in found:
            print("Release check failed:", line)
        if not found:
            print(f"Release check passed ({options.tag}).")
        return 1 if found else 0
    if options.command == "notes":
        try:
            text = notes(version)
        except ValueError as error:
            parser.error(str(error))
        # bytes, so a Windows console's code page cannot garble the dashes
        sys.stdout.buffer.write(text.encode("utf-8"))
        return 0
    if options.command == "prerelease":
        print("true" if is_prerelease(version) else "false")
        return 0
    for path in build(version, options.tag, options.out):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
