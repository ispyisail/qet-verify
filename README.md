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

Takes about 5 seconds without `--binary`, about a minute with it.

## What it does not check

It does not decide whether a feature should exist or whether the design is
right. A maintainer still decides that. It also does not run QET's unit tests
(`ctest` in your build folder) or a sanitizer build; run those yourself.

## For maintainers: refreshing the baselines

`baselines/` hold what a clean upstream `master` produces. Regenerate after
upstream accepts a new finding on purpose:

```bash
./verify.sh --qet-dir <clean master checkout> --binary <its build> --make-baselines
```

Current baselines: upstream `master` at `9edfbf234` (2026-10-25), built with Qt 6.
All 24 example projects save identically twice and keep every element, wire
and terminal. Use a Qt 6 build for `--binary`.

## Licence

GPL-2.0-or-later, the same as QElectroTech: version 2 of the GNU General
Public License, or (at your option) any later version. Full text in `LICENSE`;
each source file carries an SPDX line.
