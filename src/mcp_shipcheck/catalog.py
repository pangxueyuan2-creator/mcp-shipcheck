"""Structural validation for observed and persisted tool catalogs."""

from __future__ import annotations

from typing import Any


def validate_input_schema(value: Any, *, source: str) -> dict[str, Any]:
    """Require a schema object without claiming full JSON Schema validation."""
    if not isinstance(value, dict):
        raise ValueError(f"{source} inputSchema must be an object")
    if "_invalidInputSchema" in value:
        raise ValueError(
            f"{source} inputSchema contains the legacy _invalidInputSchema marker; "
            "fix the server schema and regenerate affected snapshots, including trusted baselines"
        )
    return value


def validate_snapshot_catalog(
    snapshot: dict[str, Any], *, source: str = "snapshot"
) -> dict[str, dict[str, Any]]:
    """Validate and index every tool, rejecting partial or ambiguous catalogs.

    Metadata such as ``format`` and ``protocolVersion`` is optional for the
    programmatic comparator; the CLI separately checks its v1 file format.
    """
    if not isinstance(snapshot, dict):
        raise ValueError(f"{source} must be an object")
    values = snapshot.get("tools")
    if not isinstance(values, list):
        raise ValueError(f"{source} tools must be an array")
    tools: dict[str, dict[str, Any]] = {}
    for index, tool in enumerate(values):
        location = f"{source} tools[{index}]"
        if not isinstance(tool, dict):
            raise ValueError(f"{location} must be an object")
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{location} name must be a non-empty string")
        if name in tools:
            raise ValueError(f"{source} tools contains duplicate tool names")
        validate_input_schema(tool.get("inputSchema"), source=location)
        tools[name] = tool
    return tools
