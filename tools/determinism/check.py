#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Save-determinism corpus for QElectroTech.

Phases 1a (canonical serialization) and 3 (project-as-directory) of the
multi-user roadmap both rewrite how projects serialize, and neither change is
reviewable by eye. This checks two properties mechanically, using the headless
`--resave` CLI so no display or GUI automation is involved:

  I1  save is idempotent  -- resave(resave(x)) is byte-identical to resave(x)
  I3  meaning is preserved -- element / conductor / terminal counts and the full
      uuid set are unchanged across a resave

I1 is the property Phase 1a exists to establish. It does NOT hold on master
today (Diagram::toXml iterates QGraphicsScene::items(), which returns stacking
order, not a content-derived order), so a first run is expected to report
failures -- that list is the Phase 1a to-do, measured rather than guessed.

I3 is the one that must never regress. An I3 failure means a save lost or
invented data, which is a corruption bug regardless of any roadmap.

A timeout is reported as ERROR and is always worth investigating: it means the
headless path blocked rather than ran slowly. Known instance at time of writing
-- `--resave examples/schema_indus.qet` hangs indefinitely while consuming
essentially no CPU, though the GUI opens the same project without complaint, so
the file is fine and the CLI path is not.

Usage:
    check.py --binary PATH --corpus DIR [--write-baseline]

Without --write-baseline the results are compared against baseline.json and the
exit code is non-zero if anything got worse. That makes this a gate, not just a
report.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Counted per project and required to survive a resave unchanged.
COUNTED = {
    "elements":   re.compile(r"<element\s"),
    "conductors": re.compile(r"<conductor\s"),
    "terminals":  re.compile(r"<terminal\s"),
    "texts":      re.compile(r"<input\s"),
    "shapes":     re.compile(r"<shape\s"),
    "images":     re.compile(r"<image\s"),
}
UUID_RE = re.compile(r'uuid="\{([0-9a-fA-F-]+)\}"')


def semantics(path):
    """Content fingerprint that must be invariant across a save."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    fp = {name: len(rx.findall(text)) for name, rx in COUNTED.items()}
    fp["uuids"] = sorted(set(UUID_RE.findall(text)))
    return fp


def resave(binary, src, dst, timeout):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        proc = subprocess.run([binary, "--resave", src, dst],
                              env=env, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return False, f"exit {proc.returncode}: {' / '.join(tail)}"
    if not os.path.exists(dst):
        return False, "produced no output file"
    return True, ""


def check_project(binary, src, tmpdir, timeout):
    """Return a result dict for one project."""
    name = os.path.basename(src)
    p1 = os.path.join(tmpdir, "pass1.qet")
    p2 = os.path.join(tmpdir, "pass2.qet")
    res = {"name": name, "i1": None, "i3": None, "error": None}

    ok, err = resave(binary, src, p1, timeout)
    if not ok:
        res["error"] = f"first resave failed: {err}"
        return res
    ok, err = resave(binary, p1, p2, timeout)
    if not ok:
        res["error"] = f"second resave failed: {err}"
        return res

    with open(p1, "rb") as a, open(p2, "rb") as b:
        res["i1"] = a.read() == b.read()

    s1, s2 = semantics(p1), semantics(p2)
    res["i3"] = s1 == s2
    if not res["i3"]:
        deltas = []
        for key in COUNTED:
            if s1[key] != s2[key]:
                deltas.append(f"{key} {s1[key]}->{s2[key]}")
        lost = set(s1["uuids"]) - set(s2["uuids"])
        gained = set(s2["uuids"]) - set(s1["uuids"])
        if lost:
            deltas.append(f"{len(lost)} uuid(s) lost")
        if gained:
            deltas.append(f"{len(gained)} uuid(s) invented")
        res["error"] = "; ".join(deltas)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", default="/usr/local/bin/qelectrotech")
    ap.add_argument("--corpus", default="/src/examples")
    ap.add_argument("--baseline", default=os.path.join(os.path.dirname(__file__), "baseline.json"))
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    if not os.path.exists(args.binary):
        sys.exit(f"binary not found: {args.binary}")
    projects = sorted(
        os.path.join(args.corpus, f)
        for f in os.listdir(args.corpus) if f.endswith(".qet")
    )
    if not projects:
        sys.exit(f"no .qet files found in {args.corpus}")

    print(f"binary : {args.binary}")
    print(f"corpus : {args.corpus} ({len(projects)} projects)\n")

    results = []
    tmproot = tempfile.mkdtemp(prefix="qet-determinism-")
    try:
        for src in projects:
            sub = tempfile.mkdtemp(dir=tmproot)
            r = check_project(args.binary, src, sub, args.timeout)
            results.append(r)
            if r["error"] and r["i3"] is None:
                mark = "ERROR"
            elif r["i3"] is False:
                mark = "I3 FAIL"
            elif r["i1"]:
                mark = "ok"
            else:
                mark = "I1 fail"
            print(f"  {mark:<8} {r['name']}" + (f"   ({r['error']})" if r["error"] else ""))
    finally:
        shutil.rmtree(tmproot, ignore_errors=True)

    i1_pass = sum(1 for r in results if r["i1"])
    i3_fail = [r for r in results if r["i3"] is False]
    errors = [r for r in results if r["i3"] is None]

    print(f"\n  I1 (idempotent save) : {i1_pass}/{len(results)} pass")
    print(f"  I3 (meaning preserved): {len(results) - len(i3_fail) - len(errors)}/{len(results)} pass")
    if errors:
        print(f"  could not be checked  : {len(errors)}")

    current = {r["name"]: {"i1": r["i1"], "i3": r["i3"]} for r in results}

    if args.write_baseline:
        with open(args.baseline, "w") as fh:
            json.dump(current, fh, indent=2, sort_keys=True)
        print(f"\nbaseline written to {args.baseline}")
        print("I1 failures above are the Phase 1a to-do list.")
        return 1 if i3_fail or errors else 0

    if not os.path.exists(args.baseline):
        print(f"\nno baseline at {args.baseline} -- run with --write-baseline first")
        return 1 if i3_fail or errors else 0

    with open(args.baseline) as fh:
        base = json.load(fh)

    regressions = []
    for name, cur in current.items():
        was = base.get(name)
        if was is None:
            continue  # new corpus entry, nothing to compare
        if was["i1"] and not cur["i1"]:
            regressions.append(f"{name}: I1 regressed (save is no longer idempotent)")
        if was["i3"] and not cur["i3"]:
            regressions.append(f"{name}: I3 regressed (a save changed the project's meaning)")

    improvements = [n for n, c in current.items()
                    if c["i1"] and base.get(n) and not base[n]["i1"]]

    print()
    if improvements:
        print(f"  {len(improvements)} project(s) newly satisfy I1:")
        for n in improvements:
            print(f"    + {n}")
    if regressions:
        print("  REGRESSIONS:")
        for r in regressions:
            print(f"    - {r}")
        return 1
    if i3_fail:
        print("  I3 failing (data changed by a save) -- always a hard failure:")
        for r in i3_fail:
            print(f"    - {r['name']}: {r['error']}")
        return 1
    print("  no regressions against baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
