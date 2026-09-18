from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.compare import compare_snapshots


class CompositionConstraintCompareTests(unittest.TestCase):
    def _snapshot(self, schema: dict) -> dict:
        return {
            "format": "mcp-shipcheck/v1",
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "tools": [{"name": "run", "inputSchema": schema}],
        }

    def test_new_root_anyof_is_breaking(self) -> None:
        baseline = self._snapshot({"type": "object"})
        candidate = self._snapshot(
            {
                "type": "object",
                "anyOf": [
                    {"required": ["path"]},
                    {"required": ["url"]},
                ],
            }
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn(
            "tools.run.inputSchema.anyOf",
            {change["path"] for change in result["changes"]},
        )

    def test_anyof_branch_removal_is_breaking(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "integer"},
                        ]
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                        ]
                    }
                },
            }
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn(
            "tools.run.inputSchema.properties.target.anyOf",
            {change["path"] for change in result["changes"]},
        )

    def test_anyof_branch_addition_is_compatible(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                        ]
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [
                            {"type": "integer"},
                            {"type": "string"},
                        ]
                    }
                },
            }
        )

        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])

    def test_anyof_reordering_is_compatible(self) -> None:
        left = {"type": "string", "minLength": 1}
        right = {"type": "integer", "minimum": 0}
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {"anyOf": [left, right]}},
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {"anyOf": [right, left]}},
            }
        )

        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])

    def test_oneof_reordering_is_compatible(self) -> None:
        left = {"type": "string", "pattern": "^a"}
        right = {"type": "integer", "minimum": 0}
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {"oneOf": [left, right]}},
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {"oneOf": [right, left]}},
            }
        )

        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])

    def test_oneof_branch_addition_fails_closed(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {"type": "number"},
                        ]
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {"type": "number"},
                            {"type": "integer"},
                        ]
                    }
                },
            }
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn(
            "tools.run.inputSchema.properties.target.oneOf",
            {change["path"] for change in result["changes"]},
        )

    def test_oneof_branch_removal_fails_closed(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "integer"},
                        ]
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {"type": "string"},
                        ]
                    }
                },
            }
        )

        self.assertFalse(compare_snapshots(baseline, candidate)["compatible"])

    def test_composition_inside_local_def_is_checked(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {"$ref": "#/$defs/target"}},
                "$defs": {
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "integer"},
                        ]
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {"$ref": "#/$defs/target"}},
                "$defs": {
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                        ]
                    }
                },
            }
        )

        self.assertFalse(compare_snapshots(baseline, candidate)["compatible"])

    def test_removing_composition_constraint_is_compatible(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "integer"},
                        ]
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"target": {}},
            }
        )

        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])


if __name__ == "__main__":
    unittest.main()
