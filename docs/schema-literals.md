# JSON Schema literal compatibility

MCP ShipCheck compares `enum` and `const` constraints as accepted input values, not as raw Python values.

## Compatibility rules

- Adding an `enum` or `const` constraint is breaking because inputs that were previously accepted can now be rejected.
- Removing either constraint is widening and therefore compatible.
- Removing or changing any previously accepted `enum` value is breaking.
- Adding only new `enum` values is compatible.
- Changing `const` to a different JSON value is breaking.
- Numerically equal JSON numbers such as `1` and `1.0` are treated as the same value.
- JSON booleans are not numbers: changing `true` to `1`, or `false` to `0`, is breaking.
- Array element order remains significant, while object key order does not.

The same checks apply at the tool input-schema root, on nested object properties, and after supported local `#/$defs/...` references are resolved.

## Conservative handling

Snapshots normally originate from JSON, so literal values should already be valid JSON values. If an in-process caller supplies a malformed `enum` or a non-JSON literal and the constraint changes, ShipCheck fails closed instead of claiming compatibility it cannot prove.

These rules do not attempt arbitrary JSON Schema equivalence. They complement the bounded type, required-property, scalar-bound, `anyOf`, and `oneOf` checks already performed by the comparator.
