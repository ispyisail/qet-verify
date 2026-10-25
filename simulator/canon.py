# SPDX-License-Identifier: GPL-2.0-or-later
"""
Canonical projection of a .qet project file.

Per SIMULATOR-DESIGN.md §4.3, this is the single most important piece of
code in the harness: too strict and every oracle drowns in false
positives from cosmetic noise (colours, fonts, timestamps); too loose and
it hides real corruption. It has its own tests in tests/test_canon.py,
including a test that it DOES detect deliberately corrupted state --
a canon() that can't tell two different projects apart is worse than
useless.

What counts as identity-bearing here, and why:

  - element:    uuid, type, x, y, z, orientation, prefix, freezeLabel.
                NOT colour/font/label-rendering attributes -- those are
                display config, not content.
  - conductor:  identity is the SORTED (terminal1, terminal2) pair within
                its diagram. Sorted because a conductor is electrically
                symmetric; if a resave ever swapped which terminal is "1"
                and which is "2" that would be a cosmetic difference, not
                a semantic one, and should not fail O2/O3.
                Note: modern QET DOES write a uuid attribute on every
                <conductor> it saves, but assigns it fresh on first load
                of a legacy file that lacks one (probed: 741.qet gains 67
                new uuids on first save, stable from the second save on),
                so the uuid is a migration artifact, not identity.
                uuid_universe (below) records it regardless, which is
                what lets the O9 cross-run self-check expose that
                first-save churn instead of hiding it.
  - diagram:    QET's schema has no diagram uuid either -- identity is
                the `order` attribute (folios are explicitly ordered;
                see moveDiagramUp/Down in qetdiagrameditor.cpp). Title is
                kept as informational only, since renaming a folio is a
                legitimate edit, not corruption.
  - uuid_universe: EVERY uuid attribute found anywhere in the document,
                tagged by its element name. This is deliberately generic
                rather than hand-enumerating every item type (dynamic
                texts, terminal strips, independent texts, ...) so O3
                (full uuid set preserved) covers item types this module
                was never taught about by name.

Explicitly stripped, never even parsed into canon: the <properties> block
(saveddate*, savedtime, savedfilename, savedfilepath) -- these change on
every save by design and are not content.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# Attributes on <element> that are part of its identity/content.
_ELEMENT_KEYS = ("type", "x", "y", "z", "orientation", "prefix", "freezeLabel")
# Attributes on <dynamic_elmt_text> worth comparing (its rendered content
# depends on live autonum state, so we compare configuration, not output).
_DTEXT_KEYS = ("text_from", "x", "y", "rotation")

_FLOAT_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _num(s: str | None):
    """Parse a QET numeric attribute, preserving NaN/Inf if literally present."""
    if s is None or s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return s  # non-numeric -- return raw so callers can flag it
    return v


@dataclass
class Canon:
    diagrams: list[dict] = field(default_factory=list)   # sorted by order
    uuid_universe: dict[str, str] = field(default_factory=dict)  # uuid -> tag name
    counts: dict[str, int] = field(default_factory=dict)
    raw_project_attrs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "diagrams": self.diagrams,
            "uuid_universe": self.uuid_universe,
            "counts": self.counts,
        }


class CanonError(RuntimeError):
    """The file could not be parsed at all (not a canon *mismatch* -- a parse failure)."""


def canonicalize(path: Path) -> Canon:
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        raise CanonError(f"not well-formed XML: {e}") from e

    root = tree.getroot()
    uuid_universe: dict[str, str] = {}
    diagrams = []

    for el in root.iter():
        u = el.get("uuid")
        if u:
            uuid_universe[u] = el.tag

    for d_idx, d in enumerate(root.iter("diagram")):
        order = d.get("order", str(d_idx))
        elements = {}
        conductors = {}
        dtexts = {}

        for e in d.iter("element"):
            u = e.get("uuid")
            if not u:
                continue
            elements[u] = {k: _num(e.get(k)) if k in ("x", "y", "z", "orientation") else e.get(k)
                           for k in _ELEMENT_KEYS}

        for c in d.iter("conductor"):
            t1, t2 = c.get("terminal1"), c.get("terminal2")
            if t1 is None or t2 is None:
                continue
            lo, hi = sorted([t1, t2])
            key = f"{lo}-{hi}"
            # Store the SORTED pair, not the raw terminal1/terminal2, so a
            # cosmetic swap of which terminal QET calls "1" vs "2" (the
            # conductor is electrically symmetric) does not register as a
            # semantic difference. Caught by
            # test_tolerates_conductor_terminal_order_swap.
            conductors.setdefault(key, []).append({
                "terminals": [lo, hi],
                "type": c.get("type"),
            })

        for dt in d.iter("dynamic_elmt_text"):
            u = dt.get("uuid")
            if not u:
                continue
            dtexts[u] = {k: _num(dt.get(k)) if k in ("x", "y", "rotation") else dt.get(k)
                         for k in _DTEXT_KEYS}
            info_name = dt.find("info_name")
            dtexts[u]["info_name"] = info_name.text if info_name is not None else None

        diagrams.append({
            "order": order,
            "elements": elements,
            "conductors": conductors,
            "dynamic_texts": dtexts,
            # The folio's own attributes (cols/colsize/rows/rowsize/...).
            # Deliberately kept raw and NOT compared by diff()/canon_equal()
            # -- they describe the page, not its content. Exposed so callers
            # can bound-check element coordinates against the drawable area:
            # an element dropped just outside the frame still saves as a
            # perfectly valid project, so nothing else here would catch it.
            "raw_attrs": dict(d.attrib),
        })

    diagrams.sort(key=lambda d: d["order"])

    counts = {
        "diagrams": len(diagrams),
        "elements": sum(len(d["elements"]) for d in diagrams),
        "conductors": sum(len(v) for d in diagrams for v in d["conductors"].values()),
        "uuids": len(uuid_universe),
    }

    return Canon(
        diagrams=diagrams,
        uuid_universe=uuid_universe,
        counts=counts,
        raw_project_attrs={k: v for k, v in root.attrib.items()},
    )


def diff(a: Canon, b: Canon) -> list[str]:
    """Human-readable list of differences; empty list means canon-equal."""
    diffs: list[str] = []

    if a.counts != b.counts:
        diffs.append(f"counts differ: {a.counts} vs {b.counts}")

    ua, ub = set(a.uuid_universe), set(b.uuid_universe)
    only_a, only_b = ua - ub, ub - ua
    if only_a:
        diffs.append(f"{len(only_a)} uuid(s) only in first: {sorted(only_a)[:5]}{'...' if len(only_a) > 5 else ''}")
    if only_b:
        diffs.append(f"{len(only_b)} uuid(s) only in second: {sorted(only_b)[:5]}{'...' if len(only_b) > 5 else ''}")

    common_tag_mismatch = {u for u in (ua & ub) if a.uuid_universe[u] != b.uuid_universe[u]}
    if common_tag_mismatch:
        diffs.append(f"{len(common_tag_mismatch)} uuid(s) changed tag type: {sorted(common_tag_mismatch)[:5]}")

    da = {d["order"]: d for d in a.diagrams}
    db = {d["order"]: d for d in b.diagrams}
    if set(da) != set(db):
        diffs.append(f"diagram order-set differs: {sorted(da)} vs {sorted(db)}")

    for order in sorted(set(da) & set(db)):
        pa, pb = da[order], db[order]
        for cat in ("elements", "conductors", "dynamic_texts"):
            if pa[cat] != pb[cat]:
                keys_a, keys_b = set(pa[cat]), set(pb[cat])
                if keys_a != keys_b:
                    diffs.append(
                        f"diagram order={order} {cat} key-set differs: "
                        f"only_a={sorted(keys_a - keys_b)[:3]} only_b={sorted(keys_b - keys_a)[:3]}"
                    )
                else:
                    changed = [k for k in keys_a if pa[cat][k] != pb[cat][k]]
                    if changed:
                        diffs.append(
                            f"diagram order={order} {cat} value differs for {changed[:3]}"
                            f"{'...' if len(changed) > 3 else ''}"
                        )
    return diffs


def canon_equal(a: Canon, b: Canon) -> bool:
    return not diff(a, b)


# ---------------------------------------------------------------------
# O6: geometric invariants -- independent of canon(), operates directly
# on the file so it can flag literal "nan"/"inf" strings that _num()
# would otherwise swallow as "non-numeric".
#
# NaN/Inf detection is an ABSOLUTE invariant: no real, un-corrupted
# project should ever contain one (verified: zero hits across all 23
# files in qet-fix/examples/).
#
# Grid alignment is deliberately NOT checked as an absolute invariant.
# Measured against the same 23-file corpus, 5 real, ordinary example
# projects contain elements sitting at positions like x="488" or
# x="201" -- not multiples of 10, not of 5, not corrupted, just placed
# there by a user with snapping off (or by an older QET version, or via
# import). An absolute "everything must be on a 10px grid" check would
# have flagged 483 "violations" in one single legitimate file
# (perceuse.qet) alone -- exactly the false-positive flood
# SIMULATOR-DESIGN.md §4.3 warns a too-strict canon() produces.
#
# The property PR #660 actually cares about, and the one worth
# checking, is a DELTA: an element that WAS on the grid before an
# operation must still BE on the grid after it (design doc §3, O6:
# "an item on the grid stays on the grid after any rotate/move/undo
# cycle"). grid_regressions() below checks exactly that, comparing two
# snapshots of the same uuids rather than judging either one in
# isolation.
# ---------------------------------------------------------------------

@dataclass
class GeometryViolation:
    uuid: str
    tag: str
    field: str
    raw_value: str
    kind: str  # "nan" or "inf"


def nan_or_inf_violations(path: Path) -> list[GeometryViolation]:
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        # Consistent with canonicalize(): unparseable input is a
        # CanonError, not an uncaught exception. Found the hard way --
        # against a *real* QET binary this branch was never reached
        # (QET either crashes before producing output, refuses to write
        # it, or writes well-formed XML), so it went unexercised until a
        # deliberately dumb stand-in binary in a test fed a mutator's
        # malformed byte-level garbage straight through unmodified.
        raise CanonError(f"not well-formed XML: {e}") from e
    violations: list[GeometryViolation] = []

    for el in tree.getroot().iter():
        if el.tag not in ("element", "conductor", "dynamic_elmt_text"):
            continue
        u = el.get("uuid", "")
        for field_name in ("x", "y"):
            raw = el.get(field_name)
            if raw is None or raw == "":
                continue
            low = raw.strip().lower()
            if low == "nan":
                violations.append(GeometryViolation(u, el.tag, field_name, raw, "nan"))
            elif low in ("inf", "-inf", "infinity", "-infinity"):
                violations.append(GeometryViolation(u, el.tag, field_name, raw, "inf"))
            elif _FLOAT_RE.match(raw):
                v = float(raw)
                if math.isnan(v) or math.isinf(v):
                    violations.append(GeometryViolation(u, el.tag, field_name, raw,
                                                          "nan" if math.isnan(v) else "inf"))
    return violations


@dataclass
class GridRegression:
    uuid: str
    before: tuple[float, float]
    after: tuple[float, float]


def grid_regressions(before: Path, after: Path, grid: int = 10) -> list[GridRegression]:
    """
    Elements present in both files whose position was grid-aligned in
    `before` and is no longer grid-aligned in `after`. An element that
    was never on the grid is not this function's concern -- see the
    module-level note above for why an absolute check is the wrong tool.
    """
    def positions(path: Path) -> dict[str, tuple[float, float]]:
        try:
            tree = ET.parse(str(path))
        except ET.ParseError as e:
            raise CanonError(f"not well-formed XML: {e}") from e
        out = {}
        for el in tree.getroot().iter("element"):
            u = el.get("uuid")
            x, y = el.get("x"), el.get("y")
            if not u or x is None or y is None:
                continue
            try:
                out[u] = (float(x), float(y))
            except ValueError:
                continue  # non-numeric position is nan_or_inf_violations()'s concern, not this one
        return out

    def on_grid(pos: tuple[float, float]) -> bool:
        x, y = pos
        # NaN/Inf positions are nan_or_inf_violations()'s concern, not this
        # function's -- round(nan / grid) raises ValueError, so treat a
        # non-finite position as simply "not on grid" rather than crash.
        # Found by simulator/runner.py's adversarial sweep within the first
        # ~30 mutated inputs (an inject_nan_coordinate mutation surviving
        # through to a resaved file).
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        return (abs(x - round(x / grid) * grid) <= 1e-6
                and abs(y - round(y / grid) * grid) <= 1e-6)

    pos_before, pos_after = positions(before), positions(after)
    regressions = []
    for u, p_before in pos_before.items():
        p_after = pos_after.get(u)
        if p_after is not None and on_grid(p_before) and not on_grid(p_after):
            regressions.append(GridRegression(u, p_before, p_after))
    return regressions
