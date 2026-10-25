# SPDX-License-Identifier: GPL-2.0-or-later
"""E0xx rules over .elmt element files.

E001 -- file does not parse as XML (Python ElementTree).
E002 -- illegal XML 1.0 control character (same scan as P002).
E003 -- terminal names whose lexicographic order differs from their numeric
        order (DIAGNOSTIC-TOOLS-PLAN.md G4.1). The label-transfer sort in
        sources/undocommand/linkelementcommand.cpp compares terminal names
        as plain strings, so a terminal numbered above 9 gets the wrong
        master label. naturalorder.py ports the exact comparator already
        verified against this defect (local branch fix/terminal-sort-order)
        and this rule finds the elements it matters for, statically.
E004 -- two terminals in one element sharing the same name. QET's own
        terminal lookup (Element::terminal(const QString &)) is name-keyed
        within one element, so a duplicate silently makes the second
        terminal unreachable by name -- the first match always wins.

The two rules are deliberately adjacent in the report: an element whose only
defect is a control character fires *both* -- it is not well-formed (E001) and
it contains an illegal control character (E002). That is correct, not a
double-count: E001 is "Python rejects it", E002 is "here is the byte that made
it illegal". They separate "the file is bad" (element collection) from "Qt
mishandles bad input" (the .qet loader) -- different bugs in different repos.
"""
from __future__ import annotations

import re
from collections import Counter

from model import Document, control_char_offsets
from naturalorder import natural_sort_key
from report import Violation

# ElementTree's ParseError carries the position in prose: "line 4, column 35".
_POS_RE = re.compile(r"line (\d+)")


def e001_not_parseable(doc: Document):
    """The file is not well-formed XML, so QET (and ElementTree) cannot load it."""
    if doc.parse_error is None:
        return
    line = 0
    m = _POS_RE.search(doc.parse_error)
    if m:
        line = int(m.group(1))
    yield Violation(
        "E001", "error", doc.display_path, line,
        f"file does not parse as XML: {doc.parse_error}",
        evidence=doc.parse_error,
    )


def e002_control_char(doc: Document):
    """Illegal XML 1.0 control character in the element file (same scan as P002)."""
    for cc in control_char_offsets(doc.raw):
        line = doc.line_of_offset(cc.offset)
        if cc.form == "raw":
            desc = f"raw byte 0x{cc.code_point:02X}"
        else:
            desc = f"character reference &#{cc.code_point};"
        yield Violation(
            "E002", "error", doc.display_path, line,
            f"illegal XML 1.0 control character U+{cc.code_point:04X} ({desc})",
            evidence=f"byte offset {cc.offset}",
        )


def e003_terminal_name_ordering(doc: Document):
    """Terminal names whose lexicographic order differs from natural order.

    Compares sorted(names) (what a naive string sort produces) against
    sorted(names, key=natural_sort_key) (what a human -- and QET's label
    transfer, once fixed -- expects). Any element where these two orders
    differ is one where a lexicographic sort would put terminals on the
    wrong master label past terminal 9. Flags every element once, not once
    per out-of-place terminal -- the finding is "this element's terminal
    order is affected", not a per-pair diff.
    """
    if doc.tree is None:
        return
    names = [t.get("name") for t in doc.tree.iter("terminal") if t.get("name")]
    if len(names) < 2:
        return
    if sorted(names) == sorted(names, key=natural_sort_key):
        return
    # Anchor the report on the first out-of-place terminal for a line number,
    # rather than the whole element -- lines_of_uuid needs a uuid, and the
    # first terminal whose name differs from its natural-sorted neighbour is
    # as good an anchor as any single one.
    first_uuid = next(
        (t.get("uuid") for t in doc.tree.iter("terminal") if t.get("name")), None
    )
    line = 0
    if first_uuid:
        lines = doc.lines_of_uuid(first_uuid)
        line = lines[0] if lines else 0
    yield Violation(
        "E003", "warning", doc.display_path, line,
        f"{len(names)} terminal name(s) sort differently lexicographically "
        f"than numerically -- a lexicographic sort (e.g. the label-transfer "
        f"path in linkelementcommand.cpp before the fix on "
        f"fix/terminal-sort-order) assigns the wrong master label to "
        f"terminals numbered above 9",
        evidence=f"lexicographic={sorted(names)[:6]}... "
                 f"natural={sorted(names, key=natural_sort_key)[:6]}...",
    )


def e004_duplicate_terminal_name(doc: Document):
    """Two terminals in one element sharing the same non-empty name.

    Checked before writing this docstring, not assumed: there is no
    Element::terminal(const QString&) or equivalent name-keyed lookup
    anywhere in sources/qetgraphicsitem/element.{h,cpp} -- QET does not
    resolve a terminal by name internally, so a duplicate is not a lookup
    hazard the way a duplicate uuid is.

    What IS verified: the natural-order comparator used for master-label
    transfer (naturalorder.terminal_name_less_than(), and its C++ original
    on fix/terminal-sort-order) treats two identically-named terminals as
    tied -- neither compares less-than the other. std::sort tolerates ties,
    but does not guarantee their relative order is preserved or
    reproducible, so which of the two duplicate-named terminals receives
    which master label becomes implementation-defined rather than something
    the element's own data determines. Flagged as a warning on that basis,
    plus the plainer point that two terminals a human reads as "the same
    terminal" are ambiguous regardless of what code does with them.

    Deliberately excludes name="" -- 5,241 terminals collection-wide have no
    name at all (the normal, unnamed state for a generic terminal), and
    treating that as a "duplicate" would be a false-positive flood, not a
    finding.
    """
    if doc.tree is None:
        return
    terms = [t for t in doc.tree.iter("terminal") if t.get("name")]
    counts = Counter(t.get("name") for t in terms)
    seen_names = set()
    for t in terms:
        name = t.get("name")
        if counts[name] <= 1 or name in seen_names:
            continue
        seen_names.add(name)
        uuid = t.get("uuid")
        line = 0
        if uuid:
            lines = doc.lines_of_uuid(uuid)
            line = lines[-1] if lines else 0  # last occurrence: the shadowed one
        yield Violation(
            "E004", "warning", doc.display_path, line,
            f'terminal name "{name}" used {counts[name]} times in this '
            f"element -- ambiguous to a human, and ties the master-label "
            f"sort comparator so their relative order is unspecified",
            evidence=f"name={name!r} count={counts[name]}",
        )
