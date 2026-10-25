# SPDX-License-Identifier: GPL-2.0-or-later
"""Violation type, text/JSON output, and baseline diffing.

The baseline mirrors ``tests/determinism/baseline.json`` in shape -- a map
keyed by file, then by check id, then by a scalar result. Here the scalar is a
violation *count* (a file can carry several duplicate uuids), where the
determinism baseline's scalar is a boolean.

The comparison is the same "got worse" gate the determinism harness uses: a
regression is a (file, rule) whose count went *up* (or is brand new); the
inverse -- a count that went down -- is reported as an improvement, not a
failure, because a legitimate fix is not a regression. The important thing a
suppressing baseline must NOT do is hide a rule silently breaking: if P001
fired N times yesterday and zero today, that shows up as N vanished
violations, not as a green run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SEVERITIES = ("info", "warning", "error")
# "info" is opt-in: it exists so a too-noisy rule can be shipped without
# training people to ignore the tool. No stage-1 rule is "info", but the
# severity machinery is here so demoting one (brief W2-stage1 §5) is a
# one-character change rather than a rework.
DEFAULT_SEVERITIES = frozenset(("error", "warning"))

_RULE_ORDER = ("P001", "P002", "P003", "P004", "P005", "E001", "E002", "E003", "E004")


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "evidence": self.evidence,
        }


def sort_key(v: Violation):
    return (v.path, _RULE_ORDER.index(v.rule_id) if v.rule_id in _RULE_ORDER else 999,
            v.line, v.rule_id, v.message)


def build_current(violations: list[Violation]) -> dict[str, dict[str, int]]:
    """Collapse a violation list into {path: {rule_id: count}}."""
    current: dict[str, dict[str, int]] = {}
    for v in violations:
        rules = current.setdefault(v.path, {})
        rules[v.rule_id] = rules.get(v.rule_id, 0) + 1
    return current


def load_baseline(path: Path) -> dict[str, dict[str, int]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"baseline {path} is not a JSON object")
    out: dict[str, dict[str, int]] = {}
    for file, rules in data.items():
        if not isinstance(rules, dict):
            raise ValueError(f"baseline entry for {file!r} is not an object")
        out[file] = {rule: int(count) for rule, count in rules.items()}
    return out


def write_baseline(path: Path, current: dict[str, dict[str, int]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2, sort_keys=True)
        fh.write("\n")


def compare_baseline(current, baseline):
    """Return (regressions, improvements), each a list of (path, rule, cur, was).

    A regression means a rule found *more* on a file than the recorded
    baseline (or a brand-new file/rule pair appeared) -- that fails the gate.
    An improvement means a rule found *fewer* -- legitimate when someone fixed
    the file, but worth eyeballing because it can also mean a rule broke.
    """
    regressions: list[tuple[str, str, int, int]] = []
    improvements: list[tuple[str, str, int, int]] = []
    for path, rules in sorted(current.items()):
        base_rules = baseline.get(path, {})
        for rule, count in sorted(rules.items()):
            was = base_rules.get(rule, 0)
            if count > was:
                regressions.append((path, rule, count, was))
    for path, rules in sorted(baseline.items()):
        cur_rules = current.get(path, {})
        for rule, was in sorted(rules.items()):
            cur = cur_rules.get(rule, 0)
            if cur < was:
                improvements.append((path, rule, cur, was))
    return regressions, improvements


def format_text(violations: list[Violation], baseline_summary: str = "") -> str:
    lines: list[str] = []
    by_rule: dict[str, int] = {}
    for v in violations:
        by_rule[v.rule_id] = by_rule.get(v.rule_id, 0) + 1
    if violations:
        lines.append(f"{len(violations)} violation(s) across {len(by_rule)} rule(s):")
        for rule in _RULE_ORDER:
            if rule in by_rule:
                lines.append(f"  {rule}: {by_rule[rule]}")
    else:
        lines.append("0 violations.")
    for v in sorted(violations, key=sort_key):
        loc = f"{v.path}:{v.line}" if v.line else v.path
        lines.append(f"{v.rule_id} [{v.severity}] {loc}: {v.message}")
        if v.evidence:
            lines.append(f"      {v.evidence}")
    if baseline_summary:
        lines.append("")
        lines.append(baseline_summary)
    return "\n".join(lines)


def format_json(violations: list[Violation]) -> str:
    return json.dumps([v.to_dict() for v in sorted(violations, key=sort_key)],
                      indent=2)
