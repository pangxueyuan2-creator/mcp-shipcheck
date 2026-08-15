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
from mcp_shipcheck.probe import ProbeTimeout, ProtocolError, probe_command

FIXTURE = ROOT / "demo" / "fixture_server.py"


def command(mode: str) -> list[str]:
    return [sys.executable, str(FIXTURE), "--mode", mode]


class ProbeTests(unittest.TestCase):
    def test_probe_collects_tool_surface_without_calling_tools(self) -> None:
        snapshot = probe_command(command("baseline"), timeout=1)
        self.assertEqual(snapshot["format"], "mcp-shipcheck/v1")
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)
        self.assertEqual([tool["name"] for tool in snapshot["tools"]], ["read_note", "search_notes"])
        self.assertEqual(snapshot["tools"][0]["inputSchema"]["required"], ["path"])

    def test_probe_rejects_non_json_stdout(self) -> None:
        with self.assertRaises(ProtocolError):
            probe_command(command("noise"), timeout=1)

    def test_probe_times_out(self) -> None:
        with self.assertRaises(ProbeTimeout):
            probe_command(command("silent"), timeout=0.05)


class CompareTests(unittest.TestCase):
    def test_added_tool_is_compatible(self) -> None:
        result = compare_snapshots(probe_command(command("baseline")), probe_command(command("compatible")))
        self.assertTrue(result["compatible"])
        self.assertEqual(result["summary"], {"breaking": 0, "nonBreaking": 1, "total": 1})
        self.assertEqual(result["changes"][0]["kind"], "tool-added")

    def test_removed_tool_and_required_input_are_breaking(self) -> None:
        result = compare_snapshots(probe_command(command("baseline")), probe_command(command("breaking")))
        self.assertFalse(result["compatible"])
        kinds = {change["kind"] for change in result["changes"]}
        self.assertIn("tool-removed", kinds)
        self.assertIn("required-added", kinds)
        self.assertNotIn("input-added", kinds)

    def test_description_only_change_is_compatible(self) -> None:
        baseline = {"format": "mcp-shipcheck/v1", "protocolVersion": "2024-11-05", "capabilities": {}, "tools": [{"name": "read", "description": "old", "inputSchema": {"type": "object", "properties": {}}}]}
        candidate = {"format": "mcp-shipcheck/v1", "protocolVersion": "2024-11-05", "capabilities": {}, "tools": [{"name": "read", "description": "new", "inputSchema": {"type": "object", "properties": {}}}]}
        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run([sys.executable, "-m", "mcp_shipcheck", *args], cwd=ROOT, env=environment, text=True, capture_output=True, check=False)

    def test_verify_writes_snapshot_and_compare_returns_two_for_breakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.json"
            candidate = Path(directory) / "candidate.json"
            result = self.run_cli("verify", "--output", str(baseline), "--", *command("baseline"))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(baseline.exists())
            self.assertEqual(json.loads(baseline.read_text())["format"], "mcp-shipcheck/v1")
            result = self.run_cli("verify", "--baseline", str(baseline), "--output", str(candidate), "--", *command("breaking"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("breaking change", result.stderr)
