"""Semantic comparison for MCP ShipCheck snapshots."""

from __future__ import annotations

import json
from math import isfinite
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
_MAX_REFERENCE_SCAN_NODES = 256
_RESTRICTING_KEYWORDS = (
    "pattern",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
)
_LOWER_BOUND_KEYWORDS = {"minLength", "minItems", "minimum"}
_UPPER_BOUND_KEYWORDS = {"maxLength", "maxItems", "maximum"}
_COMPOSITION_KEYWORDS = ("anyOf", "oneOf")


def _constraint_tightened(keyword: str, old: Any, new: Any) -> bool:
    if old == new:
        return False
    if keyword == "pattern":
        # Different regular expressions are not safely orderable. Treat a
        # replacement as potentially narrowing the accepted input set.
        return True
    if not isinstance(old, (int, float)) or isinstance(old, bool):
        return True
    if not isinstance(new, (int, float)) or isinstance(new, bool):
        return True
    if keyword in _LOWER_BOUND_KEYWORDS:
        return new > old
    if keyword in _UPPER_BOUND_KEYWORDS:
        return new < old
    return True


def _local_defs(schema: dict[str, Any]) -> dict[str, Any]:
    values = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    return values if isinstance(values, dict) else {}


def _deref(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Resolve a chain of local ``#/$defs/...`` references without looping."""

    current = schema
    seen_refs: set[str] = set()
    while isinstance(current, dict):
        ref = current.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref in seen_refs:
            break
        target = defs.get(ref[len("#/$defs/") :])
        if not isinstance(target, dict):
            break
        seen_refs.add(ref)
        current = target
    return current


def _reference_dependencies(
    schema: Any, defs: dict[str, Any],
    target_identities: dict[str, tuple[Any, ...] | None] | None = None,
) -> tuple[Any, ...] | None:
    """Identify reachable supported local targets without recursively expanding refs.

    Only schema positions are visited: reference-shaped literal/annotation data
    is not a dependency. None means the bounded scan could not establish an
    identity and must not be used as evidence of compatibility.
    """
    pending = [(schema, 0)]
    targets: dict[str, Any] = {}
    visited = 0
    while pending:
        current, depth = pending.pop()
        if not isinstance(current, dict):
            continue
        ref = current.get("$ref")
        local_ref = isinstance(ref, str) and ref.startswith("#/$defs/")
        if local_ref and ref in targets:
            continue
        visited += 1
        if depth > _MAX_SCHEMA_DEPTH or visited > _MAX_REFERENCE_SCAN_NODES:
            return None
        if local_ref:
            target = defs.get(ref[len("#/$defs/") :])
            if not isinstance(target, dict):
                return None
            targets[ref] = target
            pending.append((target, depth + 1))
            # Match the existing local resolver's supported target-only scope.
            continue
        pending.extend((child, depth + 1) for child in _properties(current).values())
        for keyword in _COMPOSITION_KEYWORDS:
            branches = current.get(keyword)
            if isinstance(branches, list):
                pending.extend((branch, depth + 1) for branch in branches)
        additional = current.get("additionalProperties")
        if isinstance(additional, dict):
            pending.append((additional, depth + 1))
    target_identities = {} if target_identities is None else target_identities
    entries = []
    for ref in sorted(targets):
        if ref not in target_identities:
            target_identities[ref] = _json_value_identity(targets[ref])
        identity = target_identities[ref]
        if identity is None:
            return None
        entries.append((ref, identity))
    return ("object", tuple(entries))


def _reference_branch_keys(value: Any, defs: dict[str, Any]) -> list[tuple[Any, ...]] | None:
    if not isinstance(value, list):
        return None
    keys = []
    cached_keys: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    target_identities: dict[str, tuple[Any, ...] | None] = {}
    for branch in value:
        identity = _json_value_identity(branch)
        if identity is None:
            return None
        if identity not in cached_keys:
            dependencies = _reference_dependencies(branch, defs, target_identities)
            if dependencies is None:
                return None
            cached_keys[identity] = (identity, dependencies)
        keys.append(cached_keys[identity])
    return keys


def _composition_branch_keys(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    try:
        return [json.dumps(branch, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for branch in value]
    except (TypeError, ValueError):
        return None


def _type_set(value: Any) -> frozenset[str] | None:
    """Normalize a valid JSON Schema ``type`` value for set comparison."""
    if isinstance(value, str):
        return frozenset((value,))
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return None


def _json_value_identity(value: Any) -> tuple[Any, ...] | None:
    """Return JSON Schema equality identity without Python bool/int aliasing.

    JSON Schema treats booleans as a different primitive type from numbers,
    while numerically equal JSON numbers such as ``1`` and ``1.0`` compare as
    the same value. Containers are compared recursively and object key order is
    irrelevant.
    """

    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not isfinite(value):
            return None
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        items: list[tuple[Any, ...]] = []
        for item in value:
            identity = _json_value_identity(item)
            if identity is None:
                return None
            items.append(identity)
        return ("array", tuple(items))
    if isinstance(value, dict):
        items: list[tuple[str, tuple[Any, ...]]] = []
        for key in sorted(value):
            if not isinstance(key, str):
                return None
            identity = _json_value_identity(value[key])
            if identity is None:
                return None
            items.append((key, identity))
        return ("object", tuple(items))
    return None


def _enum_identities(value: Any) -> list[tuple[Any, ...]] | None:
    if not isinstance(value, list):
        return None
    identities: list[tuple[Any, ...]] = []
    for item in value:
        identity = _json_value_identity(item)
        if identity is None:
            return None
        identities.append(identity)
    return identities


def _compare_type_constraint(old: dict[str, Any], new: dict[str, Any], path: str) -> list[dict[str, str]]:
    """Classify JSON Schema type changes by accepted-type set inclusion."""
    old_present = "type" in old
    new_present = "type" in new
    old_value = old.get("type")
    new_value = new.get("type")

    if not old_present and new_present:
        return [_change("input-restricted", "breaking", path, "input schema gained a type constraint")]
    if old_present and not new_present:
        return []
    if not old_present or not new_present or old_value == new_value:
        return []

    old_types = _type_set(old_value)
    new_types = _type_set(new_value)
    if old_types is None or new_types is None:
        return [_change("input-type-changed", "breaking", path, "input schema changed its type constraint")]
    if old_types == new_types:
        return []
    if old_types.issubset(new_types):
        return [
            _change(
                "input-type-widened",
                "non-breaking",
                path,
                f"input schema widened accepted types from {sorted(old_types)!r} to {sorted(new_types)!r}",
            )
        ]
    return [
        _change(
            "input-type-changed",
            "breaking",
            path,
            f"input schema no longer accepts all prior types {sorted(old_types)!r}",
        )
    ]


def _compare_literal_constraints(old: dict[str, Any], new: dict[str, Any], path: str) -> list[dict[str, str]]:
    """Classify ``enum`` and ``const`` changes using JSON Schema value equality."""

    changes: list[dict[str, str]] = []
    old_enum_present = "enum" in old
    new_enum_present = "enum" in new
    old_enum = old.get("enum")
    new_enum = new.get("enum")

    if not old_enum_present and new_enum_present:
        changes.append(_change("input-restricted", "breaking", path, "input schema gained an enum constraint"))
    elif old_enum_present and new_enum_present:
        old_ids = _enum_identities(old_enum)
        new_ids = _enum_identities(new_enum)
        if old_ids is None or new_ids is None:
            if old_enum != new_enum:
                changes.append(_change("enum-changed", "breaking", path, "input schema changed its enum constraint"))
        else:
            new_id_set = set(new_ids)
            removed = [value for value, identity in zip(old_enum, old_ids, strict=True) if identity not in new_id_set]
            if removed:
                changes.append(
                    _change("enum-narrowed", "breaking", path, f"input schema no longer accepts {removed!r}")
                )

    old_const_present = "const" in old
    new_const_present = "const" in new
    if not old_const_present and new_const_present:
        changes.append(_change("input-restricted", "breaking", path, "input schema gained a const constraint"))
    elif old_const_present and new_const_present:
        old_identity = _json_value_identity(old.get("const"))
        new_identity = _json_value_identity(new.get("const"))
        if old_identity is None or new_identity is None:
            if old.get("const") != new.get("const"):
                changes.append(_change("const-changed", "breaking", path, "input schema const changed"))
        elif old_identity != new_identity:
            changes.append(_change("const-changed", "breaking", path, "input schema const changed"))

    return changes


def _compare_composition_constraints(
    old: dict[str, Any], new: dict[str, Any], path: str,
    defs_old: dict[str, Any], defs_new: dict[str, Any],
) -> list[dict[str, str]]:
    """Conservatively classify supported ``anyOf``/``oneOf`` changes."""
    changes: list[dict[str, str]] = []
    for keyword in _COMPOSITION_KEYWORDS:
        old_present = keyword in old
        new_present = keyword in new
        old_value = old.get(keyword)
        new_value = new.get(keyword)
        old_keys = _composition_branch_keys(old_value)
        new_keys = _composition_branch_keys(new_value)
        keyword_path = f"{path}.{keyword}"

        if old_present and new_present:
            old_ref_keys = _reference_branch_keys(old_value, defs_old)
            new_ref_keys = _reference_branch_keys(new_value, defs_new)
            retained = old_ref_keys is not None and new_ref_keys is not None
            if retained:
                retained = (set(old_ref_keys).issubset(set(new_ref_keys)) if keyword == "anyOf"
                            else sorted(old_ref_keys) == sorted(new_ref_keys))
            if not retained:
                changes.append(_change("input-restricted", "breaking", keyword_path,
                                       f"input schema changed {keyword} alternatives or their local reference dependencies"))
                continue
        if not old_present and new_present:
            changes.append(_change("input-restricted", "breaking", keyword_path, f"input schema gained a {keyword} constraint"))
            continue
        if old_present and not new_present:
            continue
        if not old_present or not new_present or old_value == new_value:
            continue
        if old_keys is None or new_keys is None:
            changes.append(_change("input-restricted", "breaking", keyword_path, f"input schema changed its {keyword} constraint"))
            continue

        if keyword == "anyOf":
            # Keeping every old branch and adding alternatives cannot reject an
            # input that previously matched at least one branch.
            if set(old_keys).issubset(set(new_keys)):
                continue
            changes.append(_change("input-restricted", "breaking", keyword_path, "input schema removed or changed an anyOf alternative"))
            continue

        # oneOf requires exactly one matching branch. Only pure reordering of
        # the same branch multiset is provably safe without semantic reasoning.
        if sorted(old_keys) != sorted(new_keys):
            changes.append(_change("input-restricted", "breaking", keyword_path, "input schema changed oneOf alternatives; exclusivity may narrow accepted input"))

    return changes


def _additional_properties_mode(schema: dict[str, Any]) -> tuple[str, Any]:
    """Normalize ``additionalProperties`` with JSON Schema's default-open semantics."""
    if "additionalProperties" not in schema:
        return ("allow", True)
    value = schema.get("additionalProperties")
    if value is True:
        return ("allow", True)
    if value is False:
        return ("deny", False)
    if isinstance(value, dict):
        return ("schema", value)
    return ("invalid", value)


def _compare_additional_properties(
    old: dict[str, Any], new: dict[str, Any], path: str,
    defs_old: dict[str, Any], defs_new: dict[str, Any],
) -> list[dict[str, str]]:
    """Detect object-schema changes that reject previously accepted extra keys.

    Missing ``additionalProperties`` is equivalent to ``true``. Schema-valued
    changes are intentionally conservative: an empty schema remains equivalent
    to allowing extras, while a new or changed non-empty schema is considered a
    restriction unless the old schema denied extras entirely.
    """
    if isinstance(old.get("additionalProperties"), dict) and isinstance(new.get("additionalProperties"), dict):
        old_dependencies = _reference_dependencies(old["additionalProperties"], defs_old)
        new_dependencies = _reference_dependencies(new["additionalProperties"], defs_new)
        if old_dependencies is None or new_dependencies is None or old_dependencies != new_dependencies:
            return [_change("additional-properties-changed", "breaking", f"{path}.additionalProperties",
                            "input schema changed or could not resolve local reference dependencies for additional properties")]

    old_mode, old_value = _additional_properties_mode(old)
    new_mode, new_value = _additional_properties_mode(new)
    keyword_path = f"{path}.additionalProperties"

    if old_mode == new_mode and old_value == new_value:
        return []

    # Once extra keys were forbidden, allowing all extras or allowing a subset
    # cannot reject any object that previously validated.
    if old_mode == "deny" and new_mode in {"allow", "schema"}:
        return []
    if new_mode == "allow":
        return []

    # ``{}`` accepts every value, so it is equivalent to ``true`` for the
    # additional-property values it evaluates.
    if old_mode == "allow" and new_mode == "schema" and new_value == {}:
        return []
    if old_mode == "schema" and old_value == {} and new_mode == "allow":
        return []

    if old_mode == "invalid" or new_mode == "invalid":
        return [
            _change(
                "additional-properties-changed",
                "breaking",
                keyword_path,
                "input schema changed an unsupported additionalProperties form",
            )
        ]

    if old_mode == "allow" and new_mode in {"deny", "schema"}:
        return [
            _change(
                "additional-properties-restricted",
                "breaking",
                keyword_path,
                "input schema no longer accepts all additional object properties",
            )
        ]
    if old_mode == "schema" and new_mode == "deny":
        return [
            _change(
                "additional-properties-restricted",
                "breaking",
                keyword_path,
                "input schema no longer accepts additional object properties allowed by the prior schema",
            )
        ]
    if old_mode == "schema" and new_mode == "schema":
        return [
            _change(
                "additional-properties-changed",
                "breaking",
                keyword_path,
                "input schema changed the contract for additional object properties",
            )
        ]
    return []


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
    changes: list[dict[str, str]] = []
    if depth > _MAX_SCHEMA_DEPTH:
        return changes

    if defs_old is None:
        defs_old = _local_defs(old)
    if defs_new is None:
        defs_new = _local_defs(new)

    old = _deref(old, defs_old)
    new = _deref(new, defs_new)
    seen = seen if seen is not None else set()
    pair = (id(old), id(new))
    if pair in seen:
        return changes
    seen.add(pair)

    changes.extend(_compare_type_constraint(old, new, path))
    changes.extend(_compare_literal_constraints(old, new, path))
    changes.extend(_compare_composition_constraints(old, new, path, defs_old, defs_new))
    changes.extend(_compare_additional_properties(old, new, path, defs_old, defs_new))

    old_required, new_required = _required(old), _required(new)
    for field in sorted(new_required - old_required):
        changes.append(_change("required-added", "breaking", f"{path}.properties.{field}", f"input {field!r} became required"))

    old_properties, new_properties = _properties(old), _properties(new)
    for field in sorted(old_properties):
        property_path = f"{path}.properties.{field}"
        if field not in new_properties:
            changes.append(_change("input-removed", "breaking", property_path, f"input {field!r} was removed"))
            continue

        old_value = _deref(old_properties[field], defs_old)
        new_value = _deref(new_properties[field], defs_new)

        for keyword in _RESTRICTING_KEYWORDS:
            if keyword not in old_value and keyword in new_value:
                changes.append(_change("input-restricted", "breaking", property_path, f"input {field!r} gained a {keyword} constraint"))
            elif keyword in old_value and keyword in new_value and _constraint_tightened(
                keyword, old_value[keyword], new_value[keyword]
            ):
                changes.append(
                    _change(
                        "input-restricted",
                        "breaking",
                        property_path,
                        f"input {field!r} tightened its {keyword} constraint",
                    )
                )

        # Recurse through all existing property pairs so type, literal,
        # composition, and object-openness keywords are checked even on
        # primitive properties and behind local $defs refs.
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
    an input is removed or narrows its accepted type/literal set, a supported
    schema constraint becomes stricter, object openness is narrowed, or
    protocol/server capabilities change. Tool descriptions deliberately do not
    affect the result.
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
