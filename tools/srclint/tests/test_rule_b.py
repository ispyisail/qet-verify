# SPDX-License-Identifier: GPL-2.0-or-later
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from srclint import rule_b_contextless_lambda_connect  # noqa: E402


def findings_for(text: str):
    return rule_b_contextless_lambda_connect(Path("fixture.cpp"), text=text)


class RuleBTest(unittest.TestCase):
    def test_proof_fixture_f013_flagged_critical(self):
        # Verbatim shape of FINDINGS.md F013 --
        # sources/TerminalStrip/ui/terminalstriptreedockwidget.cpp:67.
        text = (
            "TerminalStripTreeDockWidget::TerminalStripTreeDockWidget() {\n"
            "    m_project_destroy_connection = connect(m_project, &QObject::destroyed, [this](){\n"
            "        this->m_current_strip.clear();\n"
            "        this->reload();\n"
            "    });\n"
            "}\n"
        )
        findings = findings_for(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")
        self.assertIn("destroyed", findings[0].detail)

    def test_must_not_report_shape_is_flagged_with_documented_reasoning(self):
        # sources/projectview.cpp:88 -- FINDINGS.md F013 says this specific
        # line "must not report", but is safe only by an accident of
        # ~QETProject's destruction order (deletes diagrams directly,
        # bypassing removeDiagram(), so diagramRemoved never fires during
        # destruction) -- not something derivable from this file's text.
        # F013 explicitly permits flagging it AS LONG AS the reasoning is
        # documented (see srclint's README and the upstream comment added
        # near the real projectview.cpp lines). This test locks in that
        # accepted, explained outcome -- not a false-positive to silently
        # chase away with a broader exclusion.
        text = (
            "ProjectView::ProjectView(QETProject *project) {\n"
            "    m_project = project;\n"
            "    connect(m_project, &QETProject::diagramAdded, [this](QETProject *project, Diagram *diagram) {\n"
            "        Q_UNUSED(project)\n"
            "        this->diagramAdded(diagram);\n"
            "    });\n"
            "}\n"
        )
        findings = findings_for(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")

    def test_sender_is_this_excluded(self):
        text = "connect(this, &Widget::somethingChanged, [this](){ this->update(); });"
        self.assertEqual(findings_for(text), [])

    def test_ui_prefixed_sender_excluded(self):
        text = "connect(ui->m_button_box, &QDialogButtonBox::accepted, [this](){ this->accept(); });"
        self.assertEqual(findings_for(text), [])

    def test_sender_parented_to_this_via_new_excluded(self):
        text = (
            "void f() {\n"
            "    Worker *w = new Worker(this);\n"
            "    connect(w, &Worker::done, [this](){ this->finish(); });\n"
            "}\n"
        )
        self.assertEqual(findings_for(text), [])

    def test_sender_parented_to_other_object_not_excluded(self):
        # Shaped after qetdiagrameditor.cpp:1586's real diagram_event --
        # new'd but parented to `d` (a Diagram), not `this` -- so the
        # exclusion must NOT fire.
        text = (
            "void f(Diagram *d) {\n"
            "    DiagramEventAddShape *diagram_event = new DiagramEventAddShape(d, Shape::Line);\n"
            "    connect(diagram_event, &DiagramEventInterface::destroyed, [this](){ this->clear(); });\n"
            "}\n"
        )
        findings = findings_for(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")

    def test_member_parented_to_this_via_assignment_excluded(self):
        text = (
            "void C::init() {\n"
            "    m_child = new Child(this);\n"
            "}\n"
            "void C::wire() {\n"
            "    connect(m_child, &Child::sig, [this](){ this->onSig(); });\n"
            "}\n"
        )
        self.assertEqual(findings_for(text), [])

    def test_constructor_parameter_member_not_excluded(self):
        # The plan's own example of real risk: a member set from a ctor
        # parameter has no lifetime guarantee relative to `this` at all.
        text = (
            "void C::C(Project *project) {\n"
            "    m_project = project;\n"
            "    connect(m_project, &Project::sig, [this](){ this->onSig(); });\n"
            "}\n"
        )
        findings = findings_for(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "warning")

    def test_no_lambda_capture_not_flagged(self):
        text = "connect(sender, &Sig::sig, receiver, &Receiver::slot);"
        self.assertEqual(findings_for(text), [])

    def test_lambda_not_capturing_this_not_flagged(self):
        text = "connect(sender, &Sig::sig, [row](){ x(row); });"
        self.assertEqual(findings_for(text), [])

    def test_context_object_present_not_flagged_even_capturing_this(self):
        # 4-arg connect with an explicit context object is safe regardless
        # of what the lambda captures -- the connection is owned by the
        # context, not the sender.
        text = "connect(sender, &Sig::sig, this, [this](){ this->onSig(); });"
        self.assertEqual(findings_for(text), [])


if __name__ == "__main__":
    unittest.main()
