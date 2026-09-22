from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.compare import compare_snapshots
from mcp_shipcheck.probe import ProtocolError, probe_command


def _tool(name: str = "run") -> dict:
    return {"name": name, "inputSchema": {"type": "object"}}


def _snapshot(tools: list) -> dict:
    return {"format": "mcp-shipcheck/v1", "tools": tools}


class CompareCatalogValidationTests(unittest.TestCase):
    def test_invalid_catalogs_are_rejected_on_either_side(self) -> None:
        cases = [
            ("missing tools", {}, "tools"),
            ("null tools", {"tools": None}, "tools"),
            ("object tools", {"tools": {}}, "tools"),
            ("string tools", {"tools": "private-invalid-catalog"}, "tools"),
            ("null tool", {"tools": [None]}, "tools"),
            ("array tool", {"tools": [[]]}, "tools"),
            ("string tool", {"tools": ["private-invalid-catalog"]}, "tools"),
            ("missing name", {"tools": [{"inputSchema": {}}]}, "name"),
            ("empty name", {"tools": [_tool("")]}, "name"),
            ("blank name", {"tools": [_tool(" \t")]}, "name"),
            ("number name", {"tools": [_tool(123)]}, "name"),
            ("missing schema", {"tools": [{"name": "run"}]}, "inputSchema"),
        ]
        for schema in (None, False, True, 0, [], "private-invalid-catalog"):
            cases.append((f"schema {schema!r}", {"tools": [{"name": "run", "inputSchema": schema}]}, "inputSchema"))
        for label, invalid, message in cases:
            for side in ("baseline", "candidate"):
                with self.subTest(case=label, side=side):
                    old, new = (invalid, {"tools": []}) if side == "baseline" else ({"tools": []}, invalid)
                    with self.assertRaisesRegex(ValueError, message) as error:
                        compare_snapshots(old, new)
                    self.assertIn(side, str(error.exception))
                    self.assertNotIn("private-invalid-catalog", str(error.exception))

    def test_duplicate_names_cannot_shadow_a_breaking_tool(self) -> None:
        original = _tool()
        restricted = {"name": "run", "inputSchema": {"type": "object", "required": ["password"]}}
        for tools in ([restricted, original], [original, restricted]):
            for side in ("baseline", "candidate"):
                with self.subTest(tools=tools, side=side):
                    invalid, valid = {"tools": tools}, {"tools": [original]}
                    with self.assertRaisesRegex(ValueError, "duplicate"):
                        compare_snapshots(invalid, valid) if side == "baseline" else compare_snapshots(valid, invalid)

    def test_legacy_invalid_schema_marker_requires_a_new_snapshot(self) -> None:
        invalid = {"tools": [{"name": "run", "inputSchema": {"_invalidInputSchema": True}}]}
        for side in ("baseline", "candidate"):
            with self.subTest(side=side):
                old, new = (invalid, {"tools": []}) if side == "baseline" else ({"tools": []}, invalid)
                with self.assertRaisesRegex(ValueError, "_invalidInputSchema") as error:
                    compare_snapshots(old, new)
                self.assertIn("regenerate", str(error.exception))
                self.assertIn("baseline", str(error.exception))

    def test_minimal_valid_snapshots_and_opaque_schema_keywords_still_work(self) -> None:
        tools = [
            _tool("读取笔记"),
            {"name": "empty", "inputSchema": {}},
            {"name": "custom", "inputSchema": {"vendorKeyword": {"mode": "custom"}}},
            {"name": "field", "inputSchema": {"properties": {"_invalidInputSchema": {"type": "boolean"}}}},
        ]
        self.assertTrue(compare_snapshots({"tools": []}, {"tools": []})["compatible"])
        result = compare_snapshots({"tools": tools}, {"tools": list(reversed(tools))})
        self.assertTrue(result["compatible"])
        self.assertEqual(result["changes"], [])


class CatalogBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pages = self.root / "pages.json"
        self.log = self.root / "requests.jsonl"
        self.command = [sys.executable, str(ROOT / "tests/fixtures/paginated_server.py"), str(self.pages), str(self.log)]

    def configure(self, invalid_tool: dict, *, later_page: bool = False) -> None:
        pages = [{"result": {"tools": [invalid_tool]}}]
        if later_page:
            pages.insert(0, {"result": {"tools": [_tool("valid-first-page")], "nextCursor": "next"}})
        self.pages.write_text(json.dumps(pages), encoding="utf-8")

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "mcp_shipcheck", *args],
            capture_output=True, text=True, env=environment, timeout=15,
        )

    def test_real_probe_rejects_non_object_and_missing_schemas(self) -> None:
        invalid_tools = [{"name": "run"}] + [
            {"name": "run", "inputSchema": schema}
            for schema in (None, False, True, 0, [], "private-invalid-schema")
        ]
        for invalid in invalid_tools:
            with self.subTest(tool=invalid):
                self.configure(invalid)
                with self.assertRaisesRegex(ProtocolError, "inputSchema") as error:
                    probe_command(self.command, timeout=2)
                self.assertNotIn("private-invalid-schema", str(error.exception))

    def test_real_probe_rejects_reserved_legacy_marker(self) -> None:
        self.configure({"name": "run", "inputSchema": {"_invalidInputSchema": True}})
        with self.assertRaisesRegex(ProtocolError, "_invalidInputSchema"):
            probe_command(self.command, timeout=2)

    def test_verify_schema_failure_preserves_outputs_and_never_calls_tools(self) -> None:
        baseline = self.root / "baseline.json"
        output = self.root / "candidate.json"
        report = self.root / "report.json"
        baseline.write_text(json.dumps(_snapshot([_tool()])), encoding="utf-8")
        for later_page in (False, True):
            for existing in (False, True):
                with self.subTest(later_page=later_page, existing=existing):
                    self.configure({"name": "run", "inputSchema": "private-invalid-schema"}, later_page=later_page)
                    for path in (output, report):
                        if existing:
                            path.write_text("existing output", encoding="utf-8")
                        elif path.exists():
                            path.unlink()
                    result = self.cli(
                        "verify", "--baseline", str(baseline), "--output", str(output),
                        "--compare-output", str(report), "--", *self.command,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("inputSchema", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn("private-invalid-schema", result.stdout + result.stderr)
                    for path in (output, report):
                        if existing:
                            self.assertEqual(path.read_text(encoding="utf-8"), "existing output")
                        else:
                            self.assertFalse(path.exists())
                    methods = [json.loads(line)["method"] for line in self.log.read_text(encoding="utf-8").splitlines()]
                    self.assertTrue(set(methods) <= {"initialize", "notifications/initialized", "tools/list"})

    def test_compare_cli_rejects_bad_catalogs_without_writing_report(self) -> None:
        baseline = self.root / "baseline.json"
        candidate = self.root / "candidate.json"
        report = self.root / "report.json"
        invalid_snapshots = [
            {"format": "mcp-shipcheck/v1", "tools": None},
            _snapshot([_tool(), _tool()]),
            _snapshot([{"name": "run", "inputSchema": "private-invalid-schema"}]),
            _snapshot([{"name": "run", "inputSchema": {"_invalidInputSchema": True}}]),
        ]
        for invalid in invalid_snapshots:
            for side in ("baseline", "candidate"):
                with self.subTest(invalid=invalid, side=side):
                    old, new = (invalid, _snapshot([])) if side == "baseline" else (_snapshot([]), invalid)
                    baseline.write_text(json.dumps(old), encoding="utf-8")
                    candidate.write_text(json.dumps(new), encoding="utf-8")
                    report.write_text("existing report", encoding="utf-8")
                    result = self.cli("compare", str(baseline), str(candidate), "--output", str(report))
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn("private-invalid-schema", result.stdout + result.stderr)
                    self.assertEqual(report.read_text(encoding="utf-8"), "existing report")
                    self.assertNotIn('"compatible": true', result.stdout)


if __name__ == "__main__":
    unittest.main()
