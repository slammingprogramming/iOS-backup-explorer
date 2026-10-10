#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Checks that the version is written down consistently.

The version lives in one place, ``__version__`` in ``ios_backup_explorer.py``.
This check fails if

* it is not a Semantic Versioning number (``MAJOR.MINOR.PATCH``, optionally
  with a pre-release such as ``2.1.0-rc.1``),
* the changelog does not have a ``## [version] - date`` heading for it, or
  has a newer release heading than the version,
* the README's version badge shows another version.

Run from the repository's top folder: ``python tools/check_version.py``.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
RELEASE = re.compile(r"^## \[(?P<version>[^\]]+)\] - (?P<date>\d{4}-\d\d-\d\d)",
                     re.M)


def code_version(root=ROOT):
    text = (root / "ios_backup_explorer.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    return found.group(1) if found else None


def releases(root=ROOT):
    """``[(version, date), ...]`` from the changelog, newest first."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    return [(m.group("version"), m.group("date"))
            for m in RELEASE.finditer(text)]


def problems(root=ROOT):
    found = []
    version = code_version(root)
    if version is None:
        return ["ios_backup_explorer.py has no __version__"]
    if not SEMVER.match(version):
        found.append(f"__version__ {version!r} is not a Semantic "
                     "Versioning number")
    listed = releases(root)
    if not listed:
        found.append("CHANGELOG.md has no '## [x.y.z] - date' release "
                     "heading")
    else:
        newest = listed[0][0]
        if newest != version:
            found.append(f"__version__ is {version} but the newest release "
                         f"in CHANGELOG.md is {newest}")
        if len({v for v, _ in listed}) != len(listed):
            found.append("CHANGELOG.md lists a version twice")
    readme = (root / "README.md").read_text(encoding="utf-8")
    badge = re.search(r"img\.shields\.io/badge/version-(.+?)-[A-Za-z]+[\"?]",
                      readme)
    if badge is None:
        found.append("README.md has no version badge")
    elif badge.group(1).replace("--", "-") != version:
        found.append(f"the README badge says {badge.group(1)}, "
                     f"__version__ is {version}")
    return found


def main():
    found = problems()
    for line in found:
        print("Version check failed:", line)
    if not found:
        print(f"Version check passed ({code_version()}).")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
