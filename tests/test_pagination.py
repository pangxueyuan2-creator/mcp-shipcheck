from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.probe import ProbeTimeout, ProtocolError, StartupError, probe_command


def tool(name: str) -> dict:
    return {"name": name, "inputSchema": {"type": "object"}}


class PaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pages = self.root / "pages.json"
        self.log = self.root / "requests.jsonl"
        self.command = [sys.executable, str(ROOT / "tests/fixtures/paginated_server.py"),
                        str(self.pages), str(self.log)]

    def configure(self, pages: list[dict]) -> None:
        self.pages.write_text(json.dumps(pages), encoding="utf-8")

    def requests(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_all_pages_empty_page_empty_cursor_and_notifications(self) -> None:
        self.configure([
            {"result": {"tools": [tool("z")], "nextCursor": ""}},
            {"result": {"tools": [], "nextCursor": "opaque/令牌?=+"}, "notification": True},
            {"result": {"tools": [tool("a")]}, "notification": True},
        ])
        snapshot = probe_command(self.command, timeout=2)
        self.assertEqual([t["name"] for t in snapshot["tools"]], ["a", "z"])
        requests = self.requests()
        self.assertEqual([r["method"] for r in requests],
                         ["initialize", "notifications/initialized"] + ["tools/list"] * 3)
        self.assertEqual(requests[3]["params"], {"cursor": ""})
        self.assertEqual(requests[4]["params"], {"cursor": "opaque/令牌?=+"})
        self.assertNotIn("opaque", json.dumps(snapshot))
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)

    def test_duplicate_names_across_pages_fail(self) -> None:
        self.configure([{"result": {"tools": [tool("same")], "nextCursor": "x"}},
                        {"result": {"tools": [tool("same")]}}])
        with self.assertRaisesRegex(ProtocolError, "duplicate"):
            probe_command(self.command)

    def test_cursor_cycles_fail(self) -> None:
        for cursors in (["x", "x"], ["", "middle", ""]):
            with self.subTest(cursors=cursors):
                self.configure([{"result": {"tools": [], "nextCursor": c}} for c in cursors])
                with self.assertRaisesRegex(ProtocolError, "repeated"):
                    probe_command(self.command)

    def test_invalid_cursor_types_fail(self) -> None:
        for cursor in (None, 0, False, [], {}):
            with self.subTest(cursor=cursor):
                self.configure([{"result": {"tools": [], "nextCursor": cursor}}])
                with self.assertRaisesRegex(ProtocolError, "nextCursor must be a string"):
                    probe_command(self.command)

    def test_invalid_later_pages_fail(self) -> None:
        for result in ({}, {"tools": {}}, {"tools": [None]}, {"tools": [{"name": ""}]}):
            with self.subTest(result=result):
                self.configure([{"result": {"tools": [], "nextCursor": "x"}}, {"result": result}])
                with self.assertRaises(ProtocolError):
                    probe_command(self.command)

    def test_page_limit_and_exact_boundary(self) -> None:
        with patch("mcp_shipcheck.probe.MAX_TOOL_PAGES", 2):
            self.configure([{"result": {"tools": [], "nextCursor": "x"}},
                            {"result": {"tools": []}}])
            self.assertEqual(probe_command(self.command)["tools"], [])
            self.configure([{"result": {"tools": [], "nextCursor": "x"}},
                            {"result": {"tools": [], "nextCursor": "y"}}])
            with self.assertRaisesRegex(ProtocolError, "page count"):
                probe_command(self.command)

    def test_tool_count_limit_is_cumulative(self) -> None:
        with patch("mcp_shipcheck.probe.MAX_TOOLS", 2):
            self.configure([{"result": {"tools": [tool("a")], "nextCursor": "x"}},
                            {"result": {"tools": [tool("b")]}}])
            self.assertEqual(len(probe_command(self.command)["tools"]), 2)
            self.configure([{"result": {"tools": [tool("a")], "nextCursor": "x"}},
                            {"result": {"tools": [tool("b"), tool("c")]}}])
            with self.assertRaisesRegex(ProtocolError, "tool count"):
                probe_command(self.command)

    def test_byte_limit_is_cumulative(self) -> None:
        results = [{"tools": [tool("a")], "nextCursor": "x"}, {"tools": [tool("b")]}]
        size = sum(len(json.dumps(r, ensure_ascii=True).encode("utf-8")) for r in results)
        self.configure([{"result": r} for r in results])
        with patch("mcp_shipcheck.probe.MAX_TOOL_RESULT_BYTES", size):
            self.assertEqual(len(probe_command(self.command)["tools"]), 2)
        with patch("mcp_shipcheck.probe.MAX_TOOL_RESULT_BYTES", size - 1):
            with self.assertRaisesRegex(ProtocolError, "byte limit"):
                probe_command(self.command)

    def test_timeout_is_shared_by_all_pages(self) -> None:
        self.configure([{"result": {"tools": [], "nextCursor": str(i)}, "delay": 0.10}
                        for i in range(10)])
        with self.assertRaises(ProbeTimeout):
            probe_command(self.command, timeout=0.5)
        self.assertLess(len(self.requests()), 12)

    def test_invalid_timeout_fails_before_starting_process(self) -> None:
        for timeout in (0, -1, float("nan"), float("inf"), True, "5"):
            with self.subTest(timeout=timeout), patch("mcp_shipcheck.probe.subprocess.Popen") as popen:
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    probe_command(self.command, timeout=timeout)
                popen.assert_not_called()

    def test_server_not_reading_large_cursor_request_is_bounded(self) -> None:
        self.configure([{"result": {"tools": [], "nextCursor": "x" * 131072},
                         "after_response_delay": 30}])
        started = time.monotonic()
        with self.assertRaises(ProbeTimeout):
            probe_command(self.command, timeout=0.5)
        self.assertLess(time.monotonic() - started, 5)

    def test_later_page_exit_fails(self) -> None:
        self.configure([{"result": {"tools": [], "nextCursor": "x"}}, {"exit": True}])
        with self.assertRaises(StartupError):
            probe_command(self.command)

    def cli(self, output: Path, *args: str) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run([sys.executable, "-m", "mcp_shipcheck", "verify", "--output",
                               str(output), *args, "--", *self.command],
                              capture_output=True, text=True, env=environment, timeout=15)

    def test_cli_detects_removed_tool_on_later_page(self) -> None:
        baseline = self.root / "baseline.json"
        candidate = self.root / "candidate.json"
        comparison = self.root / "compare.json"
        self.configure([{"result": {"tools": [tool("first")], "nextCursor": "x"}},
                        {"result": {"tools": [tool("later")]}}])
        result = self.cli(baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.configure([{"result": {"tools": [tool("first")], "nextCursor": "x"}},
                        {"result": {"tools": []}}])
        result = self.cli(candidate, "--baseline", str(baseline), "--compare-output", str(comparison))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(json.loads(comparison.read_text())["compatible"])
        self.assertIn("later", comparison.read_text())

    def test_cli_later_page_failure_does_not_publish_or_leak(self) -> None:
        for failure in ({"error": "private-cursor-sentinel"}, {"raw": "private-cursor-sentinel"}):
            with self.subTest(failure=failure):
                self.configure([{"result": {"tools": [tool("first")], "nextCursor": "x"}}, failure])
                output = self.root / "incomplete.json"
                result = self.cli(output)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(output.exists())
                self.assertNotIn("private-cursor-sentinel", result.stdout + result.stderr)
                output.write_text("previous trusted snapshot", encoding="utf-8")
                result = self.cli(output)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(output.read_text(), "previous trusted snapshot")
                output.unlink()


if __name__ == "__main__":
    unittest.main()
