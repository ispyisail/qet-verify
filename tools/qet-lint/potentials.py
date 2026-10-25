# SPDX-License-Identifier: GPL-2.0-or-later
"""Group a .qet diagram's conductors into electrical potentials.

A "potential" here is a connected component of the graph whose nodes are
terminals and whose edges are conductors -- i.e. every conductor reachable
from another by a chain of shared terminals (a bus/junction with 3+
conductors on one terminal is one potential, transitively).

QET has two format-selected, mutually exclusive-per-endpoint addressing
schemes for a conductor's terminal1/terminal2 (verified against
Conductor::valideXml() and Diagram::fromXml()'s findTerminal(), not
guessed -- see DIAGNOSTIC-TOOLS-PLAN.md G4.2):

  * modern: an "element1"/"element2" attribute is present. terminal1/
    terminal2 are then a per-terminal-DEFINITION uuid (Terminal::uuid(),
    constant across every instance of that .elmt type, defined in the
    .elmt file, not the project) -- so a terminal's identity is the pair
    (element instance uuid, terminal definition uuid), both of which ARE
    directly present on the conductor tag itself.
  * legacy: no element1/element2. terminal1/terminal2 are plain integers
    indexing a table Diagram::toXml() rebuilds FROM SCRATCH on every save,
    scoped to ONE diagram (each diagram's own toXml() call gets a fresh
    table) -- so a legacy terminal's identity for grouping purposes is
    (diagram index, the integer), never just the bare integer, or two
    unrelated folios' terminal "5"s would be falsely unioned.

Because a single <conductor> element sets each end independently based on
that end's OWN terminal.uuid().isNull() (conductor.cpp's toXml()), the two
ends of one conductor can, in principle, use different schemes -- handled
symmetrically here, not assumed to match.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree.ElementTree import Element

TerminalKey = tuple  # ("uuid", element_uuid, terminal_uuid) | ("legacy", diagram_index, terminal_int)


def terminal_key(diagram_index: int, element_attr: str | None, terminal_attr: str | None) -> TerminalKey | None:
    """The grouping key for one conductor endpoint, or None if unresolvable."""
    if terminal_attr is None:
        return None
    terminal_attr = terminal_attr.strip()
    if not terminal_attr:
        return None
    if element_attr:
        element_attr = element_attr.strip()
        if not element_attr:
            return None
        return ("uuid", element_attr, terminal_attr)
    return ("legacy", diagram_index, terminal_attr)


class _UnionFind:
    def __init__(self):
        self._parent: dict[TerminalKey, TerminalKey] = {}

    def find(self, x: TerminalKey) -> TerminalKey:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: TerminalKey, b: TerminalKey) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


@dataclass
class Potential:
    diagram_index: int
    conductors: list[Element] = field(default_factory=list)


def group_potentials(tree: Element) -> list[Potential]:
    """Every potential (connected component of conductors) in the document,
    scoped per-diagram (a potential never spans two <diagram> elements --
    physical wiring doesn't, and legacy terminal ids aren't even comparable
    across diagrams). Conductors with an unresolvable endpoint on BOTH sides
    are skipped -- they cannot be grouped with anything, and are not part of
    the finding this module exists to support.
    """
    potentials: list[Potential] = []
    for diagram_index, diagram in enumerate(tree.iter("diagram")):
        uf = _UnionFind()
        conductors = list(diagram.iter("conductor"))
        keyed = []
        for cond in conductors:
            k1 = terminal_key(diagram_index, cond.get("element1"), cond.get("terminal1"))
            k2 = terminal_key(diagram_index, cond.get("element2"), cond.get("terminal2"))
            keyed.append((cond, k1, k2))
            if k1 is not None and k2 is not None:
                uf.union(k1, k2)
            elif k1 is not None:
                uf.find(k1)
            elif k2 is not None:
                uf.find(k2)

        groups: dict[TerminalKey, Potential] = {}
        for cond, k1, k2 in keyed:
            anchor = k1 if k1 is not None else k2
            if anchor is None:
                continue
            root = uf.find(anchor)
            groups.setdefault(root, Potential(diagram_index=diagram_index)).conductors.append(cond)
        potentials.extend(groups.values())
    return potentials
