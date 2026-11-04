#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Runs verify.sh on Linux with Git Bash faked (uname says MINGW64, cygpath is a
# logging stub), to catch a regression in the Windows-only branches of verify.sh.
# It does NOT prove verify.sh works on Windows: only a run under real Git Bash does.
#
#   tests/windows-branches.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/qet-verify-wintest.XXXXXX")"
trap 'rm -rf "$T"' EXIT
REAL_PY="$(command -v python3)"
mkdir -p "$T/bin" "$T/qet/sources" "$T/qet/examples" "$T/videos"
FAILS=0
ok()  { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; FAILS=$((FAILS+1)); }

cat >"$T/bin/uname" <<'S'
#!/bin/sh
[ "$1" = "-s" ] && { echo MINGW64_NT-10.0; exit 0; }
exec /usr/bin/uname "$@"
S
# cygpath -m X: log X and answer X unchanged (real Git Bash accepts C:/ paths, a
# Linux filesystem does not, so the answer cannot be converted here)
cat >"$T/bin/cygpath" <<'S'
#!/bin/sh
echo "$2" >>"$CYGPATH_LOG"
printf '%s' "$2"
S
# the Microsoft Store `python3` stub: exists, does nothing useful
printf '#!/bin/sh\nexit 9\n' >"$T/bin/python3"
# `python` works, and says it was used
printf '#!/bin/sh\necho used >>"$PYTHON_LOG"\nexec %s "$@"\n' "$REAL_PY" >"$T/bin/python"
# a stand-in qelectrotech.exe: --version answers with $FAKE_EXE_RC
printf '#!/bin/sh\nexit "${FAKE_EXE_RC:-0}"\n' >"$T/qelectrotech.exe"
chmod +x "$T"/bin/* "$T/qelectrotech.exe"

run() { # extra verify.sh args; output in $T/out
  : >"$T/cygpath.log"; : >"$T/python.log"
  PATH="$T/bin:$PATH" CYGPATH_LOG="$T/cygpath.log" PYTHON_LOG="$T/python.log" \
    QET_VERIFY_NO_UPDATE=1 TMPDIR="$T" "$HERE/verify.sh" --qet-dir "$T/qet" "$@" >"$T/out" 2>&1
}

# The checks themselves are expected to fail here (empty example folders, a stub
# binary); only the Windows branches are tested.
run --binary "$T/qelectrotech.exe" --videos "$T/videos"
for p in "$HERE" "$T/qet" "$T/qelectrotech.exe" "$T/videos"; do
  grep -qxF "$p" "$T/cygpath.log" && ok "converted with cygpath: ${p#$T/}" || bad "never converted with cygpath: $p"
done
grep -q '^used' "$T/python.log" && ok "python3 stub rejected, fell back to python" || bad "did not fall back to python"
grep -q 'SKIP  the video recorder needs' "$T/out" && ok "check 6 skips on Windows" || bad "check 6 did not skip on Windows"

FAKE_EXE_RC=53 run --binary "$T/qelectrotech.exe"
grep -q 'FAIL.*Qt DLLs' "$T/out" && ok "a binary that will not start fails with the DLL hint" || bad "no DLL hint for a binary that will not start"

FAKE_EXE_RC=0 run --binary "$T/qelectrotech.exe"
grep -q 'binary not found or not executable' "$T/out" && bad "a binary that starts was rejected" || ok "a binary that starts is accepted"

if grep -q 'Python 3.8 or newer not found' "$T/out"; then bad "python probe failed"; else ok "python probe found an interpreter"; fi

(( FAILS == 0 )) && echo "all Windows-branch checks passed" || echo "$FAILS failed"
exit $(( FAILS > 0 ))
