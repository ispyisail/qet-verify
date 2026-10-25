# SPDX-License-Identifier: GPL-2.0-or-later
"""Hermetic tests for qet-lint's five rules + baseline diffing.

Run from the repo root:

    python3 -m unittest discover -s tools/qet-lint/tests -v

The fixtures are synthetic (written to a temp dir), so the tests do not
depend on the QET element collection or example projects existing anywhere.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]   # tools/qet-lint
_REPO = Path(__file__).resolve().parents[3]  # repo root
for _p in (_PKG, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import model                      # noqa: E402
import report                     # noqa: E402
import rules_element as re_el      # noqa: E402
import rules_project as re_proj    # noqa: E402


def _run(path: Path, rules):
    doc = model.load(path, display_path=str(path))
    return list(v for rule in rules for v in rule(doc))


class ControlCharTest(unittest.TestCase):
    def test_raw_nul_is_flagged(self):
        found = model.control_char_offsets(b"a\x00b")
        self.assertEqual([(f.form, f.code_point, f.offset) for f in found],
                         [("raw", 0x00, 1)])

    def test_charref_is_flagged(self):
        found = model.control_char_offsets(b"x &#11; y")
        self.assertEqual([(f.form, f.code_point) for f in found],
                         [("charref", 0x0B)])

    def test_hex_charref_is_flagged(self):
        found = model.control_char_offsets(b"x &#x0B; y")
        self.assertEqual([(f.form, f.code_point) for f in found],
                         [("charref", 0x0B)])

    def test_legal_controls_are_not_flagged(self):
        # tab, LF, CR are the only legal ASCII controls in XML 1.0.
        self.assertEqual(model.control_char_offsets(b"\t\n\r"), [])
        # a reference to a *legal* control is not a violation.
        self.assertEqual(model.control_char_offsets(b"&#10;&#13;&#9;"), [])


class ProjectRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, content: bytes) -> Path:
        p = self.dir / name
        p.write_bytes(content)
        return p

    def test_p001_flags_nan_coordinate(self):
        p = self._write("nan.qet", (
            b'<project><diagram order="0">'
            b'<element type="t" x="nan" y="10" uuid="{11111111-2222-3333-4444-555555555555}"/>'
            b'</diagram></project>'
        ))
        vs = _run(p, (re_proj.p001_nan_or_inf,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "P001")
        self.assertIn('x="nan"', vs[0].message)

    def test_p001_ignores_finite_coordinates(self):
        p = self._write("ok.qet", (
            b'<project><diagram order="0">'
            b'<element type="t" x="10.5" y="-3" uuid="{11111111-2222-3333-4444-555555555555}"/>'
            b'</diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p001_nan_or_inf,)), [])

    def test_p002_flags_raw_nul(self):
        p = self._write("nul.qet", b'<project>\x00</project>')
        vs = _run(p, (re_proj.p002_control_char,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "P002")
        self.assertEqual(vs[0].line, 1)

    def test_p002_flags_charref(self):
        p = self._write("ref.qet", b'<project>&#11;</project>')
        vs = _run(p, (re_proj.p002_control_char,))
        self.assertEqual(len(vs), 1)
        self.assertIn("U+000B", vs[0].message)

    def test_p003_flags_duplicate_element_uuid(self):
        p = self._write("dup.qet", (
            b'<project>'
            b'<diagram order="0">'
            b'<element type="a" x="1" y="1" uuid="{11111111-2222-3333-4444-555555555555}"/>'
            b'<element type="b" x="2" y="2" uuid="{11111111-2222-3333-4444-555555555555}"/>'
            b'</diagram></project>'
        ))
        vs = _run(p, (re_proj.p003_duplicate_element_uuid,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "P003")
        self.assertIn("appears on 2", vs[0].message)

    def test_p003_ignores_unique_uuids(self):
        p = self._write("uniq.qet", (
            b'<project><diagram order="0">'
            b'<element type="a" x="1" y="1" uuid="{11111111-2222-3333-4444-555555555555}"/>'
            b'<element type="b" x="2" y="2" uuid="{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"/>'
            b'</diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p003_duplicate_element_uuid,)), [])

    def test_p003_ignores_terminal_uuid_copies(self):
        # QET copies terminal uuids when instantiating an element; P003 is
        # scoped to <element> uuids and must not flag those copies.
        p = self._write("termdup.qet", (
            b'<project><diagram order="0">'
            b'<element type="a" x="1" y="1" uuid="{11111111-2222-3333-4444-555555555555}">'
            b'<terminal x="0" y="0" uuid="{tttttttt-tttt-tttt-tttt-tttttttttttt}"/>'
            b'</element>'
            b'<element type="b" x="2" y="2" uuid="{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}">'
            b'<terminal x="0" y="0" uuid="{tttttttt-tttt-tttt-tttt-tttttttttttt}"/>'
            b'</element>'
            b'</diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p003_duplicate_element_uuid,)), [])

    def test_p005_flags_disagreeing_potential(self):
        # Shaped after the real Habitat-Unifilaire.qet finding: a 6-way
        # bus junction where one conductor's num disagrees with the rest.
        conds = "".join(
            f'<conductor terminal1="{i}" terminal2="20" num="{n}"/>'
            for i, n in ((9, "10mm²"), (25, "10mm²k"), (16, "10mm²k"))
        )
        p = self._write("disagree.qet", (
            f'<project><diagram order="0"><conductors>{conds}</conductors>'
            f"</diagram></project>"
        ).encode())
        vs = _run(p, (re_proj.p005_potential_disagrees,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "P005")
        self.assertIn("wire number", vs[0].message)

    def test_p005_agreeing_potential_not_flagged(self):
        conds = "".join(
            f'<conductor terminal1="{i}" terminal2="20" num="45"/>' for i in (9, 25, 16)
        )
        p = self._write("agree.qet", (
            f'<project><diagram order="0"><conductors>{conds}</conductors>'
            f"</diagram></project>"
        ).encode())
        self.assertEqual(_run(p, (re_proj.p005_potential_disagrees,)), [])

    def test_p005_some_blank_some_set_not_flagged(self):
        # Conservative-by-design: only 2+ DISTINCT NON-EMPTY values count.
        # A potential where some members are unlabelled is not (yet) known
        # to be a defect -- see the rule's docstring.
        p = self._write("partial.qet", (
            b'<project><diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2" num="45"/>'
            b'<conductor terminal1="2" terminal2="3" num=""/>'
            b'</conductors></diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p005_potential_disagrees,)), [])

    def test_p005_singleton_potential_not_flagged(self):
        p = self._write("single.qet", (
            b'<project><diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2" num="45"/>'
            b'</conductors></diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p005_potential_disagrees,)), [])

    def test_p005_flags_colour_disagreement(self):
        p = self._write("colour.qet", (
            b'<project><diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2" conductor_color="Bleu"/>'
            b'<conductor terminal1="2" terminal2="3" conductor_color="Noir"/>'
            b'</conductors></diagram></project>'
        ))
        vs = _run(p, (re_proj.p005_potential_disagrees,))
        self.assertEqual(len(vs), 1)
        self.assertIn("wire colour", vs[0].message)

    def test_p005_whitespace_colour_variant_not_flagged(self):
        # Real corpus data has " Noir" vs "Noir" -- stray whitespace, not a
        # second colour.
        p = self._write("wscolour.qet", (
            b'<project><diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2" conductor_color=" Noir"/>'
            b'<conductor terminal1="2" terminal2="3" conductor_color="Noir"/>'
            b'</conductors></diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p005_potential_disagrees,)), [])

    def test_p005_literal_newline_value_treated_as_blank(self):
        # Real corpus data has num="&#xa;" (a stored literal newline).
        p = self._write("newline.qet", (
            b'<project><diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2" num="&#xa;"/>'
            b'<conductor terminal1="2" terminal2="3" num="45"/>'
            b'</conductors></diagram></project>'
        ))
        self.assertEqual(_run(p, (re_proj.p005_potential_disagrees,)), [])

    def test_p005_unresolved_formula_vs_resolved_number_flagged(self):
        # Shaped after the real perceuse.qet finding: one conductor still
        # carries the raw autonumbering formula instead of its resolved
        # value, inside an otherwise-consistently-numbered potential.
        p = self._write("formula.qet", (
            b'<project><diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2" num="45" formula="%sequ_1"/>'
            b'<conductor terminal1="2" terminal2="3" num="%sequ_1" formula="%sequ_1"/>'
            b'</conductors></diagram></project>'
        ))
        vs = _run(p, (re_proj.p005_potential_disagrees,))
        self.assertEqual(len(vs), 1)


class InfoKeyRuleTest(unittest.TestCase):
    """P004 -- %{key} inside <dynamic_elmt_text> not in the registered-key
    allowlist. See DIAGNOSTIC-TOOLS-PLAN.md G1a and infokeys.py's module
    docstring for why <titleblocktemplate> is explicitly out of scope.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, content: str) -> Path:
        p = self.dir / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_flags_unregistered_key_in_dynamic_text(self):
        """Proof fixture: plc_tc is declared in qetinformation.h but not
        registered in elementInfoKeys() -- resolves to %{void} at runtime."""
        path = self._write("proof.qet", """<?xml version="1.0"?>
<project version="0.100.1">
  <diagram><elements><element uuid="{e1}" type="test.elmt">
    <inputs><dynamic_elmt_text uuid="{t1}">
      <text>%{plc_tc}</text>
    </dynamic_elmt_text></inputs>
  </element></elements></diagram>
</project>""")
        doc = model.load(path, display_path=str(path))
        found = list(re_proj.p004_unregistered_info_key(doc))
        self.assertEqual(len(found), 1)
        self.assertIn("plc_tc", found[0].evidence)

    def test_ignores_registered_key_in_dynamic_text(self):
        path = self._write("clean.qet", """<?xml version="1.0"?>
<project version="0.100.1">
  <diagram><elements><element uuid="{e1}" type="test.elmt">
    <inputs><dynamic_elmt_text uuid="{t1}">
      <text>%{label} / %{description}</text>
    </dynamic_elmt_text></inputs>
  </element></elements></diagram>
</project>""")
        doc = model.load(path, display_path=str(path))
        self.assertEqual(list(re_proj.p004_unregistered_info_key(doc)), [])

    def test_ignores_unregistered_key_in_titleblocktemplate(self):
        """%{ref} etc. inside a titleblocktemplate is a custom title-block
        field, not element info -- must never be flagged. Measured: 178 of
        180 %{key} occurrences across the 23 shipped examples are exactly
        this case."""
        path = self._write("titleblock.qet", """<?xml version="1.0"?>
<project version="0.100.1">
  <diagram>
    <titleblocktemplate name="custom">
      <field name="reference"><value>
        <translation lang="en">%{ref}</translation>
      </value></field>
    </titleblocktemplate>
  </diagram>
</project>""")
        doc = model.load(path, display_path=str(path))
        self.assertEqual(list(re_proj.p004_unregistered_info_key(doc)), [])

    def test_no_dynamic_text_no_crash(self):
        path = self._write("empty.qet", """<?xml version="1.0"?>
<project version="0.100.1"><diagram/></project>""")
        doc = model.load(path, display_path=str(path))
        self.assertEqual(list(re_proj.p004_unregistered_info_key(doc)), [])

    def test_diagram_and_project_keys_are_registered(self):
        """DIA_*/PROJECT_*/COND_* keys (folio, projecttitle, etc.) also
        substitute inside a dynamic_elmt_text and must not be flagged --
        they are a separate C++ namespace from ELMT_*, merged at render
        time, not a second open-ended field like titleblocktemplate."""
        path = self._write("diaproj.qet", """<?xml version="1.0"?>
<project version="0.100.1">
  <diagram><elements><element uuid="{e1}" type="test.elmt">
    <inputs><dynamic_elmt_text uuid="{t1}">
      <text>%{folio} %{projecttitle} %{conductor_color}</text>
    </dynamic_elmt_text></inputs>
  </element></elements></diagram>
</project>""")
        doc = model.load(path, display_path=str(path))
        self.assertEqual(list(re_proj.p004_unregistered_info_key(doc)), [])


class ElementRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, content: bytes) -> Path:
        p = self.dir / name
        p.write_bytes(content)
        return p

    def test_e001_flags_unparseable(self):
        p = self._write("bad.elmt", b"<definition><name></definition>")
        vs = _run(p, (re_el.e001_not_parseable,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "E001")

    def test_e001_clean_file(self):
        p = self._write("ok.elmt", b'<definition version="0.100.0"/>')
        self.assertEqual(_run(p, (re_el.e001_not_parseable,)), [])

    def test_e002_flags_charref(self):
        # The xpx.elmt fixture: &#11; (U+000B) in a <name lang="ca"> element.
        p = self._write("xpx.elmt",
                        b'<definition version="0.100.0">\n<names>\n'
                        b'<name lang="ca">Unitat &#11;erge</name>\n</names>\n</definition>\n')
        vs = _run(p, (re_el.e002_control_char,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "E002")
        self.assertEqual(vs[0].line, 3)


    def _terminal_element(self, names):
        """A minimal but valid .elmt with one <terminal> per name given."""
        terms = "".join(
            f'<terminal uuid="{{{i:08d}-0000-0000-0000-000000000000}}" '
            f'name="{n}" x="0" y="{i}" orientation="n"/>\n'
            for i, n in enumerate(names)
        )
        return self._write(f"e{abs(hash(tuple(names)))}.elmt",
            f'<definition version="0.100.0"><description>\n{terms}'
            f'</description></definition>\n'.encode())

    def test_e003_flags_lexicographic_vs_natural_divergence(self):
        """Proof fixture shape: T1..T20 sorted as text puts T10 before T2."""
        p = self._terminal_element([f"T{i}" for i in (1, 2, 3, 9, 10, 11, 20)])
        vs = _run(p, (re_el.e003_terminal_name_ordering,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "E003")

    def test_e003_ignores_terminals_already_in_natural_order(self):
        p = self._terminal_element(["T1", "T2", "T3", "L1", "L2", "PE"])
        self.assertEqual(_run(p, (re_el.e003_terminal_name_ordering,)), [])

    def test_e003_ignores_single_terminal(self):
        p = self._terminal_element(["T1"])
        self.assertEqual(_run(p, (re_el.e003_terminal_name_ordering,)), [])

    def test_e003_ignores_unnamed_terminals(self):
        p = self._terminal_element(["", "", ""])
        self.assertEqual(_run(p, (re_el.e003_terminal_name_ordering,)), [])

    def test_e004_flags_duplicate_name(self):
        p = self._terminal_element(["A", "B", "A"])
        vs = _run(p, (re_el.e004_duplicate_terminal_name,))
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0].rule_id, "E004")
        self.assertIn('"A"', vs[0].message)

    def test_e004_ignores_unique_names(self):
        p = self._terminal_element(["A", "B", "C"])
        self.assertEqual(_run(p, (re_el.e004_duplicate_terminal_name,)), [])

    def test_e004_ignores_repeated_empty_names(self):
        """5,241 terminals collection-wide have name="" -- the normal,
        unnamed state. Must never be treated as a duplicate."""
        p = self._terminal_element(["", "", "", "A"])
        self.assertEqual(_run(p, (re_el.e004_duplicate_terminal_name,)), [])

    def test_e004_flags_only_once_for_three_way_duplicate(self):
        """Three terminals sharing one name is one finding, not three."""
        p = self._terminal_element(["A", "A", "A"])
        vs = _run(p, (re_el.e004_duplicate_terminal_name,))
        self.assertEqual(len(vs), 1)


class BaselineTest(unittest.TestCase):
    def test_compare_regression_and_improvement(self):
        base = {"a.qet": {"P002": 1}}
        cur = {"a.qet": {"P002": 2}, "b.qet": {"P001": 1}}
        regressions, improvements = report.compare_baseline(cur, base)
        self.assertEqual(regressions, [("a.qet", "P002", 2, 1), ("b.qet", "P001", 1, 0)])
        self.assertEqual(improvements, [])

    def test_compare_improvement(self):
        base = {"a.qet": {"P002": 2}}
        cur = {"a.qet": {"P002": 0}}
        regressions, improvements = report.compare_baseline(cur, base)
        self.assertEqual(regressions, [])
        self.assertEqual(improvements, [("a.qet", "P002", 0, 2)])

    def test_build_current_and_roundtrip(self):
        vs = [report.Violation("P002", "error", "a.qet", 1, "x"),
              report.Violation("P002", "error", "a.qet", 2, "y"),
              report.Violation("E001", "error", "b.elmt", 0, "z")]
        current = report.build_current(vs)
        self.assertEqual(current, {"a.qet": {"P002": 2}, "b.elmt": {"E001": 1}})


if __name__ == "__main__":
    unittest.main()
