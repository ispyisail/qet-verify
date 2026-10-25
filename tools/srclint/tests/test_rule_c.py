# SPDX-License-Identifier: GPL-2.0-or-later
"""R-C: a translatable string written in French, read from the sources."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from srclint import looks_french, rule_c_french_source, translatable_strings  # noqa: E402


class LooksFrench(unittest.TestCase):
    def test_french(self):
        for t in ["Paysage", "Personnaliser", "Couleur de fond du folio", "Éditer", "Supprimer la sélection"]:
            self.assertTrue(looks_french(t), t)

    def test_english_including_french_style_spacing(self):
        for t in ["Size :", "Convert to Bézier curve", "Unable to write to the file « %1 ».",
                  "Open", "Delete this sheet ?", "Purple : Lavender"]:
            self.assertFalse(looks_french(t), t)


class TranslatableStrings(unittest.TestCase):
    def test_cpp_calls(self):
        code = '''a = tr("Ouvrir le fichier"); // tr("in a comment")
b = QObject::tr("Two "
                "parts");
/* tr("in a block
   comment") */
c = QCoreApplication::translate("Ctx", "Fermer la fenêtre");
d = QT_TRANSLATE_NOOP("Ctx", "Annuler");
e = QT_TR_NOOP("Escaped \\"quote\\"");
f = attr("not translatable");
g = tr(variable);
'''
        self.assertEqual(translatable_strings(Path("x.cpp"), code), [
            (1, "Ouvrir le fichier"), (2, "Two parts"), (6, "Fermer la fenêtre"),
            (7, "Annuler"), (8, 'Escaped "quote"')])

    def test_ui_strings_skip_notr(self):
        ui = '''<widget>
 <property name="text"><string>Couleur &amp; style</string></property>
 <property name="objectName"><string notr="true">Couleur</string></property>
</widget>'''
        self.assertEqual(translatable_strings(Path("x.ui"), ui), [(2, "Couleur & style")])


class RuleC(unittest.TestCase):
    def test_flags_french_only(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "sources"
            (src / "ui").mkdir(parents=True)
            (src / "a.cpp").write_text('x = tr("Open");\ny = tr("Ouvrir le fichier");\n', encoding="utf-8")
            (src / "ui" / "b.ui").write_text("<string>Supprimer la sélection</string>\n<string>Delete</string>\n",
                                             encoding="utf-8")
            found = rule_c_french_source(src)
            self.assertEqual([(f.file, f.line, f.ident) for f in found], [
                ("sources/a.cpp", "2", "Ouvrir le fichier"),
                ("sources/ui/b.ui", "1", "Supprimer la sélection")])


if __name__ == "__main__":
    unittest.main()
