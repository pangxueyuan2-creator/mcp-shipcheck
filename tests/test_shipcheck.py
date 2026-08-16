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
from mcp_shipcheck.probe import ProbeTimeout, ProtocolError, StartupError, probe_command

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

    def test_probe_rejects_early_exit(self) -> None:
        with self.assertRaises(StartupError):
            probe_command(command("early-exit"), timeout=1)

    def test_probe_rejects_malformed_json(self) -> None:
        with self.assertRaises(ProtocolError):
            probe_command(command("malformed"), timeout=1)

    def test_probe_rejects_wrong_jsonrpc_id(self) -> None:
        with self.assertRaises(ProtocolError):
            probe_command(command("wrong-id"), timeout=1)

    def test_probe_records_unusual_protocol_version(self) -> None:
        snapshot = probe_command(command("wrong-protocol"), timeout=1)
        self.assertEqual(snapshot["protocolVersion"], "99.99.99")
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)

    def test_probe_rejects_missing_tools_array(self) -> None:
        with self.assertRaises(ProtocolError):
            probe_command(command("missing-tools"), timeout=1)

    def test_probe_rejects_duplicate_tool_names(self) -> None:
        with self.assertRaises(ProtocolError):
            probe_command(command("duplicate-names"), timeout=1)

    def test_probe_accepts_unicode_tool_name(self) -> None:
        snapshot = probe_command(command("unicode-name"), timeout=1)
        self.assertEqual([tool["name"] for tool in snapshot["tools"]], ["读取笔记"])

    def test_probe_accepts_large_input_schema(self) -> None:
        snapshot = probe_command(command("large-schema"), timeout=1)
        self.assertEqual(len(snapshot["tools"][0]["inputSchema"]["properties"]), 200)

    def test_probe_ignores_stderr_startup_noise(self) -> None:
        snapshot = probe_command(command("stderr-noise"), timeout=1)
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)
        self.assertEqual([tool["name"] for tool in snapshot["tools"]], ["read_note", "search_notes"])

    def test_probe_never_sends_tools_call(self) -> None:
        snapshot = probe_command(command("call-trap"), timeout=1)
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "methods.log"
            environment = os.environ.copy()
            environment["MCP_SHIPCHECK_METHOD_LOG"] = str(log_path)
            environment["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mcp_shipcheck",
                    "verify",
                    "--output",
                    str(Path(directory) / "snap.json"),
                    "--",
                    *command("call-trap"),
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            methods = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/list"])
            self.assertNotIn("tools/call", methods)

    def test_probe_sends_initialized_before_tools_list(self) -> None:
        snapshot = probe_command(command("require-initialized"), timeout=1)
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)
        self.assertEqual([tool["name"] for tool in snapshot["tools"]], ["read_note", "search_notes"])

    def test_probe_does_not_surface_stderr_secrets(self) -> None:
        with self.assertRaises(StartupError) as ctx:
            probe_command(command("secret-stderr"), timeout=1)
        self.assertNotIn("shipcheck-redteam-secret", str(ctx.exception))
        self.assertNotIn("API_TOKEN", str(ctx.exception))
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mcp_shipcheck",
                    "verify",
                    "--output",
                    str(Path(directory) / "snap.json"),
                    "--",
                    *command("secret-stderr"),
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("shipcheck-redteam-secret", result.stdout)
        self.assertNotIn("shipcheck-redteam-secret", result.stderr)
        self.assertNotIn("API_TOKEN", result.stdout)
        self.assertNotIn("API_TOKEN", result.stderr)

    def test_probe_rejects_oversized_jsonrpc_line(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            probe_command(command("huge-line"), timeout=2)
        self.assertIn("exceeds", str(ctx.exception))
        self.assertLess(len(str(ctx.exception)), 500)

    def test_probe_rejects_non_utf8_stdout(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            probe_command(command("non-utf8"), timeout=1)
        self.assertIn("non-UTF-8", str(ctx.exception))

    def test_probe_rejects_non_string_tool_name(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            probe_command(command("int-name"), timeout=1)
        self.assertIn("non-empty string name", str(ctx.exception))


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

    def _snapshot(self, properties: dict) -> dict:
        return {
            "format": "mcp-shipcheck/v1",
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "tools": [
                {"name": "run", "inputSchema": {"type": "object", "properties": properties}}
            ],
        }

    def test_new_const_on_existing_input_is_breaking(self) -> None:
        baseline = self._snapshot({"mode": {"type": "string"}})
        candidate = self._snapshot({"mode": {"type": "string", "const": "safe"}})
        result = compare_snapshots(baseline, candidate)
        self.assertFalse(result["compatible"])
        self.assertIn("input-restricted", {change["kind"] for change in result["changes"]})

    def test_new_type_or_enum_constraints_are_breaking(self) -> None:
        baseline = self._snapshot({"mode": {}, "flavor": {}})
        candidate = self._snapshot({"mode": {"type": "string"}, "flavor": {"enum": ["a", "b"]}})
        result = compare_snapshots(baseline, candidate)
        self.assertFalse(result["compatible"])
        self.assertEqual(
            sum(change["kind"] == "input-restricted" for change in result["changes"]), 2
        )

    def test_removing_a_type_constraint_is_compatible(self) -> None:
        baseline = self._snapshot({"mode": {"type": "string"}})
        candidate = self._snapshot({"mode": {}})
        result = compare_snapshots(baseline, candidate)
        self.assertTrue(result["compatible"])
        self.assertNotIn("input-restricted", {change["kind"] for change in result["changes"]})


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
