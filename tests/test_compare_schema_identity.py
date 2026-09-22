from __future__ import annotations

from pathlib import Path
import sys
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.compare import compare_snapshots


def _compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    def snapshot(schema: dict[str, Any]) -> dict[str, Any]:
        return {"tools": [{"name": "run", "inputSchema": schema}]}

    return compare_snapshots(snapshot(old), snapshot(new))


class SchemaIdentityCompareTests(unittest.TestCase):
    def test_composition_distinguishes_boolean_and_number_literals(self) -> None:
        for composition in ("anyOf", "oneOf"):
            for constraint in ("const", "enum"):
                for old, new in ((True, 1), (1, True), (False, 0), (0, False)):
                    with self.subTest(composition=composition, constraint=constraint, old=old, new=new):
                        old_value = [old] if constraint == "enum" else old
                        new_value = [new] if constraint == "enum" else new
                        result = _compare(
                            {"properties": {"value": {composition: [{constraint: old_value}]}}},
                            {"properties": {"value": {composition: [{constraint: new_value}]}}},
                        )

                        self.assertFalse(result["compatible"])
                        self.assertEqual(len(result["changes"]), 1)
                        self.assertEqual(result["changes"][0]["severity"], "breaking")
                        self.assertEqual(
                            result["changes"][0]["path"],
                            f"tools.run.inputSchema.properties.value.{composition}",
                        )

    def test_additional_properties_distinguishes_boolean_and_number_literals(self) -> None:
        for constraint in ("const", "enum"):
            for old, new in ((True, 1), (1, True), (False, 0), (0, False)):
                with self.subTest(constraint=constraint, old=old, new=new):
                    old_value = [old] if constraint == "enum" else old
                    new_value = [new] if constraint == "enum" else new
                    result = _compare(
                        {"additionalProperties": {constraint: old_value}},
                        {"additionalProperties": {constraint: new_value}},
                    )

                    self.assertFalse(result["compatible"])
                    self.assertEqual(len(result["changes"]), 1)
                    self.assertEqual(result["changes"][0]["kind"], "additional-properties-changed")
                    self.assertEqual(result["changes"][0]["path"], "tools.run.inputSchema.additionalProperties")

    def test_nested_literal_values_are_distinguished(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                old_constraint = {"const": {"flags": [True, {"enabled": False}]}}
                new_constraint = {"const": {"flags": [1, {"enabled": 0}]}}
                old = [old_constraint] if keyword != "additionalProperties" else old_constraint
                new = [new_constraint] if keyword != "additionalProperties" else new_constraint

                self.assertFalse(_compare({keyword: old}, {keyword: new})["compatible"])

    def test_local_reference_and_nested_object_use_json_identity(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                old_constraint = {"const": True}
                new_constraint = {"const": 1}
                old = [old_constraint] if keyword != "additionalProperties" else old_constraint
                new = [new_constraint] if keyword != "additionalProperties" else new_constraint
                result = _compare(
                    {"properties": {"value": {"$ref": "#/$defs/Value"}}, "$defs": {"Value": {keyword: old}}},
                    {"properties": {"value": {"$ref": "#/$defs/Value"}}, "$defs": {"Value": {keyword: new}}},
                )

                self.assertFalse(result["compatible"])
                self.assertEqual(result["changes"][0]["path"], f"tools.run.inputSchema.properties.value.{keyword}")

    def test_equal_numbers_and_object_key_order_remain_compatible(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                old_constraint = {"const": {"count": 1, "flags": [False, 2]}}
                new_constraint = {"const": {"flags": [False, 2.0], "count": 1.0}}
                old = [old_constraint] if keyword != "additionalProperties" else old_constraint
                new = [new_constraint] if keyword != "additionalProperties" else new_constraint
                result = _compare({keyword: old}, {keyword: new})

                self.assertTrue(result["compatible"])
                self.assertEqual(result["changes"], [])

    def test_adding_anyof_branch_while_preserving_boolean_branch_is_compatible(self) -> None:
        result = _compare({"anyOf": [{"const": True}]}, {"anyOf": [{"const": True}, {"const": 1}]})

        self.assertTrue(result["compatible"])

    def test_reordering_boolean_and_number_oneof_branches_is_compatible(self) -> None:
        result = _compare(
            {"oneOf": [{"const": True}, {"const": 1}]},
            {"oneOf": [{"const": 1}, {"const": True}]},
        )

        self.assertTrue(result["compatible"])


if __name__ == "__main__":
    unittest.main()
