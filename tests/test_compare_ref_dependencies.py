from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_shipcheck.compare import compare_snapshots
from mcp_shipcheck import compare as compare_module


class ReferenceDependencyCompareTests(unittest.TestCase):
    def compare(self, old: dict, new: dict) -> dict:
        def snapshot(schema: dict) -> dict:
            return {"format": "mcp-shipcheck/v1", "protocolVersion": "2024-11-05",
                    "capabilities": {}, "tools": [{"name": "run", "inputSchema": schema}]}
        return compare_snapshots(snapshot(old), snapshot(new))

    def schema(self, keyword: str, values: list) -> dict:
        value = {"$ref": "#/$defs/mode"}
        if keyword != "additionalProperties":
            value = [value, {"type": "null"}]
        result = {"type": "object", "$defs": {"mode": {"enum": values}}}
        if keyword == "additionalProperties":
            result[keyword] = value
        else:
            result["properties"] = {"mode": {keyword: value}}
        return result

    def location(self, schema: dict) -> dict:
        return schema["properties"]["mode"]

    def test_unchanged_ref_target_narrowing_is_breaking(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                result = self.compare(self.schema(keyword, ["fast", "safe"]), self.schema(keyword, ["safe"]))
                self.assertFalse(result["compatible"])
                prefix = "tools.run.inputSchema" + ("" if keyword == "additionalProperties" else ".properties.mode")
                self.assertIn(f"{prefix}.{keyword}", {change["path"] for change in result["changes"]})

    def test_oneof_target_widening_can_create_overlap(self) -> None:
        old = self.schema("oneOf", ["fast"])
        self.location(old)["oneOf"][1] = {"const": "safe"}
        new = copy.deepcopy(old)
        new["$defs"]["mode"]["enum"].append("safe")
        self.assertFalse(self.compare(old, new)["compatible"])

    def test_ref_target_boolean_and_number_are_distinct(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                self.assertFalse(self.compare(self.schema(keyword, [True]), self.schema(keyword, [1]))["compatible"])

    def test_equal_numeric_targets_remain_compatible(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                self.assertTrue(self.compare(self.schema(keyword, [1]), self.schema(keyword, [1.0]))["compatible"])

    def test_unused_definitions_do_not_change_identity(self) -> None:
        for keyword in ("anyOf", "oneOf", "additionalProperties"):
            with self.subTest(keyword=keyword):
                old = self.schema(keyword, ["fast"])
                new = copy.deepcopy(old)
                new["$defs"]["unused"] = {"const": False}
                self.assertTrue(self.compare(old, new)["compatible"])

    def test_reordering_and_anyof_ref_addition_remain_compatible(self) -> None:
        for keyword in ("anyOf", "oneOf"):
            old = self.schema(keyword, ["fast"])
            new = copy.deepcopy(old)
            self.location(new)[keyword].reverse()
            self.assertTrue(self.compare(old, new)["compatible"])
        self.location(new)["anyOf"] = self.location(new).pop("oneOf")
        self.location(old)["anyOf"] = self.location(old).pop("oneOf")
        self.location(new)["anyOf"].append({"$ref": "#/$defs/extra"})
        new["$defs"]["extra"] = {"type": "integer"}
        self.assertTrue(self.compare(old, new)["compatible"])

    def test_refs_in_nested_schema_positions_are_tracked(self) -> None:
        for inner in ({"properties": {"mode": {"$ref": "#/$defs/mode"}}},
                      {"anyOf": [{"$ref": "#/$defs/mode"}]},
                      {"additionalProperties": {"$ref": "#/$defs/mode"}}):
            with self.subTest(inner=inner):
                old = self.schema("anyOf", ["fast", "safe"])
                self.location(old)["anyOf"] = [inner]
                new = copy.deepcopy(old)
                new["$defs"]["mode"]["enum"] = ["safe"]
                self.assertFalse(self.compare(old, new)["compatible"])

    def test_chains_and_cycles_track_each_reachable_target(self) -> None:
        old = self.schema("anyOf", ["fast", "safe"])
        old["$defs"]["mode"] = {"properties": {"next": {"$ref": "#/$defs/next"}}}
        old["$defs"]["next"] = {"enum": ["fast", "safe"], "properties": {"back": {"$ref": "#/$defs/mode"}}}
        self.assertTrue(self.compare(old, copy.deepcopy(old))["compatible"])
        new = copy.deepcopy(old)
        new["$defs"]["next"]["enum"] = ["safe"]
        self.assertFalse(self.compare(old, new)["compatible"])

    def test_reference_shaped_literal_data_is_not_traversed(self) -> None:
        for keyword in ("const", "enum", "default", "examples"):
            with self.subTest(keyword=keyword):
                old = self.schema("anyOf", ["fast", "safe"])
                literal = {"$ref": "#/$defs/mode"}
                self.location(old)["anyOf"] = [{keyword: [literal] if keyword in {"enum", "examples"} else literal}]
                new = copy.deepcopy(old)
                new["$defs"]["mode"]["enum"] = ["safe"]
                self.assertTrue(self.compare(old, new)["compatible"])

    def test_ref_named_property_is_not_a_reference(self) -> None:
        old = self.schema("anyOf", ["fast", "safe"])
        self.location(old)["anyOf"] = [{"properties": {"$ref": {"const": "#/$defs/mode"}}}]
        new = copy.deepcopy(old)
        new["$defs"]["mode"]["enum"] = ["safe"]
        self.assertTrue(self.compare(old, new)["compatible"])

    def test_changed_dependency_beyond_depth_limit_is_not_approved(self) -> None:
        old = self.schema("anyOf", ["fast"])
        for index in range(12):
            old["$defs"]["mode" if index == 0 else str(index)] = {"$ref": f"#/$defs/{index + 1}"}
        old["$defs"]["12"] = {"enum": ["fast", "safe"]}
        new = copy.deepcopy(old)
        new["$defs"]["12"]["enum"] = ["safe"]
        self.assertFalse(self.compare(old, new)["compatible"])

    def test_missing_local_target_is_not_an_equal_dependency(self) -> None:
        old = self.schema("anyOf", ["fast"])
        old["$defs"] = {}
        self.assertFalse(self.compare(old, copy.deepcopy(old))["compatible"])

    def test_dependency_scan_budget_fails_closed(self) -> None:
        old = self.schema("additionalProperties", ["fast"])
        old["additionalProperties"] = {"properties": {str(index): {} for index in range(257)}}
        self.assertFalse(self.compare(old, copy.deepcopy(old))["compatible"])

    def test_repeated_branches_share_dependency_scan(self) -> None:
        branch = {"$ref": "#/$defs/mode"}
        definitions = {"mode": {"enum": [str(index) for index in range(2000)]}}
        with patch.object(compare_module, "_reference_dependencies", wraps=compare_module._reference_dependencies) as scan:
            keys = compare_module._reference_branch_keys([branch] * 100, definitions)
        self.assertEqual(len(keys), 100)
        self.assertEqual(scan.call_count, 1)


if __name__ == "__main__":
    unittest.main()
