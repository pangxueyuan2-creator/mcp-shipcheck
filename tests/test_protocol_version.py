from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.probe import ProtocolError, probe_command

FIXTURE = ROOT / "demo" / "fixture_server.py"


def command(mode: str) -> list[str]:
    return [sys.executable, str(FIXTURE), "--mode", mode]


class ProtocolVersionTests(unittest.TestCase):
    def test_probe_rejects_unsupported_protocol_version(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            probe_command(command("wrong-protocol"), timeout=1)
        self.assertIn("unsupported initialize protocolVersion", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
