# qet-verify

Checks a [QElectroTech](https://github.com/qelectrotech/qelectrotech-source-mirror)
change before you open a pull request. Needs only Python 3 and a QElectroTech
checkout. It fails only on a problem **your change adds**.

```bash
git clone <this repo> && cd qet-verify
./verify.sh --qet-dir ~/qet/qelectrotech-source-mirror
```

Add `--binary <path to your built qelectrotech>` to also run the save check.
It prints `PASS`, `FAIL` or `SKIP` per check, and the file holding the details
for any failure. A `SKIP` is not a pass: it means the check did not run.

| # | Check | Needs a build | What a FAIL means |
|---|---|---|---|
| 1 | `tools/qet-lint` | no | Your change added a broken wire, a bad coordinate (NaN) or another file problem in the example projects or symbols |
| 2 | `tools/srclint` | no | A new interface string in `tr()` is not English |
| 3 | `tools/determinism` | yes | Saving and reloading a project lost or invented an element, wire or terminal |
| 4 | `tools/qetdb` round trip | yes | A project saved as `.qetdb` and read back is not the same as saved as `.qet`: data the `.qet` keeps is missing from the database. Covers the examples, `tests/qttest/fixtures` and a project with bridges |
| 5 | `tools/qetdb` scan | no | The change adds saved data to an XML writer but does not touch `sources/dataBase`, add a fixture, or say `qetdb: not needed (reason)` in a commit message |
| 6 | how-to video stories (optional, `--videos <folder>`) | yes | A story that a how-to video was recorded from no longer runs on this build: a menu was renamed, a dialog changed, or the result is not what the video shows. Re-record that video. Uses `qelectrotech-docker/tools/how-to-video` next to this repo, or `--video-tool <dir>`; needs Xvfb, openbox, xdotool, cmake and Qt 6 dev files |

Takes about 15 seconds without `--binary`, about a minute with it. Checks 1
and 2 fetch upstream `master` into your checkout (a private ref,
`refs/qet-verify/upstream-master`; your branches are not touched) and compare
your commit with the commit your branch started from, so a problem already on
`master` never fails your pull request. Without a network they fall back to the
stored baselines, and the receipt says so.

## Updates

`verify.sh` fetches its own repository before every run and fast-forwards to the latest
version, then runs that version. Set `QET_VERIFY_NO_UPDATE=1` to skip it. The receipt's
`verifier:` line says `up to date`, `updated just now`, or why it could not check. A copy
downloaded as a zip has no git history and cannot update itself.

## The receipt

At the end `verify.sh` prints a short block to paste into the pull request description:

```
qet-verify receipt
change:    9edfbf234 on master (tree clean)
checks:    project files PASS | english text PASS | save check PASS
baseline:  upstream master 4a91ca8a1, branch point 9edfbf234 (save check: upstream master 9edfbf234)
verifier:  qet-verify 16c832f
```

`change` is the commit the checks ran on. If it is not the last commit of the
pull request, or says `UNCOMMITTED CHANGES`, the checks are out of date: run
again. A `SKIP` means that check did not run.

A pasted receipt shows the checks were run; it does not prove it, because
anyone can type one. To be sure, run `verify.sh` yourself (about a minute).
Proof needs a check that runs on GitHub's servers.

## What it does not check

It does not decide whether a feature should exist or whether the design is
right. A maintainer still decides that. It also does not run QET's unit tests
(`ctest` in your build folder) or a sanitizer build; run those yourself.

## For maintainers: refreshing the baselines

Checks 1 and 2 make their baseline on every run, so `baselines/qet-lint.json`
and `baselines/srclint.json` are only the offline fallback. The save check
(3) needs a build of `master` and still uses `baselines/determinism.json`.
Refresh after upstream accepts a new finding on purpose:

```bash
./verify.sh --qet-dir <clean master checkout> --binary <its build> --make-baselines
```

Stored baselines: upstream `master` at `9edfbf234` (2026-10-25), built with Qt 6.
All 24 example projects save identically twice and keep every element, wire
and terminal. Use a Qt 6 build for `--binary`.

## Licence

GPL-2.0-or-later, the same as QElectroTech: version 2 of the GNU General
Public License, or (at your option) any later version. Full text in `LICENSE`;
each source file carries an SPDX line.
