# SPDX-License-Identifier: GPL-2.0-or-later
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectscan import captures_this, find_connect_calls, lambda_capture_list  # noqa: E402


class FindConnectCallsTest(unittest.TestCase):
    def test_single_line_three_arg(self):
        text = 'void f() { connect(sender, &Sig::sig, [this](){ this->g(); }); }'
        calls = find_connect_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0], "sender")
        self.assertEqual(calls[0].args[1], "&Sig::sig")
        self.assertTrue(calls[0].args[2].startswith("[this]"))

    def test_multiline_call_with_nested_parens_and_commas_in_body(self):
        # Shaped after projectview.cpp's real diagramAdded connect.
        text = (
            "connect(m_project, &QETProject::diagramAdded, [this](QETProject *project, Diagram *diagram) {\n"
            "    Q_UNUSED(project)\n"
            "    this->diagramAdded(diagram);\n"
            "});\n"
        )
        calls = find_connect_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0], "m_project")
        self.assertEqual(calls[0].args[1], "&QETProject::diagramAdded")
        self.assertIn("this->diagramAdded(diagram)", calls[0].args[2])

    def test_line_number_is_of_connect_token_not_call_end(self):
        text = "\n\n\nconnect(a, &A::sig, [this](){ x(); });\n"
        calls = find_connect_calls(text)
        self.assertEqual(calls[0].start_line, 4)

    def test_old_style_four_arg_connect_not_mistaken_for_lambda(self):
        text = "connect(sender, &Sig::sig, receiver, &Receiver::slot);"
        calls = find_connect_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args), 4)
        self.assertIsNone(lambda_capture_list(calls[0].args[3]))

    def test_five_arg_connect_with_context_object(self):
        text = "connect(sender, &Sig::sig, this, [this](){ x(); }, Qt::QueuedConnection);"
        calls = find_connect_calls(text)
        self.assertEqual(len(calls[0].args), 5)

    def test_string_literal_with_paren_does_not_unbalance(self):
        text = 'connect(a, &A::sig, [this](){ label("(unbalanced"); });'
        calls = find_connect_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertIn("label", calls[0].args[2])


class CapturesThisTest(unittest.TestCase):
    def test_bare_this(self):
        self.assertTrue(captures_this("[this](){ x(); }"))

    def test_this_with_other_captures(self):
        self.assertTrue(captures_this("[this, row](){ x(); }"))
        self.assertTrue(captures_this("[row, this](){ x(); }"))

    def test_no_this(self):
        self.assertFalse(captures_this("[row](){ x(); }"))

    def test_capture_by_value_default_not_treated_as_this(self):
        # [=] implicitly captures this too, but R-B's scope (per
        # DIAGNOSTIC-TOOLS-PLAN.md G6.2) is explicit `this` captures --
        # documented as an explicit scope limit, not silently missed.
        self.assertFalse(captures_this("[=](){ x(); }"))

    def test_not_a_lambda_returns_false(self):
        self.assertFalse(captures_this("someArray[this]"))
        self.assertFalse(captures_this("receiver"))


if __name__ == "__main__":
    unittest.main()
