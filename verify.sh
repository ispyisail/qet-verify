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
# Checks 1 and 2 compare with the commit your branch started from on upstream
# master, fetched each run; check 3 with a baseline stored in baselines/.
# So each check fails only on a problem YOUR change adds.
#
# Maintainers: ./verify.sh --qet-dir <clean master checkout> --binary <its build> --make-baselines

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
QET_DIR="" BINARY="" MAKE_BASELINES=0

usage() { sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; }
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

FAILED=0 SKIPPED=0 LAST=SKIP R1=SKIP R2=SKIP R3=SKIP
say()  { printf '\n== %s\n' "$1"; }
pass() { LAST=PASS; printf 'PASS  %s\n' "$1"; }
fail() { LAST=FAIL; printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED+1)); }
skip() { LAST=SKIP; printf 'SKIP  %s\n' "$1"; SKIPPED=$((SKIPPED+1)); }

LINT_BASE="$HERE/baselines/qet-lint.json"
SRC_BASE="$HERE/baselines/srclint.json"
DET_BASE="$HERE/baselines/determinism.json"
BASE_DESC="$(cat "$HERE/baselines/BASELINE_REF" 2>/dev/null || echo unknown)"

# Checks 1 and 2 need no build, so their baseline is made fresh on each run:
# the same checks on the commit where your branch left upstream master. A
# stored baseline goes stale the day master changes, and then every pull
# request shows master's own findings as FAILs. Without a network the stored
# baselines are used instead, and the receipt says so.
LINT_PATHS=("$QET_DIR/examples" "$QET_DIR/elements")
UPSTREAM_URL="https://github.com/qelectrotech/qelectrotech-source-mirror.git"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/qet-verify.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
live_baselines() {
  local up base pin_base pin_head
  git -C "$QET_DIR" rev-parse --git-dir >/dev/null 2>&1 || return 1
  timeout 120 git -C "$QET_DIR" fetch --quiet --no-tags "$UPSTREAM_URL" \
    "+refs/heads/master:refs/qet-verify/upstream-master" 2>/dev/null || return 1
  up="$(git -C "$QET_DIR" rev-parse --short=9 refs/qet-verify/upstream-master)" || return 1
  base="$(git -C "$QET_DIR" merge-base HEAD refs/qet-verify/upstream-master)" || return 1
  mkdir -p "$WORK/base/elements"
  git -C "$QET_DIR" archive "$base" sources examples | tar -x -C "$WORK/base" || return 1
  # elements/ is a submodule: a branch changes the symbols only by moving its
  # pin. Same pin, same symbols, so leave them out on both sides (half the
  # run time). A moved pin is linted against the old pin's symbols, which the
  # elements checkout must have.
  pin_base="$(git -C "$QET_DIR" rev-parse "$base:elements" 2>/dev/null)"
  pin_head="$(git -C "$QET_DIR" rev-parse "HEAD:elements" 2>/dev/null)"
  local base_paths=("$WORK/base/examples")
  if [[ "$pin_base" == "$pin_head" ]]; then
    LINT_PATHS=("$QET_DIR/examples")
  else
    git -C "$QET_DIR/elements" archive "$pin_base" 2>/dev/null | tar -x -C "$WORK/base/elements" || return 1
    base_paths+=("$WORK/base/elements")
  fi
  python3 "$HERE/tools/qet-lint" --baseline "$WORK/qet-lint.json" --write-baseline \
    "${base_paths[@]}" >/dev/null 2>&1 || return 1
  python3 "$HERE/tools/srclint/srclint.py" --qet-dir "$WORK/base" \
    --baseline "$WORK/srclint.json" --write-baseline >/dev/null 2>&1 || return 1
  LINT_BASE="$WORK/qet-lint.json" SRC_BASE="$WORK/srclint.json"
  BASE_DESC="upstream master $up, branch point $(git -C "$QET_DIR" rev-parse --short=9 "$base") (save check: $BASE_DESC)"
}
if (( ! MAKE_BASELINES )) && ! live_baselines; then
  BASE_DESC="$BASE_DESC (stored; upstream master unreachable, may report master's own findings)"
fi

# 1. project and symbol files
say "1/3 Project and symbol files"
if (( MAKE_BASELINES )); then
  python3 "$HERE/tools/qet-lint" --baseline "$LINT_BASE" --write-baseline "${LINT_PATHS[@]}" >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$LINT_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif python3 "$HERE/tools/qet-lint" --baseline "$LINT_BASE" "${LINT_PATHS[@]}" >"${TMPDIR:-/tmp}/qet-verify-lint.txt" 2>&1; then
  pass "no new problems in example projects or symbols"
else
  fail "new problem found. Details: ${TMPDIR:-/tmp}/qet-verify-lint.txt"
fi

R1=$LAST

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

R2=$LAST

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

R3=$LAST

say "Result"
if (( MAKE_BASELINES )); then
  (( FAILED == 0 )) && git -C "$QET_DIR" rev-parse --git-dir >/dev/null 2>&1 && printf "upstream master %s\n" "$(git -C "$QET_DIR" rev-parse --short=9 HEAD)" > "$HERE/baselines/BASELINE_REF"
  (( FAILED == 0 )) && echo "Baselines written to $HERE/baselines" || echo "Some baselines failed."
  exit $(( FAILED > 0 ))
fi
printf '%d failed, %d skipped\n' "$FAILED" "$SKIPPED"

# Receipt: paste this block into the pull request description. It names the
# commit the checks ran on, so a stale receipt (edited since) is easy to spot.
# A pasted receipt shows the checks were run; it does not prove it. To be sure,
# run verify.sh again.
if git -C "$QET_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  CHANGE="$(git -C "$QET_DIR" rev-parse --short=9 HEAD)"
  BRANCH="$(git -C "$QET_DIR" branch --show-current)"
  if [[ -z "$(git -C "$QET_DIR" status --porcelain --untracked-files=no)" ]]; then TREE="tree clean"; else TREE="UNCOMMITTED CHANGES, commit first"; fi
else
  CHANGE="unknown (not a git checkout)"; BRANCH=""; TREE=""
fi
VER="$(git -C "$HERE" rev-parse --short=7 HEAD 2>/dev/null || echo unknown)"
git -C "$HERE" diff --quiet HEAD 2>/dev/null || VER="$VER+modified"
echo
echo "Receipt (paste into the pull request description):"
echo '```'
echo "qet-verify receipt"
echo "change:    $CHANGE${BRANCH:+ on $BRANCH}${TREE:+ ($TREE)}"
echo "checks:    project files $R1 | english text $R2 | save check $R3"
echo "baseline:  $BASE_DESC"
echo "verifier:  qet-verify $VER"
echo '```'
(( FAILED == 0 )) && echo "OK to open your pull request." || echo "Fix the FAIL lines above (or ask your assistant to) and run again."
exit $(( FAILED > 0 ))
