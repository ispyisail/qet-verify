#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""qet-lint -- dependency-free static checker for QElectroTech .qet/.elmt files.

    python3 tools/qet-lint/__main__.py [--format text|json]
        [--baseline FILE] [--write-baseline] [--include-info] PATHS...

PATHS may be files or directories (directories are walked for ``*.qet`` and
``*.elmt``). No build, no launch, no GUI -- this is pure file analysis.

Exit code: 0 when there is nothing new to act on. Without a baseline that
means zero violations at the default severities; with a baseline it means no
(file, rule) got worse than the recorded count. Any regression exits 1, so the
tool is a gate on new problems rather than a wall of pre-existing noise.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# The package lives at tools/qet-lint (a hyphenated name, so it cannot be
# `import`ed); run as `python3 tools/qet-lint/__main__.py`. Make both this
# directory (for the sibling modules) and the repo root (for `simulator`)
# importable before pulling anything in.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
for _p in (_HERE, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import model            # noqa: E402
import report           # noqa: E402
import rules_element    # noqa: E402
import rules_project    # noqa: E402

PROJECT_RULES = (
    rules_project.p001_nan_or_inf,
    rules_project.p002_control_char,
    rules_project.p003_duplicate_element_uuid,
    rules_project.p004_unregistered_info_key,
    rules_project.p005_potential_disagrees,
)
ELEMENT_RULES = (
    rules_element.e001_not_parseable,
    rules_element.e002_control_char,
    rules_element.e003_terminal_name_ordering,
    rules_element.e004_duplicate_terminal_name,
)

DEFAULT_BASELINE = "qet-lint.baseline.json"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="qet-lint",
        description="Static checker for QElectroTech .qet / .elmt files.",
    )
    ap.add_argument("paths", nargs="+", help=".qet/.elmt files or directories to walk")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE,
                    help="baseline file (default %(default)s)")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the current violations as the baseline and exit")
    ap.add_argument("--include-info", action="store_true",
                    help="also report info-severity violations (off by default)")
    return ap


def _display_path(path: Path, root: Path | None = None) -> str:
    """Normalised path for reports and baselines.

    cwd-relative when the file is under the cwd. Otherwise relative to the
    directory argument it was found under, prefixed with that directory's
    name (<qet-checkout>/examples/a.qet -> examples/a.qet), so the same
    corpus checked out in two places gives the same baseline keys. An
    absolute path here once made a baseline that only matched one checkout.
    """
    try:
        rel = os.path.relpath(path, os.getcwd())
    except ValueError:  # different drive on Windows; not an issue on Linux
        rel = str(path)
    if not rel.startswith(".."):
        return rel.replace(os.sep, "/")
    if root is not None:
        rel = os.path.relpath(path.absolute(), root.parent)
        return rel.replace(os.sep, "/")
    return path.name


def iter_files(paths: list[str]):
    """Yield (path, root) for every .qet/.elmt under the given files/dirs,
    deduped. root is the directory argument a file was found under, or None
    for a file given directly."""
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            root = p.absolute()
            for ext in ("*.qet", "*.elmt"):
                for f in p.rglob(ext):
                    r = f.resolve()
                    if r not in seen:
                        seen.add(r)
                        yield f, root
        elif p.is_file():
            r = p.resolve()
            if r not in seen:
                seen.add(r)
                yield p, None
        else:
            print(f"qet-lint: warning: not a file or directory: {p}",
                  file=sys.stderr)


def _run_rules(doc: model.Document, rules, violations: list[report.Violation]):
    for rule in rules:
        violations.extend(rule(doc))


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    severities = set(report.DEFAULT_SEVERITIES)
    if args.include_info:
        severities.add("info")

    violations: list[report.Violation] = []
    for path, root in iter_files(args.paths):
        ext = path.suffix.lower()
        doc = model.load(path, display_path=_display_path(path, root))
        if ext == ".qet":
            _run_rules(doc, PROJECT_RULES, violations)
        elif ext == ".elmt":
            _run_rules(doc, ELEMENT_RULES, violations)

    violations = [v for v in violations if v.severity in severities]
    current = report.build_current(violations)

    if args.write_baseline:
        report.write_baseline(Path(args.baseline), current)
        print(f"baseline written to {args.baseline} "
              f"({len(violations)} violation(s), {len(current)} file(s))")
        return 0

    baseline_summary = ""
    exit_code = 0
    baseline_path = Path(args.baseline)
    if baseline_path.exists():
        baseline = report.load_baseline(baseline_path)
        regressions, improvements = report.compare_baseline(current, baseline)
        if regressions:
            exit_code = 1
            baseline_summary = (
                f"REGRESSIONS vs {args.baseline} ({len(regressions)}):\n"
                + "\n".join(
                    f"  - {p} {r}: now {cur}, was {was}"
                    for p, r, cur, was in regressions)
            )
        else:
            baseline_summary = f"no regressions vs {args.baseline}."
        if improvements:
            baseline_summary += (
                f"\n  {len(improvements)} vanished (fixed, or a rule stopped firing):\n"
                + "\n".join(
                    f"    - {p} {r}: now {cur}, was {was}"
                    for p, r, cur, was in improvements)
            )
    elif violations:
        # No baseline to suppress against: any finding fails the run.
        exit_code = 1

    if args.format == "json":
        print(report.format_json(violations))
    else:
        print(report.format_text(violations, baseline_summary))

    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
