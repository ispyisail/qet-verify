# SPDX-License-Identifier: GPL-2.0-or-later
"""Hermetic tests for potentials.py's terminal-key resolution and grouping."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from potentials import group_potentials, terminal_key  # noqa: E402


def parse(xml: bytes):
    return ET.fromstring(xml)


class TerminalKeyTest(unittest.TestCase):
    def test_legacy_key_scoped_by_diagram(self):
        k1 = terminal_key(0, None, "5")
        k2 = terminal_key(1, None, "5")
        self.assertNotEqual(k1, k2)
        self.assertEqual(terminal_key(0, None, "5"), terminal_key(0, None, "5"))

    def test_modern_key_ignores_diagram_index(self):
        # Element uuids are globally unique real uuids -- diagram index is
        # irrelevant to identity for the modern scheme.
        k1 = terminal_key(0, "{elem}", "{term}")
        k2 = terminal_key(99, "{elem}", "{term}")
        self.assertEqual(k1, k2)

    def test_empty_terminal_unresolvable(self):
        self.assertIsNone(terminal_key(0, None, ""))
        self.assertIsNone(terminal_key(0, None, None))
        self.assertIsNone(terminal_key(0, "{elem}", ""))

    def test_empty_element_with_nonempty_terminal_is_legacy_not_blank_modern(self):
        # An empty element1="" must not silently produce a degenerate
        # "modern" key that collides with every other empty-element1 case.
        key = terminal_key(0, "", "7")
        self.assertEqual(key, ("legacy", 0, "7"))


class GroupPotentialsTest(unittest.TestCase):
    def _diagram(self, conductors_xml: str, extra: str = "") -> ET.Element:
        return parse(
            f'<project><diagram order="0">{extra}<conductors>{conductors_xml}'
            f"</conductors></diagram></project>".encode()
        )

    def test_two_conductors_sharing_a_terminal_are_one_potential(self):
        tree = self._diagram(
            '<conductor terminal1="1" terminal2="2" num="5"/>'
            '<conductor terminal1="2" terminal2="3" num="5"/>'
        )
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 1)
        self.assertEqual(len(pots[0].conductors), 2)

    def test_unrelated_conductors_are_separate_potentials(self):
        tree = self._diagram(
            '<conductor terminal1="1" terminal2="2"/>'
            '<conductor terminal1="3" terminal2="4"/>'
        )
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 2)

    def test_transitive_chain_is_one_potential(self):
        # A-B, B-C, C-D: not directly pairwise connected, but one component.
        tree = self._diagram(
            '<conductor terminal1="A" terminal2="B"/>'
            '<conductor terminal1="B" terminal2="C"/>'
            '<conductor terminal1="C" terminal2="D"/>'
        )
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 1)
        self.assertEqual(len(pots[0].conductors), 3)

    def test_bus_junction_groups_all_conductors_on_it(self):
        # Shaped after the real Habitat-Unifilaire.qet finding: 6 conductors
        # all landing on the same terminal "20".
        conds = "".join(f'<conductor terminal1="{i}" terminal2="20"/>' for i in (9, 25, 16, 33, 41, 38))
        tree = self._diagram(conds)
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 1)
        self.assertEqual(len(pots[0].conductors), 6)

    def test_diagrams_do_not_cross_contaminate_legacy_ids(self):
        # Two unrelated diagrams both using terminal "1"/"2" must NOT be
        # unioned into one potential -- Diagram::toXml() rebuilds the legacy
        # id table fresh per diagram.
        tree = parse(
            b'<project>'
            b'<diagram order="0"><conductors>'
            b'<conductor terminal1="1" terminal2="2"/>'
            b'</conductors></diagram>'
            b'<diagram order="1"><conductors>'
            b'<conductor terminal1="1" terminal2="2"/>'
            b'</conductors></diagram>'
            b'</project>'
        )
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 2)
        self.assertEqual({p.diagram_index for p in pots}, {0, 1})

    def test_modern_scheme_grouping(self):
        tree = self._diagram(
            '<conductor element1="{e1}" terminal1="{t1}" element2="{e2}" terminal2="{t2}"/>'
            '<conductor element1="{e2}" terminal1="{t2}" element2="{e3}" terminal2="{t3}"/>'
        )
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 1)
        self.assertEqual(len(pots[0].conductors), 2)

    def test_mixed_scheme_ends_on_one_conductor(self):
        # conductor.cpp's toXml() sets each end independently based on that
        # end's own terminal.uuid().isNull() -- a single conductor CAN have
        # one legacy end and one modern end. Must not crash, and the two
        # differently-shaped keys must not be treated as equal.
        tree = self._diagram(
            '<conductor terminal1="7" element2="{e2}" terminal2="{t2}"/>'
        )
        pots = group_potentials(tree)
        self.assertEqual(len(pots), 1)
        self.assertEqual(len(pots[0].conductors), 1)

    def test_conductor_with_no_resolvable_terminal_skipped(self):
        tree = self._diagram('<conductor terminal1="" terminal2=""/>')
        pots = group_potentials(tree)
        self.assertEqual(sum(len(p.conductors) for p in pots), 0)


if __name__ == "__main__":
    unittest.main()
