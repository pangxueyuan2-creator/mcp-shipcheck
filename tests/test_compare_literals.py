from __future__ import annotations

from typing import Any

from mcp_shipcheck.compare import compare_snapshots


def _snapshot(schema: dict[str, Any]) -> dict[str, Any]:
    return {"tools": [{"name": "lookup", "inputSchema": schema}]}


def _compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return compare_snapshots(_snapshot(old), _snapshot(new))


def test_root_enum_narrowing_is_breaking() -> None:
    result = _compare({"enum": ["a", "b"]}, {"enum": ["a"]})

    assert result["compatible"] is False
    assert result["changes"] == [
        {
            "kind": "enum-narrowed",
            "severity": "breaking",
            "path": "tools.lookup.inputSchema",
            "message": "input schema no longer accepts ['b']",
        }
    ]


def test_root_enum_expansion_is_compatible() -> None:
    result = _compare({"enum": ["a"]}, {"enum": ["a", "b"]})

    assert result["compatible"] is True
    assert result["changes"] == []


def test_gaining_root_enum_constraint_is_breaking() -> None:
    result = _compare({}, {"enum": ["a"]})

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "input-restricted"
    assert result["changes"][0]["path"] == "tools.lookup.inputSchema"


def test_boolean_and_number_enum_values_are_not_aliased() -> None:
    result = _compare({"enum": [True]}, {"enum": [1]})

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "enum-narrowed"


def test_numerically_equal_json_numbers_remain_compatible() -> None:
    result = _compare({"enum": [1], "const": 1}, {"enum": [1.0], "const": 1.0})

    assert result["compatible"] is True
    assert result["changes"] == []


def test_object_enum_identity_ignores_key_order() -> None:
    result = _compare(
        {"enum": [{"count": 1, "enabled": True}]},
        {"enum": [{"enabled": True, "count": 1.0}]},
    )

    assert result["compatible"] is True
    assert result["changes"] == []


def test_const_boolean_to_number_is_breaking() -> None:
    result = _compare({"const": True}, {"const": 1})

    assert result["compatible"] is False
    assert result["changes"] == [
        {
            "kind": "const-changed",
            "severity": "breaking",
            "path": "tools.lookup.inputSchema",
            "message": "input schema const changed",
        }
    ]


def test_nested_property_enum_is_checked_once() -> None:
    result = _compare(
        {"type": "object", "properties": {"mode": {"type": "string", "enum": ["safe", "fast"]}}},
        {"type": "object", "properties": {"mode": {"type": "string", "enum": ["safe"]}}},
    )

    assert result["compatible"] is False
    assert len(result["changes"]) == 1
    assert result["changes"][0]["kind"] == "enum-narrowed"
    assert result["changes"][0]["path"] == "tools.lookup.inputSchema.properties.mode"


def test_local_defs_literal_constraint_is_checked() -> None:
    result = _compare(
        {
            "type": "object",
            "properties": {"mode": {"$ref": "#/$defs/Mode"}},
            "$defs": {"Mode": {"enum": ["safe", "fast"]}},
        },
        {
            "type": "object",
            "properties": {"mode": {"$ref": "#/$defs/Mode"}},
            "$defs": {"Mode": {"enum": ["safe"]}},
        },
    )

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "enum-narrowed"
    assert result["changes"][0]["path"] == "tools.lookup.inputSchema.properties.mode"


def test_malformed_enum_change_fails_closed() -> None:
    result = _compare({"enum": "safe"}, {"enum": ["safe"]})

    assert result["compatible"] is False
    assert result["changes"] == [
        {
            "kind": "enum-changed",
            "severity": "breaking",
            "path": "tools.lookup.inputSchema",
            "message": "input schema changed its enum constraint",
        }
    ]
