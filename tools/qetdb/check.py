#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Is new saved data also kept by a .qetdb, not only by a .qet?

A project can be saved as .qet (XML) or as .qetdb (one SQLite file). Data
added to the .qet writer but not to the database is silently dropped by every
save as .qetdb (bridges were, until PR #1731). Two checks:

  roundtrip  a project saved as .qet, as .qetdb and read back, must equal the
             same project saved as .qet directly. Runs over the example
             projects, every project in tests/qttest/fixtures, and one made
             here with bridges in it. A new feature is covered once a fixture
             that uses it is in tests/qttest/fixtures. Needs a build.

  static     a change that adds lines to the XML writers outside
             sources/dataBase must also touch sources/dataBase, or add a
             fixture, or say in a commit message "qetdb: not needed" (with
             the reason). Needs no build.

Usage:
    check.py roundtrip --binary PATH --qet-dir DIR [--known FILE]
    check.py static --qet-dir DIR --base REV
Exit status 1 if either finds a problem.
"""
import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OPT_OUT = re.compile(r"qetdb:\s*not\s+(needed|stored)", re.I)
WRITER_CONTEXT = re.compile(r"Xml\b|Xml\(|toXml|ownValues|saveTo", re.I)


def run(binary, env, elements, *args, timeout=180):
    try:
        p = subprocess.run([binary, f"--common-elements-dir={elements}/", *args], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        return p.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def bridges_fixture(src: Path, dst: Path):
    """A copy of the project @src with a <bridges> section: the saved data a
    .qetdb lost. The first folio is given a uuid, which a bridge's drawn
    section names, when the file has none."""
    text = src.read_text(encoding="utf-8")
    if "</project>" not in text or "<bridges" in text:
        return False
    folio = "{5b0f5e1c-8a43-4c1e-9e57-3f0d0f0a7a01}"
    m = re.search(r"<diagram\b[^>]*>", text)
    if not m:
        return False
    if 'uuid="' not in m.group(0):
        text = text[:m.end() - 1] + f' uuid="{folio}"' + text[m.end() - 1:]
    else:
        folio = re.search(r'uuid="(\{[^"]+\})"', m.group(0)).group(1)
    section = (
        '<bridges><bridge uuid="{11111111-2222-4333-8444-555555555555}" color="#cc0000" '
        'line_width="2" max_connections="2" name="Bridge A" tension_protocol="24VAC"><terminals/>'
        '<parts><part uuid="{aaaaaaaa-2222-4333-8444-555555555555}" diagram="%s" '
        'x1="100" y1="100" x2="100" y2="200"/></parts></bridge></bridges>' % folio)
    dst.write_text(text.replace("</project>", section + "</project>"), encoding="utf-8")
    return True


def lines(path):
    """One tag per line, indentation and blank lines ignored: a .qetdb writes the
    embedded collection with other indentation, which is not lost data."""
    text = path.read_text(encoding="utf-8", errors="replace").replace(">", ">\n")
    return [l.strip() for l in text.splitlines() if l.strip()]


def one(job):
    binary, elements, work, path, index = job
    name = path.stem
    d = Path(work) / f"{index}-{name}"
    d.mkdir()
    # HOME and XDG_* isolate the settings on Linux; QET_SETTINGS_DIR does it on
    # every system (Windows would otherwise use the real registry).
    env = dict(os.environ, HOME=str(d / "h"),
               XDG_CONFIG_HOME=str(d / "h/c"), XDG_DATA_HOME=str(d / "h/d"),
               QET_SETTINGS_DIR=str(d / "settings"))
    # QT_QPA_PLATFORM inherited from the caller defaults to offscreen (true
    # headless); verify.sh sets it to "" when the build has no qoffscreen
    # plugin, meaning: don't force a platform, let Qt use its native one.
    qt_platform = os.environ.get("QT_QPA_PLATFORM", "offscreen")
    if qt_platform:
        env["QT_QPA_PLATFORM"] = qt_platform
    else:
        env.pop("QT_QPA_PLATFORM", None)
    direct, db, back = d / "direct.qet", d / "p.qetdb", d / "back.qet"
    if not run(binary, env, elements, "--resave", str(path), str(direct)):
        return name, "skip", "does not resave as .qet"
    if not (run(binary, env, elements, "--resave", str(path), str(db))
            and run(binary, env, elements, "--resave", str(db), str(back))):
        return name, "FAIL", "could not be saved as .qetdb and read back"
    a, b = (lines(f) for f in (direct, back))
    if a == b:
        return name, "same", ""
    diff = [l for l in difflib.unified_diff(a, b, "as .qet", "through .qetdb", n=0, lineterm="")
            if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    return name, "FAIL", "\n    ".join(diff[:8]) + (f"\n    ... {len(diff)} lines differ" if len(diff) > 8 else "")


def roundtrip(a):
    known = set()
    if a.known and Path(a.known).is_file():
        known = {l.split('#')[0].strip() for l in Path(a.known).read_text().splitlines()} - {''}
    qet = Path(a.qet_dir)
    work = tempfile.mkdtemp(prefix="qet-verify-qetdb.", dir=os.environ.get("TMPDIR") or None)
    try:
        files = sorted((qet / "examples").glob("*.qet"))
        fixtures = qet / "tests/qttest/fixtures"
        files += sorted(fixtures.glob("*.qet")) if fixtures.is_dir() else []
        made = Path(work) / "synthetic-with-bridges.qet"
        smallest = min((f for f in files if f.parent == qet / "examples"), key=lambda f: f.stat().st_size, default=None)
        if not (smallest and bridges_fixture(smallest, made)):
            print("FAIL  the example project with bridges could not be made")
            return 1
        files.append(made)
        if not files:
            print("no projects to check")
            return 1
        elements = str(qet / "elements")
        jobs = [(a.binary, elements, work, f, i) for i, f in enumerate(files)]
        with ThreadPoolExecutor(max_workers=int(os.environ.get("QET_VERIFY_JOBS", "4"))) as ex:
            results = list(ex.map(one, jobs))
        failed = [r for r in results if r[1] == "FAIL" and r[0] not in known]
        for name, status, detail in results:
            if status == "FAIL" and name in known:
                status = "known"
            if status != "same":
                print(f"{status}  {name}" + (f"\n    {detail}" if detail else ""))
        print(f"{len(results) - len(failed)} of {len(results)} projects keep everything through a .qetdb")
        if failed:
            print("\nSomething a .qet keeps is not kept by a .qetdb: add it to the database "
                  "(sources/dataBase), then run again.")
        return 1 if failed else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def git(qet, *args):
    return subprocess.run(["git", "-C", qet, *args], capture_output=True, text=True).stdout


def static(a):
    qet, base = a.qet_dir, a.base
    changed = git(qet, "diff", "--name-only", f"{base}..HEAD").split()
    in_db = any(f.startswith("sources/dataBase/") for f in changed)
    fixture = any(f.startswith("tests/qttest/fixtures/") for f in changed)
    opted = bool(OPT_OUT.search(git(qet, "log", "--format=%B", f"{base}..HEAD")))
    diff = git(qet, "diff", "-U0", f"{base}..HEAD", "--", "sources", ":(exclude)sources/dataBase")
    hits, path, ctx = [], "", ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:]
        elif line.startswith("@@"):
            ctx = line.split("@@")[-1].strip()
        elif line.startswith("+") and re.search(r"\b(createElement|setAttribute)\s*\(", line) \
                and WRITER_CONTEXT.search(ctx) and not re.match(r"\+\s*//", line):
            hits.append(f"{path}: {line[1:].strip()[:100]}   [{ctx[:60]}]")
    if not hits:
        print("no new saved data in the XML writers")
        return 0
    print(f"{len(hits)} line(s) added to XML writers outside sources/dataBase:")
    for h in hits[:10]:
        print("  " + h)
    if in_db or fixture or opted:
        why = "touches sources/dataBase" if in_db else "adds a fixture" if fixture else "says 'qetdb: not needed'"
        print(f"the change {why}")
        return 0
    print("\nNew data written to a .qet must also be kept by a .qetdb. Add it to sources/dataBase "
          "and a fixture in tests/qttest/fixtures, or, if it must not be stored there, put "
          "'qetdb: not needed (reason)' in a commit message.")
    return 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roundtrip"); r.add_argument("--binary", required=True); r.add_argument("--qet-dir", required=True); r.add_argument("--known")
    s = sub.add_parser("static"); s.add_argument("--qet-dir", required=True); s.add_argument("--base", required=True)
    a = p.parse_args()
    return roundtrip(a) if a.cmd == "roundtrip" else static(a)


if __name__ == "__main__":
    sys.exit(main())
