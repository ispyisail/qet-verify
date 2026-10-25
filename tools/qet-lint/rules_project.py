# SPDX-License-Identifier: GPL-2.0-or-later
"""P0xx rules over .qet project files.

Each rule is a generator over a ``model.Document`` yielding ``Violation``s.

P001 -- NaN/Inf coordinate attribute. Delegated to
        ``simulator.canon.nan_or_inf_violations()`` (brief: "do not
        reimplement"); this module only attaches a source line.
P002 -- illegal XML 1.0 control character (raw byte or numeric character
        reference) anywhere in the file.
P003 -- duplicate uuid value within one project. Reuses the same uuid
        extraction canonicalize() uses to build ``uuid_universe`` (a
        ``root.iter()`` scan of ``uuid`` attributes), but flags only
        duplicates among ``<element>`` uuids -- the one value QET treats as a
        strict object identity. See the note in p003 below for why the full
        uuid universe cannot be used as-is.
P004 -- %{key} inside a <dynamic_elmt_text> where key is not a registered
        element/diagram/project/conductor info key (resolves to the
        literal "%{void}" at runtime). See infokeys.py.
P005 -- an electrical potential (potentials.py's connected-component
        grouping of conductors sharing a terminal, transitively) whose
        members disagree on wire number or wire colour.
"""
from __future__ import annotations

import collections
import re

from simulator.canon import CanonError, nan_or_inf_violations

from infokeys import ALL_REGISTERED_KEYS
from model import Document, control_char_offsets
from potentials import group_potentials
from report import Violation

# %{key} -- the element-info substitution syntax. Matches
# QETInformation::elementInfoToVar's own parsing: a bare identifier, letters/
# digits/underscore/hyphen (the only characters any registered key uses).
_INFO_KEY_RE = re.compile(r"%\{([A-Za-z0-9_-]+)\}")

# <dynamic_elmt_text ...>...</dynamic_elmt_text> and <titleblocktemplate
# ...>...</titleblocktemplate>, non-greedy across newlines (DOTALL) because a
# dynamic text's <text> child is itself indented on its own line. A regex
# rather than tree iteration because P004 needs byte spans to tell which
# %{key} sits inside which block, and Document already exposes .text with a
# byte-offset-to-line lookup that a tree traversal would have to reinvent.
_DYNAMIC_TEXT_RE = re.compile(r"<dynamic_elmt_text.*?</dynamic_elmt_text>", re.S)
_TITLEBLOCK_TEMPLATE_RE = re.compile(r"<titleblocktemplate.*?</titleblocktemplate>", re.S)


def p001_nan_or_inf(doc: Document):
    """Flag any NaN/Inf coordinate. Detection is canon.py's, not ours."""
    try:
        found = nan_or_inf_violations(doc.path)
    except CanonError:
        # Not well-formed XML. That is not this rule's finding -- the
        # control-character scan (P002) owns byte-level corruption, and a
        # structurally broken project is simply unparseable.
        return
    for gv in found:
        line = doc.line_of_attr(gv.uuid, gv.field, gv.raw_value)
        yield Violation(
            "P001", "error", doc.display_path, line,
            f"{gv.tag} has {gv.field}=\"{gv.raw_value}\" ({gv.kind})",
            evidence=f'uuid={gv.uuid} {gv.field}="{gv.raw_value}"',
        )


def _describe(cc) -> str:
    if cc.form == "raw":
        return f"raw byte 0x{cc.code_point:02X}"
    return f"character reference &#{cc.code_point};"


def p002_control_char(doc: Document):
    """Illegal XML 1.0 control character anywhere in the project file."""
    for cc in control_char_offsets(doc.raw):
        line = doc.line_of_offset(cc.offset)
        yield Violation(
            "P002", "error", doc.display_path, line,
            f"illegal XML 1.0 control character U+{cc.code_point:04X} "
            f"({_describe(cc)})",
            evidence=f"byte offset {cc.offset}",
        )


def p003_duplicate_element_uuid(doc: Document):
    """Duplicate ``<element>`` uuid -- two objects sharing one identity.

    canonicalize() builds ``uuid_universe`` from *every* ``uuid`` attribute in
    the document and stores it in a dict, which silently dedups -- it cannot
    report duplicates. Counting occurrences over the full universe and flagging
    any repeat would fire ~500 times across the 23 known-good example projects:
    QET copies a sub-item's uuid when it instantiates an element or duplicates
    a folio, so ``terminal`` / ``dynamic_text`` / ``dynamic_elmt_text`` /
    ``link_uuid`` uuids repeat pervasively in files QET loads and renders
    correctly (hand-verified -- see README). That is a false-positive flood,
    not a finding.

    The one uuid that *is* a strict identity is the ``<element>`` uuid: it is
    what QET resolves conductors (via terminal uuid), cross-folio links
    (``link_uuid``) and undo/redo by, and it is empirically unique across all
    23 example projects. A duplicate here is real corruption.
    """
    if doc.tree is None:
        return
    counts: collections.Counter = collections.Counter(
        el.get("uuid") for el in doc.tree.iter("element") if el.get("uuid")
    )
    for uuid, n in sorted(counts.items()):
        if n <= 1:
            continue
        lines = doc.lines_of_uuid(uuid)
        line = lines[1] if len(lines) >= 2 else (lines[0] if lines else 0)
        yield Violation(
            "P003", "error", doc.display_path, line,
            f"uuid {uuid} appears on {n} <element> elements",
            evidence="duplicate element uuid (second occurrence)",
        )


def p004_unregistered_info_key(doc: Document):
    """%{key} inside a dynamic element text where key is not a registered
    element/diagram/project/conductor info key.

    Scope is deliberately narrow: only %{key} occurrences whose byte offset
    falls inside a <dynamic_elmt_text>...</dynamic_elmt_text> span are
    checked. %{key} inside a <titleblocktemplate> is a different, open-ended
    namespace (custom title-block fields) and is never flagged -- see the
    module docstring above and infokeys.py.
    """
    text = doc.text
    dtext_spans = [m.span() for m in _DYNAMIC_TEXT_RE.finditer(text)]
    if not dtext_spans:
        return
    tbt_spans = [m.span() for m in _TITLEBLOCK_TEMPLATE_RE.finditer(text)]

    def _in_any(offset: int, spans: list[tuple[int, int]]) -> bool:
        return any(a <= offset < b for a, b in spans)

    seen: set[tuple[str, int]] = set()
    for m in _INFO_KEY_RE.finditer(text):
        offset = m.start()
        if not _in_any(offset, dtext_spans):
            continue
        if _in_any(offset, tbt_spans):
            # A titleblocktemplate should never be nested inside a
            # dynamic_elmt_text in a well-formed project, but the spans are
            # computed independently -- keep the check explicit rather than
            # assume the nesting can't happen.
            continue
        key = m.group(1)
        if key in ALL_REGISTERED_KEYS:
            continue
        dedup = (key, doc.line_of_offset(offset))
        if dedup in seen:
            continue
        seen.add(dedup)
        line = doc.line_of_offset(offset)
        yield Violation(
            "P004", "error", doc.display_path, line,
            f'%{{{key}}} is not a registered element/diagram/project info key '
            f'-- resolves to the literal text "%{{void}}" at runtime',
            evidence=f"key={key!r}",
        )


def _norm(value: str | None) -> str:
    """Strip a conductor attribute value for comparison. Real data has both
    kinds of noise: a lone "&#xa;" (a literal stored newline) that should
    read as blank, and leading-space colour-name variants (" Noir" vs
    "Noir") that should NOT be flagged as a second colour -- both are just
    ``.strip()`` on the decoded text, which XML parsing already resolves the
    character reference for.
    """
    return (value or "").strip()


def p005_potential_disagrees(doc: Document):
    """A potential (potentials.group_potentials(), conductors connected via
    a shared terminal, transitively -- a bus/junction is one potential) whose
    members disagree on wire number (``num``) or wire colour
    (``conductor_color``).

    Conservative on purpose: only flags when 2+ DISTINCT NON-EMPTY values
    appear for the same attribute within one potential. A potential where
    only some members carry a value and the rest are blank is NOT flagged --
    QET's own numbering/colouring conventions may legitimately label only
    one representative conductor per net, and that is not verified either
    way in this session, so treating "some blank" as a disagreement would
    risk a real false-positive class rather than a checked one.

    Severity: warning. A mismatch here does not mean the diagram is wrong --
    conductors on one node CAN legitimately be recoloured/renumbered
    per-segment in some conventions -- it means two conductors that share a
    physical connection point disagree on a label a reader would expect to
    match, worth a human looking at.
    """
    if doc.tree is None:
        return
    for potential in group_potentials(doc.tree):
        if len(potential.conductors) < 2:
            continue
        for attr, label in (("num", "wire number"), ("conductor_color", "wire colour")):
            values = {_norm(c.get(attr)) for c in potential.conductors}
            values.discard("")
            if len(values) < 2:
                continue
            first = potential.conductors[0]
            line = doc.line_of_attr("", attr, first.get(attr, ""))
            yield Violation(
                "P005", "warning", doc.display_path, line,
                f"potential of {len(potential.conductors)} conductor(s) disagrees on "
                f"{label}: {sorted(values)!r}",
                evidence=f"attr={attr} values={sorted(values)!r} "
                f"conductor_count={len(potential.conductors)}",
            )
