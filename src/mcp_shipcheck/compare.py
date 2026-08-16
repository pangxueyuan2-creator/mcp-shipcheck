"""Semantic comparison for MCP ShipCheck snapshots."""

from __future__ import annotations

from typing import Any


def _tools(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = snapshot.get("tools", [])
    if not isinstance(values, list):
        return {}
    return {tool["name"]: tool for tool in values if isinstance(tool, dict) and isinstance(tool.get("name"), str)}


def _properties(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {key: value for key, value in values.items() if isinstance(value, dict)} if isinstance(values, dict) else {}


def _required(schema: dict[str, Any]) -> set[str]:
    values = schema.get("required", []) if isinstance(schema, dict) else []
    return set(value for value in values if isinstance(value, str)) if isinstance(values, list) else set()


def _change(kind: str, severity: str, path: str, message: str) -> dict[str, str]:
    return {"kind": kind, "severity": severity, "path": path, "message": message}


_MAX_SCHEMA_DEPTH = 8
_RESTRICTING_KEYWORDS = (
    "pattern",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
)


def _deref(schema: dict[str, Any], defs: dict[str, Any], guard: set[str]) -> dict[str, Any]:
    """Resolve a local $defs reference chain with a cycle guard."""

    while (
        isinstance(schema, dict)
        and isinstance(schema.get("$ref"), str)
        and schema["$ref"].startswith("#/$defs/")
    ):
        name = schema["$ref"][len("#/$defs/") :]
        if name in guard or not isinstance(defs.get(name), dict):
            break
        guard.add(name)
        schema = defs[name]
    return schema


def _compare_schema(
    old: dict[str, Any],
    new: dict[str, Any],
    path: str,
    *,
    defs_old: dict[str, Any] | None = None,
    defs_new: dict[str, Any] | None = None,
    depth: int = 0,
    seen: set[tuple[int, int]] | None = None,
) -> list[dict[str, str]]:
    """Compare schemas recursively so constraints behind nested objects and
    local $refs are classified instead of silently passing as compatible."""

    changes: list[dict[str, str]] = []
    if depth > _MAX_SCHEMA_DEPTH or not isinstance(old, dict) or not isinstance(new, dict):
        return changes
    seen = seen if seen is not None else set()
    pair = (id(old), id(new))
    if pair in seen:
        return changes
    seen.add(pair)

    defs_old = old.get("$defs") if isinstance(old.get("$defs"), dict) else (defs_old or {})
    defs_new = new.get("$defs") if isinstance(new.get("$defs"), dict) else (defs_new or {})
    old = _deref(old, defs_old, set())
    new = _deref(new, defs_new, set())

    old_required, new_required = _required(old), _required(new)
    for field in sorted(new_required - old_required):
        changes.append(_change("required-added", "breaking", f"{path}.properties.{field}", f"input {field!r} became required"))
    old_properties, new_properties = _properties(old), _properties(new)
    for field in sorted(old_properties):
        property_path = f"{path}.properties.{field}"
        if field not in new_properties:
            changes.append(_change("input-removed", "breaking", property_path, f"input {field!r} was removed"))
            continue
        old_value, new_value = old_properties[field], new_properties[field]
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            old_value = _deref(old_value, defs_old, set())
            new_value = _deref(new_value, defs_new, set())
        old_type, new_type = old_value.get("type"), new_value.get("type")
        if old_type is None and new_type is not None:
            changes.append(_change("input-restricted", "breaking", property_path, f"input {field!r} gained a type constraint"))
        elif new_type is not None and old_type != new_type:
            changes.append(_change("input-type-changed", "breaking", property_path, f"input {field!r} type changed from {old_type!r} to {new_type!r}"))
        old_enum, new_enum = old_value.get("enum"), new_value.get("enum")
        if old_enum is None and isinstance(new_enum, list):
            changes.append(_change("input-restricted", "breaking", property_path, f"input {field!r} gained an enum constraint"))
        elif isinstance(old_enum, list) and isinstance(new_enum, list):
            removed = sorted(set(old_enum) - set(new_enum), key=repr)
            if removed:
                changes.append(_change("enum-narrowed", "breaking", property_path, f"input {field!r} no longer accepts {removed!r}"))
        if "const" not in old_value and "const" in new_value:
            changes.append(_change("input-restricted", "breaking", property_path, f"input {field!r} gained a const constraint"))
        elif "const" in old_value and "const" in new_value and old_value.get("const") != new_value.get("const"):
            changes.append(_change("const-changed", "breaking", property_path, f"input {field!r} const changed"))
        for keyword in _RESTRICTING_KEYWORDS:
            if keyword not in old_value and keyword in new_value:
                changes.append(_change("input-restricted", "breaking", property_path, f"input {field!r} gained a {keyword} constraint"))
        if isinstance(old_value.get("properties"), dict) or isinstance(new_value.get("properties"), dict):
            changes.extend(
                _compare_schema(
                    old_value,
                    new_value,
                    property_path,
                    defs_old=defs_old,
                    defs_new=defs_new,
                    depth=depth + 1,
                    seen=seen,
                )
            )
    for field in sorted(new_properties.keys() - old_properties.keys() - new_required):
        changes.append(_change("input-added", "non-breaking", f"{path}.properties.{field}", f"optional input {field!r} was added"))
    return changes


def compare_snapshots(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare two snapshots and classify public tool-surface changes.

    A comparison is breaking when a tool disappears, a required input is added,
    an input is removed or changes type, an enum is narrowed, or protocol/server
    capabilities change. Tool descriptions deliberately do not affect the result.
    """
    changes: list[dict[str, str]] = []
    baseline_tools, candidate_tools = _tools(baseline), _tools(candidate)
    for name in sorted(baseline_tools):
        tool_path = f"tools.{name}"
        if name not in candidate_tools:
            changes.append(_change("tool-removed", "breaking", tool_path, f"tool {name!r} was removed"))
            continue
        old_schema = baseline_tools[name].get("inputSchema", {})
        new_schema = candidate_tools[name].get("inputSchema", {})
        changes.extend(_compare_schema(old_schema, new_schema, tool_path + ".inputSchema"))
    for name in sorted(candidate_tools.keys() - baseline_tools.keys()):
        changes.append(_change("tool-added", "non-breaking", f"tools.{name}", f"tool {name!r} was added"))
    if baseline.get("protocolVersion") != candidate.get("protocolVersion"):
        changes.append(_change("protocol-version-changed", "breaking", "protocolVersion", "protocol version changed"))
    if baseline.get("capabilities", {}) != candidate.get("capabilities", {}):
        changes.append(_change("capabilities-changed", "breaking", "capabilities", "server capabilities changed"))
    breaking = [change for change in changes if change["severity"] == "breaking"]
    return {
        "format": "mcp-shipcheck/compare/v1",
        "compatible": not breaking,
        "summary": {"breaking": len(breaking), "nonBreaking": len(changes) - len(breaking), "total": len(changes)},
        "changes": changes,
    }
