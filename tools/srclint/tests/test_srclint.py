# SPDX-License-Identifier: GPL-2.0-or-later
"""The command line and --baseline, run on R-C over a small sources/ tree."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from srclint import main  # noqa: E402


def write_sources(root: Path, files: dict) -> Path:
    """Write {relative path: text} under root/sources and return that dir."""
    src = root / "sources"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    src.mkdir(parents=True, exist_ok=True)
    return src


def cpp(*strings: str) -> str:
    """One tr() call per line, line N holding strings[N-1]."""
    return "".join(f'auto s{i} = tr("{s}");\n' for i, s in enumerate(strings))


class MainCliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_gate_exits_nonzero_on_findings(self):
        src = write_sources(self.tmpdir, {"a.cpp": cpp("Ouvrir le fichier")})
        self.assertEqual(main(["--sources", str(src), "--gate"]), 1)

    def test_gate_exits_zero_on_english(self):
        src = write_sources(self.tmpdir, {"a.cpp": cpp("Open the file", "Size :")})
        self.assertEqual(main(["--sources", str(src), "--gate"]), 0)

    def test_no_gate_exits_zero_even_with_findings(self):
        src = write_sources(self.tmpdir, {"a.cpp": cpp("Ouvrir le fichier")})
        self.assertEqual(main(["--sources", str(src)]), 0)

    def test_qet_dir_finds_sources(self):
        write_sources(self.tmpdir, {"a.cpp": cpp("Ouvrir le fichier")})
        self.assertEqual(main(["--qet-dir", str(self.tmpdir), "--gate"]), 1)

    def test_missing_sources_exits_2(self):
        self.assertEqual(main(["--sources", str(self.tmpdir / "nope")]), 2)


class BaselineTest(unittest.TestCase):
    """--baseline: the gate fails on a finding the baseline does not already
    count, and on nothing else."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.baseline = self.tmpdir / "baseline.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _tree(self, files: dict) -> Path:
        d = Path(tempfile.mkdtemp(dir=self.tmpdir))
        return write_sources(d, files)

    def _record(self, files: dict):
        self.assertEqual(main(["--sources", str(self._tree(files)), "--baseline",
                               str(self.baseline), "--write-baseline"]), 0)

    def _gate(self, files: dict) -> int:
        return main(["--sources", str(self._tree(files)), "--baseline", str(self.baseline), "--gate"])

    def test_known_findings_pass(self):
        self._record({"a.cpp": cpp("Fermer")})
        self.assertEqual(self._gate({"a.cpp": cpp("Fermer")}), 0)

    def test_new_finding_fails(self):
        self._record({"a.cpp": cpp("Fermer")})
        self.assertEqual(self._gate({"a.cpp": cpp("Fermer", "Supprimer la sélection")}), 1)

    def test_second_copy_of_a_known_string_fails(self):
        # Counted, not just present: the same French string added again in
        # the same file is a new finding.
        self._record({"a.cpp": cpp("Fermer")})
        self.assertEqual(self._gate({"a.cpp": cpp("Fermer", "Fermer")}), 1)

    def test_moved_line_is_not_new(self):
        self._record({"a.cpp": cpp("Fermer")})
        self.assertEqual(self._gate({"a.cpp": "\n\n\n" + cpp("Fermer")}), 0)

    def test_same_string_in_another_file_is_new(self):
        self._record({"a.cpp": cpp("Fermer")})
        self.assertEqual(self._gate({"a.cpp": cpp("Fermer"), "b.cpp": cpp("Fermer")}), 1)

    def test_fixed_finding_passes(self):
        self._record({"a.cpp": cpp("Fermer", "Supprimer la sélection")})
        self.assertEqual(self._gate({"a.cpp": cpp("Fermer")}), 0)

    def test_missing_baseline_exits_2(self):
        src = self._tree({"a.cpp": ""})
        self.assertEqual(main(["--sources", str(src), "--baseline",
                               str(self.tmpdir / "nope.json"), "--gate"]), 2)


class CliSubprocessTest(unittest.TestCase):
    """One real end-to-end invocation, matching how the tool is actually run."""

    def test_runs_as_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(Path(tmp), {"a.cpp": cpp("Ouvrir le fichier")})
            script = Path(__file__).resolve().parents[1] / "srclint.py"
            result = subprocess.run(
                [sys.executable, str(script), "--qet-dir", tmp, "--gate"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("R-C", result.stdout)
            self.assertIn("a.cpp:1", result.stdout)


if __name__ == "__main__":
    unittest.main()
