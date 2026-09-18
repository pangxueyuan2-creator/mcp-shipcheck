from __future__ import annotations

from typing import Any

from mcp_shipcheck.compare import compare_snapshots


def _snapshot(schema: dict[str, Any]) -> dict[str, Any]:
    return {"tools": [{"name": "lookup", "inputSchema": schema}]}


def _compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return compare_snapshots(_snapshot(old), _snapshot(new))


def test_closing_root_object_is_breaking() -> None:
    result = _compare(
        {"type": "object", "properties": {"query": {"type": "string"}}},
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
    )

    assert result["compatible"] is False
    assert result["changes"] == [
        {
            "kind": "additional-properties-restricted",
            "severity": "breaking",
            "path": "tools.lookup.inputSchema.additionalProperties",
            "message": "input schema no longer accepts all additional object properties",
        }
    ]


def test_explicit_true_to_false_is_breaking() -> None:
    result = _compare(
        {"type": "object", "additionalProperties": True},
        {"type": "object", "additionalProperties": False},
    )

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "additional-properties-restricted"


def test_opening_closed_object_is_compatible() -> None:
    result = _compare(
        {"type": "object", "additionalProperties": False},
        {"type": "object"},
    )

    assert result["compatible"] is True
    assert result["changes"] == []


def test_empty_schema_is_equivalent_to_default_open() -> None:
    result = _compare(
        {"type": "object"},
        {"type": "object", "additionalProperties": {}},
    )

    assert result["compatible"] is True
    assert result["changes"] == []


def test_new_schema_for_extra_values_is_breaking() -> None:
    result = _compare(
        {"type": "object"},
        {"type": "object", "additionalProperties": {"type": "string"}},
    )

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "additional-properties-restricted"


def test_schema_to_false_is_breaking() -> None:
    result = _compare(
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "object", "additionalProperties": False},
    )

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "additional-properties-restricted"


def test_changed_extra_value_schema_fails_closed() -> None:
    result = _compare(
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "object", "additionalProperties": {"type": "integer"}},
    )

    assert result["compatible"] is False
    assert result["changes"] == [
        {
            "kind": "additional-properties-changed",
            "severity": "breaking",
            "path": "tools.lookup.inputSchema.additionalProperties",
            "message": "input schema changed the contract for additional object properties",
        }
    ]


def test_nested_object_closure_is_detected() -> None:
    result = _compare(
        {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {"mode": {"type": "string"}},
                }
            },
        },
        {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {"mode": {"type": "string"}},
                    "additionalProperties": False,
                }
            },
        },
    )

    assert result["compatible"] is False
    assert result["changes"][0]["path"] == "tools.lookup.inputSchema.properties.options.additionalProperties"


def test_local_defs_object_closure_is_detected() -> None:
    result = _compare(
        {
            "type": "object",
            "properties": {"options": {"$ref": "#/$defs/Options"}},
            "$defs": {"Options": {"type": "object"}},
        },
        {
            "type": "object",
            "properties": {"options": {"$ref": "#/$defs/Options"}},
            "$defs": {"Options": {"type": "object", "additionalProperties": False}},
        },
    )

    assert result["compatible"] is False
    assert result["changes"][0]["path"] == "tools.lookup.inputSchema.properties.options.additionalProperties"


def test_malformed_additional_properties_change_fails_closed() -> None:
    result = _compare(
        {"type": "object", "additionalProperties": "anything"},
        {"type": "object", "additionalProperties": True},
    )

    assert result["compatible"] is False
    assert result["changes"][0]["kind"] == "additional-properties-changed"
