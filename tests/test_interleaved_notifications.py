from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.probe import probe_command

FIXTURE = ROOT / "demo" / "fixture_server.py"


class InterleavedNotificationTests(unittest.TestCase):
    def test_probe_ignores_notifications_while_waiting_for_responses(self) -> None:
        snapshot = probe_command(
            [sys.executable, str(FIXTURE), "--mode", "interleaved-notification"],
            timeout=1,
        )

        self.assertEqual(snapshot["protocolVersion"], "2024-11-05")
        self.assertEqual(
            [tool["name"] for tool in snapshot["tools"]],
            ["read_note", "search_notes"],
        )
        self.assertEqual(snapshot["probe"]["toolCallsExecuted"], 0)


if __name__ == "__main__":
    unittest.main()
