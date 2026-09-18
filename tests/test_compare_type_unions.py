from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.compare import compare_snapshots


class TypeUnionCompareTests(unittest.TestCase):
    def _snapshot(self, schema: dict) -> dict:
        return {
            "format": "mcp-shipcheck/v1",
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "tools": [{"name": "run", "inputSchema": schema}],
        }

    def test_nullable_widening_is_non_breaking(self) -> None:
        baseline = self._snapshot(
            {"type": "object", "properties": {"name": {"type": "string"}}}
        )
        candidate = self._snapshot(
            {"type": "object", "properties": {"name": {"type": ["string", "null"]}}}
        )

        result = compare_snapshots(baseline, candidate)

        self.assertTrue(result["compatible"])
        widened = [change for change in result["changes"] if change["kind"] == "input-type-widened"]
        self.assertEqual(1, len(widened))
        self.assertEqual("tools.run.inputSchema.properties.name", widened[0]["path"])
        self.assertEqual("non-breaking", widened[0]["severity"])

    def test_nullable_narrowing_is_breaking(self) -> None:
        baseline = self._snapshot(
            {"type": "object", "properties": {"name": {"type": ["string", "null"]}}}
        )
        candidate = self._snapshot(
            {"type": "object", "properties": {"name": {"type": "string"}}}
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn("input-type-changed", {change["kind"] for change in result["changes"]})

    def test_type_union_reordering_is_compatible_and_silent(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {"value": {"type": ["string", "integer", "null"]}},
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"value": {"type": ["null", "string", "integer"]}},
            }
        )

        result = compare_snapshots(baseline, candidate)

        self.assertTrue(result["compatible"])
        self.assertEqual([], result["changes"])

    def test_root_type_narrowing_is_breaking(self) -> None:
        baseline = self._snapshot({"type": ["object", "null"], "properties": {}})
        candidate = self._snapshot({"type": "object", "properties": {}})

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        change = next(change for change in result["changes"] if change["kind"] == "input-type-changed")
        self.assertEqual("tools.run.inputSchema", change["path"])

    def test_root_type_widening_is_non_breaking(self) -> None:
        baseline = self._snapshot({"type": "object", "properties": {}})
        candidate = self._snapshot({"type": ["object", "null"], "properties": {}})

        result = compare_snapshots(baseline, candidate)

        self.assertTrue(result["compatible"])
        self.assertEqual("input-type-widened", result["changes"][0]["kind"])

    def test_local_defs_type_narrowing_is_breaking(self) -> None:
        baseline = self._snapshot(
            {
                "type": "object",
                "properties": {"value": {"$ref": "#/$defs/value"}},
                "$defs": {"value": {"type": ["string", "integer"]}},
            }
        )
        candidate = self._snapshot(
            {
                "type": "object",
                "properties": {"value": {"$ref": "#/$defs/value"}},
                "$defs": {"value": {"type": "string"}},
            }
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn("input-type-changed", {change["kind"] for change in result["changes"]})

    def test_gaining_a_type_constraint_remains_breaking(self) -> None:
        baseline = self._snapshot({"type": "object", "properties": {"value": {}}})
        candidate = self._snapshot(
            {"type": "object", "properties": {"value": {"type": ["string", "null"]}}}
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn("input-restricted", {change["kind"] for change in result["changes"]})

    def test_removing_a_type_constraint_is_compatible(self) -> None:
        baseline = self._snapshot(
            {"type": "object", "properties": {"value": {"type": ["string", "null"]}}}
        )
        candidate = self._snapshot({"type": "object", "properties": {"value": {}}})

        self.assertTrue(compare_snapshots(baseline, candidate)["compatible"])

    def test_malformed_type_change_fails_closed(self) -> None:
        baseline = self._snapshot(
            {"type": "object", "properties": {"value": {"type": ["string", 1]}}}
        )
        candidate = self._snapshot(
            {"type": "object", "properties": {"value": {"type": ["string", "null"]}}}
        )

        result = compare_snapshots(baseline, candidate)

        self.assertFalse(result["compatible"])
        self.assertIn("input-type-changed", {change["kind"] for change in result["changes"]})


if __name__ == "__main__":
    unittest.main()
