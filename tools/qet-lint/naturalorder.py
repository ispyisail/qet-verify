# SPDX-License-Identifier: GPL-2.0-or-later
"""Natural-order comparison of terminal names.

The identical algorithm already verified in QElectroTech's own source (local
branch fix/terminal-sort-order, sources/undocommand/linkelementcommand.cpp
terminalNameLessThan()) -- three sort sites there decide which master label
lands on which terminal by comparing names lexicographically, which breaks as
soon as a terminal is numbered above 9. This module ports the same comparator
to Python so E003 can detect the same defect statically, over the full
element collection rather than one project's terminal list.

Verified there against 97 real multi-terminal elements (all matching a
reference natural sort exactly) and as a valid strict weak ordering (0
irreflexivity/asymmetry/transitivity violations over an adversarial corpus).
Ported here rather than re-derived.
"""
from __future__ import annotations


def terminal_name_less_than(a: str, b: str) -> bool:
    """True if `a` sorts before `b` in natural order.

    Runs of digits compare by value; everything else compares character by
    character. So "2" sorts before "10", and "L2" before "L10". Leading
    zeros are ignored ("007" == "7" in digit-run comparison). Deliberately
    locale-independent -- QCollator::setNumericMode() would do the same job,
    but its result varies with the active locale, and this ordering has to
    be reproducible across machines to be a meaningful lint rule.
    """
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i].isdigit() and b[j].isdigit():
            start_a, start_b = i, j
            while i < len(a) and a[i].isdigit():
                i += 1
            while j < len(b) and b[j].isdigit():
                j += 1
            # ignore leading zeros so "007" and "7" compare equal
            while start_a < i - 1 and a[start_a] == "0":
                start_a += 1
            while start_b < j - 1 and b[start_b] == "0":
                start_b += 1
            len_a, len_b = i - start_a, j - start_b
            if len_a != len_b:
                return len_a < len_b
            if a[start_a:i] != b[start_b:j]:
                return a[start_a:i] < b[start_b:j]
        else:
            if a[i] != b[j]:
                return a[i] < b[j]
            i += 1
            j += 1
    return (len(a) - i) < (len(b) - j)


def natural_sort_key(name: str):
    """A sort key equivalent to terminal_name_less_than, for use with
    sorted()/list.sort() instead of pairwise comparison. Splits into
    alternating non-digit/digit runs, converting digit runs to int so
    Python's default tuple comparison reproduces natural order."""
    import re
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p for p in parts]
