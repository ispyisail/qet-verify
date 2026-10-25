#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# verify.sh — check a QElectroTech change before you open a pull request.
#
#   ./verify.sh --qet-dir ~/qet/qelectrotech-source-mirror
#   ./verify.sh --qet-dir <dir> --binary <dir>/build/qelectrotech   # + save check
#
# Checks:
#   1. project and symbol files   (tools/qet-lint, needs no build)
#   2. interface text is English  (tools/srclint, needs no build)
#   3. saving a project twice loses nothing (tools/determinism, needs --binary)
#
# Each check is compared with a baseline recorded on a clean upstream master,
# so it fails only on a problem YOUR change adds.
#
# Maintainers: ./verify.sh --qet-dir <clean master checkout> --binary <its build> --make-baselines

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
QET_DIR="" BINARY="" MAKE_BASELINES=0

usage() { sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --qet-dir) QET_DIR="${2:-}"; shift ;;
    --binary)  BINARY="${2:-}"; shift ;;
    --make-baselines) MAKE_BASELINES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "verify.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[[ -d "$QET_DIR/sources" ]] || { echo "verify.sh: --qet-dir must be a QElectroTech checkout (no sources/ folder in '$QET_DIR')" >&2; exit 2; }

FAILED=0 SKIPPED=0
say()  { printf '\n== %s\n' "$1"; }
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED+1)); }
skip() { printf 'SKIP  %s\n' "$1"; SKIPPED=$((SKIPPED+1)); }

LINT_BASE="$HERE/baselines/qet-lint.json"
SRC_BASE="$HERE/baselines/srclint.json"
DET_BASE="$HERE/baselines/determinism.json"

# 1. project and symbol files
say "1/3 Project and symbol files"
LINT_PATHS=("$QET_DIR/examples" "$QET_DIR/elements")
if (( MAKE_BASELINES )); then
  python3 "$HERE/tools/qet-lint" --baseline "$LINT_BASE" --write-baseline "${LINT_PATHS[@]}" >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$LINT_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif python3 "$HERE/tools/qet-lint" --baseline "$LINT_BASE" "${LINT_PATHS[@]}" >"${TMPDIR:-/tmp}/qet-verify-lint.txt" 2>&1; then
  pass "no new problems in example projects or symbols"
else
  fail "new problem found. Details: ${TMPDIR:-/tmp}/qet-verify-lint.txt"
fi

# 2. interface text
say "2/3 Interface text is English"
if (( MAKE_BASELINES )); then
  python3 "$HERE/tools/srclint/srclint.py" --qet-dir "$QET_DIR" --baseline "$SRC_BASE" --write-baseline >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$SRC_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif python3 "$HERE/tools/srclint/srclint.py" --qet-dir "$QET_DIR" --baseline "$SRC_BASE" --gate >"${TMPDIR:-/tmp}/qet-verify-src.txt" 2>&1; then
  pass "no new French text in tr()"
else
  fail "new non-English interface text. Details: ${TMPDIR:-/tmp}/qet-verify-src.txt"
fi

# 3. saving loses nothing
say "3/3 Saving a project loses nothing"
if [[ -z "$BINARY" ]]; then
  skip "pass --binary <path to your built qelectrotech> to run this check"
elif [[ ! -x "$BINARY" ]]; then
  fail "binary not found or not executable: $BINARY"
elif (( MAKE_BASELINES )); then
  QT_QPA_PLATFORM=offscreen python3 "$HERE/tools/determinism/check.py" --binary "$BINARY" --corpus "$QET_DIR/examples" --baseline "$DET_BASE" --write-baseline >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$DET_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif QT_QPA_PLATFORM=offscreen timeout 1500 python3 "$HERE/tools/determinism/check.py" --binary "$BINARY" --corpus "$QET_DIR/examples" --baseline "$DET_BASE" >"${TMPDIR:-/tmp}/qet-verify-det.txt" 2>&1; then
  pass "saved projects keep every element, wire and terminal"
else
  fail "a save lost or changed data. Details: ${TMPDIR:-/tmp}/qet-verify-det.txt"
fi

say "Result"
if (( MAKE_BASELINES )); then
  (( FAILED == 0 )) && echo "Baselines written to $HERE/baselines" || echo "Some baselines failed."
  exit $(( FAILED > 0 ))
fi
printf '%d failed, %d skipped\n' "$FAILED" "$SKIPPED"
(( FAILED == 0 )) && echo "OK to open your pull request." || echo "Fix the FAIL lines above (or ask your assistant to) and run again."
exit $(( FAILED > 0 ))
