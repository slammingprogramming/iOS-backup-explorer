# Versioning and releases

From version 2.0.0 on, iOS Backup Explorer follows
[Semantic Versioning 2.0.0](https://semver.org): **MAJOR.MINOR.PATCH**.

The original project, BackupLens, was released as 1.0.0. This fork's first
release is **2.0.0**, a major version because it differs from 1.0.0 in
everything a user sees and in its licence (see the [changelog](../CHANGELOG.md)).

## What each part means

| Change | Bump | Examples |
|---|---|---|
| Something people rely on **stops working the same way** | **MAJOR** | A tab or an export format is removed or renamed; a file or column in an export changes meaning; a required dependency or a newer minimum Python is needed; the licence changes |
| **New** abilities, backwards compatible | **MINOR** | A new tab; a new export format; a new kind of backup that opens; a table that now shows more |
| **Fixes** that change no ability | **PATCH** | A wrong date or unit corrected; a crash fixed; a layout of a newer iOS that now reads; documentation or test changes that ship |

When unsure, ask what a user's saved exports, scripts or habits would notice.
Changes to *how* it is built (internal modules, tests, tools) are not by
themselves a bump, but they ride along with the next release.

Pre-releases use a suffix: `2.1.0-rc.1`. The program's `__version__` and the
changelog heading then carry it too.

## Where the version lives

**One place:** `__version__` in `ios_backup_explorer.py`. It is shown in the
window's title and by `python ios_backup_explorer.py --version`. Everything
else is checked against it by `tools/check_version.py` (run in CI):

- `CHANGELOG.md` must have a heading `## [x.y.z] - YYYY-MM-DD` for it, and no
  newer one;
- the badge in `README.md` must show it.

## The changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com): a
`## [Unreleased]` section at the top collects what changes as you work, grouped
under **Added**, **Changed**, **Fixed** (and *Removed*, *Security* when they
apply). Write for a *user*: what they can now do, see or rely on, not which
function changed. Mention a fix for a bug people could have noticed. Credit
people and upstream issues where they shaped it.

## Making a release

1. **Make sure `main` is green**: the full test suite on both the setup with the
   optional packages and without them, `tools/check_attribution.py`.
2. **Decide the number** from the table above, looking at the *Unreleased*
   section.
3. **Update the version:**
   - `__version__` in `ios_backup_explorer.py`;
   - in `CHANGELOG.md`, rename `## [Unreleased]` to `## [x.y.z] - date`, add a
     fresh empty `## [Unreleased]` above it, and write a short summary of the
     release at the top of its section;
   - the version badge in `README.md`.
4. **Run `python tools/check_version.py`.**
5. **Refresh the screenshots** if the window changed
   ([SCREENSHOTS.md](SCREENSHOTS.md)); they show the version in the title bar.
6. **Commit**, signed: `Release x.y.z`.
7. **Tag** it, signed and annotated, and push both:
   `git tag -s vX.Y.Z -m "iOS Backup Explorer X.Y.Z"` then `git push` and
   `git push origin vX.Y.Z`.
8. **Watch the release workflow** (Actions, *Release*). Pushing the tag is the
   whole release: GitHub Actions does the rest (see below).

Never move or reuse a published tag. If a release is wrong, fix it in a new
patch release.

## What the release workflow does

`.github/workflows/release.yml` runs when a tag like `v2.1.0` or `v2.1.0-rc.1`
is pushed. Its steps are in `tools/release.py`, which you can run yourself:

| Job | What happens |
|---|---|
| **verify** | The tag must be `v` plus `__version__`, the changelog must have a section for it and the README badge must agree (`python tools/release.py verify vX.Y.Z`), and the tagged commit must be on the default branch. Otherwise nothing is published |
| **tests**, **attribution** | The same checks as for every push ([tests.yml](../.github/workflows/tests.yml), [attribution.yml](../.github/workflows/attribution.yml)) run on the tagged commit. A failure stops the release |
| **publish** | Builds `iOS-Backup-Explorer-X.Y.Z.zip` and `.tar.gz` from the tag with `git archive` (so only committed files, the same bytes every time) and a `SHA256SUMS` file; writes the notes from the changelog section, a short guide to running the download and a link comparing with the previous release; and creates the GitHub release. A version with a suffix (`-rc.1`) is marked a *pre-release*; any other is marked *latest* |

Only the **publish** job can write to the repository (`contents: write`); the
other jobs only read. The workflow never creates, moves or deletes a tag.

To try the pieces locally from a clone:

```bash
python tools/release.py verify v2.1.0       # is the tag releasable?
python tools/release.py notes  v2.1.0       # the notes the release will have
python tools/release.py build  v2.1.0       # the files, in dist/ (the tag must exist)
```

**If publishing fails** after the tag is pushed (a network error, say), run the
*Release* workflow again from the tag: Actions, *Release*, *Run workflow*, with
"Use workflow from" set to the tag. It updates the release in place. If the
*verify* or test jobs fail, the tag is wrong: do not move it; fix the problem
and make a new patch release.

## Tags

Tags are named `vMAJOR.MINOR.PATCH`. The tag `v1.0.0` is the original
BackupLens release (kept for history); `v2.0.0` is this project's first.

## Support

Only the newest release is supported with fixes. Security problems are
handled as described in [SECURITY.md](../SECURITY.md).
