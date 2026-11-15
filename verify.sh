#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# verify.sh — check a QElectroTech change before you open a pull request.
#
#   ./verify.sh --qet-dir ~/qet/qelectrotech-source-mirror
#   ./verify.sh --qet-dir <dir> --binary <dir>/build/qelectrotech   # + save check
#   ./verify.sh ... --videos <stories dir>   # + do the how-to videos still work (optional)
#   ./verify.sh ... --claude-review [--review-level high]   # + Claude Code review (optional)
#
# Checks:
#   1. project and symbol files   (tools/qet-lint, needs no build)
#   2. interface text is English  (tools/srclint, needs no build)
#   3. saving a project twice loses nothing (tools/determinism, needs --binary)
#   4. data saved in a .qet is kept by a .qetdb too (tools/qetdb, needs --binary)
#   5. a change adding saved data also changes the database code (tools/qetdb)
#   6. each how-to video story still runs on this build (--videos, needs --binary;
#      uses qet-how-to-video cloned next to this repo, or --video-tool <dir>)
#   7. Claude Code's /code-review of the branch (--claude-review, needs the
#      `claude` command, logged in). Advisory: it can WARN, never FAIL.
#
# Before it runs, verify.sh updates itself from its own repository (set
# QET_VERIFY_NO_UPDATE=1 to skip), so everyone runs the latest checks.
#
# Checks 1 and 2 compare with the commit your branch started from on upstream
# master, fetched each run; check 3 with a baseline stored in baselines/.
# So each check fails only on a problem YOUR change adds.
#
# Maintainers: ./verify.sh --qet-dir <clean master checkout> --binary <its build> --make-baselines

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Windows runs this under Git Bash. Native Python and qelectrotech.exe do not
# understand Git Bash's /c/... and /tmp/... paths, so every path handed to them
# is converted to C:/... form; the interpreter is `python`, not `python3`.
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;; *) WINDOWS=0 ;; esac
native() { if (( WINDOWS )); then cygpath -m "$1"; else printf '%s' "$1"; fi; }
PY=""
for cand in python3 python "py -3"; do
  # the Microsoft Store stub for `python` exists but only prints a hint, so run it
  if $cand -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then PY="$cand"; break; fi
done
[[ -n "$PY" ]] || { echo "verify.sh: Python 3.8 or newer not found (tried python3, python, py -3)" >&2; exit 2; }
HERE="$(native "$HERE")"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"

# Update this checker first: a pull request is judged by the checks of the day,
# not the ones that were cloned. Fast-forward only, so local edits are never
# overwritten; then run again as the new version. The receipt says which.
UPDATE_STATE="update not checked"
if [[ -z "${QET_VERIFY_NO_UPDATE:-}" ]] && git -C "$HERE" rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "${QET_VERIFY_UPDATED:-}" ]]; then
    UPDATE_STATE="updated just now"
  elif timeout 20 git -C "$HERE" fetch --quiet origin 2>/dev/null; then
    UPSTREAM_REF="$(git -C "$HERE" rev-parse --verify --quiet '@{u}' || git -C "$HERE" rev-parse --verify --quiet origin/HEAD || true)"
    BEHIND="$(git -C "$HERE" rev-list --count HEAD.."${UPSTREAM_REF:-HEAD}" 2>/dev/null || echo 0)"
    if [[ "$BEHIND" == 0 ]]; then
      UPDATE_STATE="up to date"
    elif git -C "$HERE" merge --ff-only --quiet "$UPSTREAM_REF" 2>/dev/null; then
      echo "qet-verify updated by $BEHIND commit(s); running the new version"
      QET_VERIFY_UPDATED=1 exec "$0" "$@"
    else
      UPDATE_STATE="$BEHIND behind, could not update (local changes?)"
      echo "WARNING: qet-verify is $BEHIND commit(s) behind and could not update itself; run: git -C $HERE pull" >&2
    fi
  else
    UPDATE_STATE="update not checked (offline)"
  fi
fi
QET_DIR="" BINARY="" MAKE_BASELINES=0 VIDEOS="" VIDEO_TOOL="" CLAUDE_REVIEW=0 REVIEW_LEVEL="medium"

usage() { sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --qet-dir) QET_DIR="${2:-}"; shift ;;
    --binary)  BINARY="${2:-}"; shift ;;
    --videos)  VIDEOS="${2:-}"; shift ;;
    --video-tool) VIDEO_TOOL="${2:-}"; shift ;;
    --claude-review) CLAUDE_REVIEW=1 ;;
    --review-level) REVIEW_LEVEL="${2:-}"; CLAUDE_REVIEW=1; shift ;;
    --make-baselines) MAKE_BASELINES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "verify.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
if (( WINDOWS )); then
  [[ -n "$QET_DIR" && -d "$QET_DIR" ]] && QET_DIR="$(native "$QET_DIR")"
  [[ -n "$BINARY" && -e "$BINARY" ]] && BINARY="$(native "$BINARY")"
  [[ -n "$VIDEOS" && -d "$VIDEOS" ]] && VIDEOS="$(native "$VIDEOS")"
fi
[[ -d "$QET_DIR/sources" ]] || { echo "verify.sh: --qet-dir must be a QElectroTech checkout (no sources/ folder in '$QET_DIR')" >&2; exit 2; }
# max and ultra start many reviewers (ultra runs in the cloud and can only be
# started by a person), so a script offers the levels up to xhigh.
case "$REVIEW_LEVEL" in low|medium|high|xhigh) ;; *)
  echo "verify.sh: --review-level must be low, medium, high or xhigh (got '$REVIEW_LEVEL')" >&2; exit 2 ;; esac

FAILED=0 SKIPPED=0 WARNED=0 LAST=SKIP R1=SKIP R2=SKIP R3=SKIP R4=SKIP R5=SKIP R6=SKIP R7=SKIP BRANCH_POINT=""
say()  { printf '\n== %s\n' "$1"; }
pass() { LAST=PASS; printf 'PASS  %s\n' "$1"; }
fail() { LAST=FAIL; printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED+1)); }
skip() { LAST=SKIP; printf 'SKIP  %s\n' "$1"; SKIPPED=$((SKIPPED+1)); }
warn() { LAST=WARN; printf 'WARN  %s\n' "$1"; WARNED=$((WARNED+1)); }

# A binary that starts: exists, and answers --version. On Windows a missing Qt
# DLL makes the launch fail at once, so this catches it with a clear message
# instead of every project failing to resave.
binary_ok() {
  [[ -f "$BINARY" ]] || return 1
  (( WINDOWS )) || [[ -x "$BINARY" ]] || return 1
  (( WINDOWS )) || return 0
  QT_QPA_PLATFORM="$QT_PLATFORM" timeout 60 "$BINARY" --version >/dev/null 2>&1
}

# Headless Qt platform for checks 3/4. Most builds ship qoffscreen (true
# headless, no window). Some Windows build artifacts don't package it since
# the app never requests it on a normal run; QT_PLATFORM="" then means "no
# platform forced", so Qt falls back to its native platform (qwindows on
# Windows) instead of hanging waiting for a plugin that isn't there. A
# window may flash briefly in that fallback case.
QT_PLATFORM="offscreen"
if (( WINDOWS )) && [[ -n "$BINARY" ]] && [[ ! -f "$(dirname "$BINARY")/platforms/qoffscreen.dll" ]]; then
  QT_PLATFORM=""
fi

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
WORK="$(native "$(mktemp -d "${TMPDIR:-/tmp}/qet-verify.XXXXXX")")"
REVIEW_TREE=""
cleanup() {
  # check 7's worktree is registered in the QET checkout; unregister it too
  [[ -n "$REVIEW_TREE" ]] && git -C "$QET_DIR" worktree remove --force "$REVIEW_TREE" >/dev/null 2>&1
  rm -rf "$WORK"
  [[ -n "$REVIEW_TREE" ]] && git -C "$QET_DIR" worktree prune >/dev/null 2>&1
  return 0
}
trap cleanup EXIT
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
  $PY "$HERE/tools/qet-lint" --baseline "$WORK/qet-lint.json" --write-baseline \
    "${base_paths[@]}" >/dev/null 2>&1 || return 1
  $PY "$HERE/tools/srclint/srclint.py" --qet-dir "$WORK/base" \
    --baseline "$WORK/srclint.json" --write-baseline >/dev/null 2>&1 || return 1
  LINT_BASE="$WORK/qet-lint.json" SRC_BASE="$WORK/srclint.json"
  BRANCH_POINT="$base"
  BASE_DESC="upstream master $up, branch point $(git -C "$QET_DIR" rev-parse --short=9 "$base") (save check: $BASE_DESC)"
}
if (( ! MAKE_BASELINES )) && ! live_baselines; then
  BASE_DESC="$BASE_DESC (stored; upstream master unreachable, may report master's own findings)"
fi

# 1. project and symbol files
say "1/7 Project and symbol files"
if (( MAKE_BASELINES )); then
  $PY "$HERE/tools/qet-lint" --baseline "$LINT_BASE" --write-baseline "${LINT_PATHS[@]}" >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$LINT_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif $PY "$HERE/tools/qet-lint" --baseline "$LINT_BASE" "${LINT_PATHS[@]}" >"${TMPDIR:-/tmp}/qet-verify-lint.txt" 2>&1; then
  pass "no new problems in example projects or symbols"
else
  fail "new problem found. Details: ${TMPDIR:-/tmp}/qet-verify-lint.txt"
fi

R1=$LAST

# 2. interface text
say "2/7 Interface text is English"
if (( MAKE_BASELINES )); then
  $PY "$HERE/tools/srclint/srclint.py" --qet-dir "$QET_DIR" --baseline "$SRC_BASE" --write-baseline >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$SRC_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif $PY "$HERE/tools/srclint/srclint.py" --qet-dir "$QET_DIR" --baseline "$SRC_BASE" --gate >"${TMPDIR:-/tmp}/qet-verify-src.txt" 2>&1; then
  pass "no new French text in tr()"
else
  fail "new non-English interface text. Details: ${TMPDIR:-/tmp}/qet-verify-src.txt"
fi

R2=$LAST

# 3. saving loses nothing
say "3/7 Saving a project loses nothing"
if [[ -z "$BINARY" ]]; then
  skip "pass --binary <path to your built qelectrotech> to run this check"
elif ! binary_ok; then
  fail "binary not found or not executable (on Windows: no Qt DLLs found next to it or on PATH?): $BINARY"
elif (( MAKE_BASELINES )); then
  QT_QPA_PLATFORM="$QT_PLATFORM" $PY "$HERE/tools/determinism/check.py" --binary "$BINARY" --corpus "$QET_DIR/examples" --baseline "$DET_BASE" --write-baseline >/dev/null && pass "baseline written" || fail "could not write baseline"
elif [[ ! -f "$DET_BASE" ]]; then
  skip "no baseline yet (maintainer: run with --make-baselines on a clean master)"
elif QT_QPA_PLATFORM="$QT_PLATFORM" timeout 1500 $PY "$HERE/tools/determinism/check.py" --binary "$BINARY" --corpus "$QET_DIR/examples" --baseline "$DET_BASE" >"${TMPDIR:-/tmp}/qet-verify-det.txt" 2>&1; then
  pass "saved projects keep every element, wire and terminal"
else
  fail "a save lost or changed data. Details: ${TMPDIR:-/tmp}/qet-verify-det.txt"
fi

R3=$LAST

# 4. what a .qet keeps, a .qetdb keeps
say "4/7 A .qetdb keeps what a .qet keeps"
if [[ -z "$BINARY" ]]; then
  skip "pass --binary <path to your built qelectrotech> to run this check"
elif ! binary_ok; then
  fail "binary not found or not executable (on Windows: no Qt DLLs found next to it or on PATH?): $BINARY"
elif (( MAKE_BASELINES )); then
  skip "nothing to write: the known differences are listed in baselines/qetdb-known.txt"
elif QT_QPA_PLATFORM="$QT_PLATFORM" timeout 1500 $PY "$HERE/tools/qetdb/check.py" roundtrip --binary "$BINARY" --qet-dir "$QET_DIR" --known "$HERE/baselines/qetdb-known.txt" >"${TMPDIR:-/tmp}/qet-verify-qetdb.txt" 2>&1; then
  pass "every example and fixture project is the same through a .qetdb"
else
  fail "a .qetdb lost data a .qet keeps. Details: ${TMPDIR:-/tmp}/qet-verify-qetdb.txt"
fi

R4=$LAST

# 5. new saved data reaches the database code
say "5/7 New saved data is also stored in the .qetdb"
if (( MAKE_BASELINES )); then
  skip "nothing to write"
elif [[ -z "$BRANCH_POINT" ]]; then
  skip "needs the branch point on upstream master (no network, or not a git checkout)"
elif $PY "$HERE/tools/qetdb/check.py" static --qet-dir "$QET_DIR" --base "$BRANCH_POINT" >"${TMPDIR:-/tmp}/qet-verify-qetdb-static.txt" 2>&1; then
  pass "$(head -1 "${TMPDIR:-/tmp}/qet-verify-qetdb-static.txt")"
else
  fail "new data written to a .qet but not stored in the .qetdb. Details: ${TMPDIR:-/tmp}/qet-verify-qetdb-static.txt"
fi

R5=$LAST

# 6. the how-to videos still match the interface (optional)
say "6/7 How-to video stories still run"
if [[ -z "$VIDEOS" ]]; then
  skip "pass --videos <folder of story .yaml files> to run this check"
elif (( MAKE_BASELINES )); then
  skip "nothing to write"
elif (( WINDOWS )); then
  skip "the video recorder needs Xvfb, openbox and xdotool, which only Linux has"
elif [[ -z "$BINARY" ]] || ! binary_ok; then
  skip "needs --binary"
else
  # https://github.com/ispyisail/qet-how-to-video, cloned next to this repo
  VT="${VIDEO_TOOL:-$HERE/../qet-how-to-video}"
  [[ -z "$VIDEO_TOOL" && ! -f "$VT/story.py" && -f "$HERE/../qelectrotech-docker/tools/how-to-video/story.py" ]] \
    && VT="$HERE/../qelectrotech-docker/tools/how-to-video"
  if [[ ! -f "$VT/story.py" ]]; then
    fail "how-to-video tool not found at $VT: git clone https://github.com/ispyisail/qet-how-to-video next to qet-verify, or use --video-tool <dir>"
  else
    V_OK=0 V_BAD=0 V_LOG="${TMPDIR:-/tmp}/qet-verify-videos.txt"; : >"$V_LOG"
    shopt -s nullglob
    for story in "$VIDEOS"/*.yaml; do
      if timeout 600 $PY "$VT/story.py" "$story" --binary "$BINARY" --check-only --out "$WORK/videos" >>"$V_LOG" 2>&1; then
        V_OK=$((V_OK+1))
      else
        V_BAD=$((V_BAD+1)); echo "  out of date: $(basename "$story")"
      fi
    done
    if (( V_OK + V_BAD == 0 )); then skip "no .yaml stories in $VIDEOS"
    elif (( V_BAD == 0 )); then pass "$V_OK story(ies) still do what their video shows"
    else fail "$V_BAD video(s) no longer match this build; re-record them. Details: $V_LOG"; fi
  fi
fi

R6=$LAST

# 7. Claude Code's /code-review of the branch (optional, advisory)
# A review by a model is not repeatable the way checks 1-6 are: two runs on the
# same commit can find different things. So it never FAILs; findings WARN and
# the exit status ignores them. It reviews the committed branch, not
# uncommitted edits: a throwaway worktree of HEAD is soft-reset to the branch
# point, which makes the whole branch the "current diff" /code-review reviews
# by default. The worktree is read-only to the reviewer (no Edit/Write tools).
say "7/7 Claude Code review (advisory)"
REVIEW_LOG="${TMPDIR:-/tmp}/qet-verify-review.txt"
if (( ! CLAUDE_REVIEW )); then
  skip "pass --claude-review to run /code-review on your branch (needs Claude Code)"
elif (( MAKE_BASELINES )); then
  skip "nothing to write"
elif [[ -z "$BRANCH_POINT" ]]; then
  skip "needs the branch point on upstream master (no network, or not a git checkout)"
elif ! command -v claude >/dev/null 2>&1; then
  skip "the claude command (Claude Code) is not on PATH"
elif [[ -z "$(git -C "$QET_DIR" diff --name-only "$BRANCH_POINT" HEAD 2>/dev/null)" ]]; then
  skip "no committed change since the branch point to review"
else
  REVIEW_TREE="$WORK/review"
  if ! git -C "$QET_DIR" worktree add --detach --quiet "$REVIEW_TREE" HEAD >/dev/null 2>&1 \
     || ! git -C "$REVIEW_TREE" reset --quiet --soft "$BRANCH_POINT"; then
    skip "could not make a worktree of HEAD in $QET_DIR"
  else
    echo "reviewing $(git -C "$REVIEW_TREE" diff --cached --shortstat) at level $REVIEW_LEVEL (takes minutes)..."
    ( cd "$REVIEW_TREE" && timeout 1800 claude -p "/code-review $REVIEW_LEVEL" \
        --allowedTools "Read Grep Glob Agent Bash(git diff:*) Bash(git log:*) Bash(git show:*) Bash(git status:*) Bash(git rev-parse:*) Bash(git merge-base:*) Bash(git blame:*)" \
        --disallowedTools "Edit Write NotebookEdit" --output-format text ) >"$REVIEW_LOG" 2>&1
    R_EXIT=$?
    R_FIRST="$(grep -m1 -v '^[[:space:]]*$' "$REVIEW_LOG" | tr -d '[:space:]')"
    if (( R_EXIT == 124 )); then
      skip "the review took over 30 minutes and was stopped. Partial output: $REVIEW_LOG"
    elif (( R_EXIT != 0 )) || [[ -z "$R_FIRST" ]] || grep -qiE 'unknown (skill|command)|not logged in|please run /login|invalid api key' "$REVIEW_LOG"; then
      skip "claude did not run the review (logged in? a version with /code-review?). Output: $REVIEW_LOG"
    else
      # No findings prints "(none)" (or an empty JSON list); findings come as a
      # JSON list of {file, line, summary, failure_scenario}.
      R_COUNT="$(grep -c '"summary"' "$REVIEW_LOG")"
      if [[ "$R_FIRST" == "(none)" ]] || { (( R_COUNT == 0 )) && grep -qE '^[[:space:]]*\[[[:space:]]*\][[:space:]]*$' "$REVIEW_LOG"; }; then
        pass "no findings at level $REVIEW_LEVEL. Notes: $REVIEW_LOG"
      elif (( R_COUNT > 0 )); then
        warn "$R_COUNT finding(s) to read (not a failure). Details: $REVIEW_LOG"
      else
        warn "the review has notes to read (not a failure). Details: $REVIEW_LOG"
      fi
    fi
  fi
fi

R7=$LAST
[[ "$R7" != SKIP ]] && R7="$R7 ($REVIEW_LEVEL)"

say "Result"
if (( MAKE_BASELINES )); then
  (( FAILED == 0 )) && git -C "$QET_DIR" rev-parse --git-dir >/dev/null 2>&1 && printf "upstream master %s\n" "$(git -C "$QET_DIR" rev-parse --short=9 HEAD)" > "$HERE/baselines/BASELINE_REF"
  (( FAILED == 0 )) && echo "Baselines written to $HERE/baselines" || echo "Some baselines failed."
  exit $(( FAILED > 0 ))
fi
printf '%d failed, %d skipped%s\n' "$FAILED" "$SKIPPED" "$( (( WARNED )) && printf ', %d warning(s) to read' "$WARNED")"

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
echo "checks:    project files $R1 | english text $R2 | save check $R3 | qetdb round trip $R4 | qetdb new data $R5 | how-to videos $R6 | code review $R7"
echo "baseline:  $BASE_DESC"
echo "verifier:  qet-verify $VER ($UPDATE_STATE)"
echo '```'
(( FAILED == 0 && WARNED )) && echo "Read the code review ($REVIEW_LOG) and fix what is real; a WARN does not block the pull request."
(( FAILED == 0 )) && echo "OK to open your pull request." || echo "Fix the FAIL lines above (or ask your assistant to) and run again."
exit $(( FAILED > 0 ))
