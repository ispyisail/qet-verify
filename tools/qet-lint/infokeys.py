# SPDX-License-Identifier: GPL-2.0-or-later
"""The %{key} allowlist for P004, extracted from sources/qetinformation.h.

This is *not* the full elementInfoKeys() list -- it is that list's key
*strings* (e.g. "manufacturer_reference"), because that is what appears
literally inside a %{...} reference in a .qet file. The C++ constant names
(ELMT_MANUFACTURER_REF) never appear in project XML.

Extracted 2026-08-22 from upstream/master. Two things were verified before
trusting this list (see DIAGNOSTIC-TOOLS-PLAN.md G1a):

  - QETInformation::elementInfoKeys() registers 55 of the 60 ELMT_* constants
    declared in qetinformation.h. The five missing -- plc_tc, plc_t1..plc_t4
    -- are deliberately NOT in this allowlist: P004 must flag them.
  - %{key} has two distinct namespaces in a .qet file. Inside a
    <dynamic_elmt_text>, %{key} is element-info substitution and must resolve
    against this list. Inside a <titleblocktemplate>, %{key} is a
    *custom title-block field* -- an open-ended, per-project namespace where
    an unregistered key is not a bug (QETProject::setTitleBlock's `apply`
    lambda does `ctx.addValue(f.first, v)` for exactly this case). Measured
    across the 23 shipped examples: 178 of 180 %{key} occurrences are inside
    a titleblocktemplate; only 2 are inside a dynamic_elmt_text. P004 must
    only check the latter, or it is a 178-false-positive rule on day one.
"""
from __future__ import annotations

# elementInfoKeys() -- sources/qetinformation.cpp:141-200. 55 of the 60
# ELMT_* constants declared in qetinformation.h, plus the literal string
# "exclude_from_bom" (not an ELMT_* constant) -- 56 entries in total.
REGISTERED_ELEMENT_INFO_KEYS = frozenset({
    "formula", "label", "plant", "location", "comment", "function",
    "description", "designation", "manufacturer", "manufacturer_reference",
    "machine_manufacturer_reference", "supplier", "quantity", "unity",
    "auxiliary1", "description_auxiliary1", "designation_auxiliary1",
    "manufacturer_auxiliary1", "manufacturer_reference_auxiliary1",
    "machine_manufacturer_reference_auxiliary1", "supplier_auxiliary1",
    "quantity_auxiliary1", "unity_auxiliary1",
    "auxiliary2", "description_auxiliary2", "designation_auxiliary2",
    "manufacturer_auxiliary2", "manufacturer_reference_auxiliary2",
    "machine_manufacturer_reference_auxiliary2", "supplier_auxiliary2",
    "quantity_auxiliary2", "unity_auxiliary2",
    "auxiliary3", "description_auxiliary3", "designation_auxiliary3",
    "manufacturer_auxiliary3", "manufacturer_reference_auxiliary3",
    "machine_manufacturer_reference_auxiliary3", "supplier_auxiliary3",
    "quantity_auxiliary3", "unity_auxiliary3",
    "auxiliary4", "description_auxiliary4", "designation_auxiliary4",
    "manufacturer_auxiliary4", "manufacturer_reference_auxiliary4",
    "machine_manufacturer_reference_auxiliary4", "supplier_auxiliary4",
    "quantity_auxiliary4", "unity_auxiliary4",
    "plc_type", "plc_address", "plc_function", "plc_comment", "plc_crossref",
    "exclude_from_bom",
})

# Declared in qetinformation.h but NOT in elementInfoKeys() -- resolve to
# %{void} at runtime (QETInformation::elementInfoToVar). This is the proof
# fixture: P004 must flag any %{key} using one of these.
DECLARED_BUT_UNREGISTERED_KEYS = frozenset({
    "plc_tc", "plc_t1", "plc_t2", "plc_t3", "plc_t4",
})

# ELMT_* keys minus the PLC block above cover element info. DIA_*, PROJECT_*
# and COND_* are separate C++ namespaces (qetinformation.h) that also
# substitute inside a dynamic_elmt_text (diagram/project/conductor context is
# merged into the same DiagramContext at render time -- see
# assembleAndDisplayText()/replaceVariables() call sites). All resolve
# through the same %{key} syntax, so P004 checks them together.
DIAGRAM_INFO_KEYS = frozenset({
    "author", "date", "display_folio", "filename", "folio", "indexrev",
    "locmach", "plant", "pos", "title",
    "folio-id", "previous-folio-num", "next-folio-num",
})
PROJECT_INFO_KEYS = frozenset({
    "folio-total", "projecttitle", "projectpath", "projectfilename",
    "saveddate", "saveddate-eu", "saveddate-us", "savedtime",
    "savedfilename", "savedfilepath",
})
CONDUCTOR_INFO_KEYS = frozenset({
    "function", "tension_protocol", "conductor_color", "conductor_section",
    "formula", "text",
})
MISC_KEYS = frozenset({"version"})  # QET_VERSION

ALL_REGISTERED_KEYS = (
    REGISTERED_ELEMENT_INFO_KEYS
    | DIAGRAM_INFO_KEYS
    | PROJECT_INFO_KEYS
    | CONDUCTOR_INFO_KEYS
    | MISC_KEYS
)

# Bare folio tokens -- bordertitleblock.cpp:995-996, a literal
# QString::replace(), never %{}-wrapped and never checked against a
# registry. Listed here only so a caller can assert P004 does not touch them;
# they never appear as %{id} etc. in real files (confirmed: 0 hits across the
# 23 examples), so no exclusion logic is needed in the scanner itself.
BARE_FOLIO_TOKENS = frozenset({"%id", "%total", "%f", "%F"})
