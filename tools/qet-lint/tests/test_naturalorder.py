# SPDX-License-Identifier: GPL-2.0-or-later
"""Hermetic tests for naturalorder.py -- the terminal-name comparator ported
from the C++ original already verified on local branch
fix/terminal-sort-order (97/97 real elements match a reference natural sort;
0 strict-weak-ordering violations over an adversarial corpus).

Run from the repo root:

    python3 -m unittest discover -s tools/qet-lint/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from naturalorder import terminal_name_less_than as lt, natural_sort_key as key


class NaturalOrderTest(unittest.TestCase):
    def test_t1_through_t20_sorts_numerically(self):
        names = ["T1", "T10", "T11", "T2", "T20", "T3", "T9"]
        self.assertEqual(
            sorted(names, key=key),
            ["T1", "T2", "T3", "T9", "T10", "T11", "T20"],
        )

    def test_plain_digits_sort_numerically(self):
        names = ["1", "2", "3", "10", "11", "20", "100", "202"]
        self.assertEqual(sorted(names, key=key), names)  # already in order

    def test_leading_zeros_treated_as_equal_value(self):
        # "007" and "7" compare as the same numeric value; stable sort keeps
        # original relative order between equal keys.
        self.assertFalse(lt("007", "7"))
        self.assertFalse(lt("7", "007"))

    def test_mixed_alphanumeric_natural_order(self):
        names = ["L1", "L10", "L2", "N", "PE"]
        self.assertEqual(sorted(names, key=key), ["L1", "L2", "L10", "N", "PE"])

    def test_non_numeric_names_unaffected(self):
        names = ["Cable", "PE", "N"]
        self.assertEqual(sorted(names, key=key), sorted(names))

    def test_strict_weak_ordering_over_adversarial_corpus(self):
        """Guards a real bug class: an invalid comparator makes sorted()
        silently produce a wrong-but-plausible-looking order rather than
        erroring, so this is checked explicitly rather than trusted."""
        corpus = [
            "", "0", "00", "007", "7", "08", "8", "9", "10", "1", "2", "20",
            "100", "202", "L", "L1", "L10", "L2", "N", "PE", "0V.1", "0V.2",
            "Cable", "DP", "1a", "1A", "a1", "A1", "T1", "T01", "T10",
        ]
        for a in corpus:
            self.assertFalse(lt(a, a), f"irreflexivity violated for {a!r}")
            for b in corpus:
                self.assertFalse(
                    lt(a, b) and lt(b, a),
                    f"asymmetry violated for {a!r}, {b!r}",
                )
        for a in corpus:
            for b in corpus:
                for c in corpus:
                    if lt(a, b) and lt(b, c):
                        self.assertTrue(
                            lt(a, c),
                            f"transitivity violated for {a!r}, {b!r}, {c!r}",
                        )

    def test_duplicate_names_are_tied(self):
        """Neither compares less-than the other -- the basis for E004's
        claim that duplicate terminal names make the sort's tie-breaking
        for those two terminals unspecified."""
        self.assertFalse(lt("T3", "T3"))

    def test_wago_fixture_matches_reference_natural_sort(self):
        """A subset of the proof fixture's own terminal names -- the
        A-prefixed group must land in numeric order, not lexicographic
        order (which would put A11/A15/A16 before A2/A7)."""
        names = ["A15", "A16", "A7", "A11", "A1", "A2"]
        self.assertEqual(
            sorted(names, key=key),
            ["A1", "A2", "A7", "A11", "A15", "A16"],
        )
        self.assertNotEqual(sorted(names, key=key), sorted(names))


if __name__ == "__main__":
    unittest.main()
