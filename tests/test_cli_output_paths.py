from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "demo" / "fixture_server.py"
BASELINE = {
    "format": "mcp-shipcheck/v1",
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}},
    "tools": [
        {"name": name, "inputSchema": {"type": "object", "properties": {}}}
        for name in ("read_note", "search_notes")
    ],
}


class OutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.baseline = self.root / "baseline.json"
        self.baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
        self.original = self.baseline.read_bytes()
        self.candidate = self.root / "candidate.json"
        self.report = self.root / "report.json"
        self.method_log = self.root / "methods.log"

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["MCP_SHIPCHECK_METHOD_LOG"] = str(self.method_log)
        return subprocess.run(
            [sys.executable, "-m", "mcp_shipcheck", *args],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def verify(self, output: Path | str, report: Path | str | None = None):
        args = ["verify", "--baseline", str(self.baseline), "--output", str(output)]
        if report is not None:
            args.extend(["--compare-output", str(report)])
        return self.run_cli(
            *args, "--", sys.executable, str(FIXTURE), "--mode", "breaking"
        )

    def assert_rejected_before_probe(self, result) -> None:
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("same file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.baseline.read_bytes(), self.original)
        self.assertFalse(self.method_log.exists(), "invalid paths must not start the server")

    def test_verify_cannot_overwrite_baseline_and_compare_candidate_to_itself(self) -> None:
        self.assert_rejected_before_probe(self.verify(self.baseline))

    def test_verify_rejects_relative_alias_of_baseline(self) -> None:
        self.assert_rejected_before_probe(self.verify("./baseline.json"))

    def test_verify_rejects_report_overwriting_baseline(self) -> None:
        self.assert_rejected_before_probe(self.verify(self.candidate, self.baseline))
        self.assertFalse(self.candidate.exists())

    def test_verify_rejects_two_outputs_pointing_to_same_new_file(self) -> None:
        self.assert_rejected_before_probe(self.verify(self.candidate, "./candidate.json"))
        self.assertFalse(self.candidate.exists())

    def test_verify_rejects_hard_link_to_baseline(self) -> None:
        alias = self.root / "hardlink.json"
        try:
            os.link(self.baseline, alias)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        self.assert_rejected_before_probe(self.verify(alias))
        self.assertEqual(alias.read_bytes(), self.original)

    def test_verify_rejects_symlink_to_baseline(self) -> None:
        alias = self.root / "symlink.json"
        try:
            alias.symlink_to(self.baseline)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        self.assert_rejected_before_probe(self.verify(alias))

    @unittest.skipUnless(os.name == "nt", "Windows path case normalization")
    def test_verify_rejects_case_alias_of_new_outputs(self) -> None:
        self.assert_rejected_before_probe(self.verify(self.candidate, "CANDIDATE.JSON"))
        self.assertFalse(self.candidate.exists())

    @unittest.skipUnless(os.name == "nt", "Windows trailing-dot/space normalization")
    def test_verify_rejects_ambiguous_windows_output_components(self) -> None:
        for report in ("candidate.json.", "candidate.json ", "new. /report.json"):
            with self.subTest(report=report):
                result = self.verify(self.candidate, report)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("ending in a dot or space", result.stderr)
                self.assertEqual(self.baseline.read_bytes(), self.original)
                self.assertFalse(self.candidate.exists())
                self.assertFalse(self.method_log.exists())

    @unittest.skipUnless(os.name == "nt", "Windows alternate data streams")
    def test_verify_rejects_alternate_data_stream_outputs(self) -> None:
        for report in ("candidate.json::$DATA", "candidate.json:report"):
            with self.subTest(report=report):
                result = self.verify(self.candidate, report)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("alternate data streams", result.stderr)
                self.assertEqual(self.baseline.read_bytes(), self.original)
                self.assertFalse(self.candidate.exists())
                self.assertFalse(self.method_log.exists())

    @unittest.skipUnless(os.name == "nt", "Windows generated short paths")
    def test_verify_does_not_replace_new_candidate_through_short_name(self) -> None:
        import ctypes

        self.candidate = self.root / "candidate-snapshot-long-name.json"
        self.candidate.touch()
        short_path = ctypes.create_unicode_buffer(32768)
        get_short_path = ctypes.windll.kernel32.GetShortPathNameW
        get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        get_short_path.restype = ctypes.c_uint32
        size = get_short_path(str(self.candidate), short_path, len(short_path))
        if not size or size >= len(short_path) or "~" not in short_path.value:
            self.skipTest("filesystem does not assign short names")
        alias = short_path.value
        self.candidate.unlink()
        result = self.verify(self.candidate, alias)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("same file", result.stderr)
        self.assertEqual(self.baseline.read_bytes(), self.original)
        snapshot = json.loads(self.candidate.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["format"], "mcp-shipcheck/v1")
        self.assertNotIn("compatible", snapshot)

    def test_compare_cannot_overwrite_either_input(self) -> None:
        self.candidate.write_bytes(self.original)
        for output in (self.baseline, self.candidate):
            with self.subTest(output=output.name):
                result = self.run_cli(
                    "compare", str(self.baseline), str(self.candidate), "--output", str(output)
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("same file", result.stderr)
                self.assertEqual(self.baseline.read_bytes(), self.original)
                self.assertEqual(self.candidate.read_bytes(), self.original)

    def test_compare_rejects_report_hard_linked_to_input(self) -> None:
        self.candidate.write_bytes(self.original)
        try:
            os.link(self.candidate, self.report)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        result = self.run_cli(
            "compare", str(self.baseline), str(self.candidate), "--output", str(self.report)
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("same file", result.stderr)
        self.assertEqual(self.candidate.read_bytes(), self.original)

    def test_invalid_baseline_does_not_start_server_or_replace_candidate(self) -> None:
        self.baseline.write_text("not a snapshot", encoding="utf-8")
        self.candidate.write_text("existing candidate", encoding="utf-8")
        result = self.verify(self.candidate)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.candidate.read_text(encoding="utf-8"), "existing candidate")
        self.assertFalse(self.method_log.exists())

    def test_missing_baseline_does_not_start_server_or_write_candidate(self) -> None:
        self.baseline.unlink()
        result = self.verify(self.candidate)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.candidate.exists())
        self.assertFalse(self.method_log.exists())

    def test_distinct_paths_preserve_baseline_and_report_breakage(self) -> None:
        result = self.verify(self.candidate, self.report)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.baseline.read_bytes(), self.original)
        self.assertEqual(json.loads(self.candidate.read_text())["format"], "mcp-shipcheck/v1")
        self.assertFalse(json.loads(self.report.read_text())["compatible"])
        self.assertTrue(self.method_log.exists())

    def test_compare_can_read_same_input_twice_with_distinct_report(self) -> None:
        result = self.run_cli(
            "compare", str(self.baseline), str(self.baseline), "--output", str(self.report)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(self.report.read_text())["compatible"])
        self.assertEqual(self.baseline.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
