from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.compare import compare_snapshots


class NestedConstraintCompareTests(unittest.TestCase):
    def _snapshot(self, schema: dict) -> dict:
        return {
            "format": "mcp-shipcheck/v1",
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "tools": [{"name": "run", "inputSchema": schema}],
        }

    def test_nested_object_enum_narrowing_is_breaking(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "cfg": {
                        "type": "object",
                        "properties": {
                            "level": {"type": "string", "enum": ["a", "b", "c"]}
                        },
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "cfg": {
                        "type": "object",
                        "properties": {"level": {"type": "string", "enum": ["a"]}},
                    }
                },
            }
        )
        result = compare_snapshots(baseline, candidate)
        self.assertFalse(result["compatible"])
        self.assertIn("enum-narrowed", {change["kind"] for change in result["changes"]})

    def test_nested_required_addition_is_breaking(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "cfg": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "cfg": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    }
                },
            }
        )
        result = compare_snapshots(baseline, candidate)
        self.assertFalse(result["compatible"])
        self.assertIn("required-added", {change["kind"] for change in result["changes"]})

    def test_local_defs_enum_narrowing_is_breaking(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {"mode": {"$ref": "#/$defs/mode"}},
                "$defs": {"mode": {"type": "string", "enum": ["safe", "fast"]}},
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"mode": {"$ref": "#/$defs/mode"}},
                "$defs": {"mode": {"type": "string", "enum": ["safe"]}},
            }
        )
        result = compare_snapshots(baseline, candidate)
        self.assertFalse(result["compatible"])
        self.assertIn("enum-narrowed", {change["kind"] for change in result["changes"]})

    def test_new_pattern_and_min_length_are_breaking(self) -> None:
        baseline = self._snapshot(
            {"type": "object", "properties": {"mode": {"type": "string"}}}
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "pattern": "^[a-z]+$",
                        "minLength": 4,
                    }
                },
            }
        )
        result = compare_snapshots(baseline, candidate)
        self.assertFalse(result["compatible"])
        self.assertGreaterEqual(
            sum(change["kind"] == "input-restricted" for change in result["changes"]),
            2,
        )

    def test_relaxation_and_property_order_remain_compatible(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "cfg": {
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string", "enum": ["safe"]},
                            "count": {"type": "integer"},
                        },
                    }
                },
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {
                    "cfg": {
                        "type": "object",
                        "properties": {
                            "count": {"type": "integer"},
                            "mode": {"type": "string", "enum": ["safe", "fast"]},
                        },
                    }
                },
            }
        )
        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])

    def test_self_referential_defs_terminate(self) -> None:
        schema = {
            "type": "object",
            "properties": {"node": {"$ref": "#/$defs/node"}},
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/$defs/node"}},
                }
            },
        }
        result = compare_snapshots(self._snapshot(schema), self._snapshot(schema))
        self.assertTrue(result["compatible"])


if __name__ == "__main__":
    unittest.main()
