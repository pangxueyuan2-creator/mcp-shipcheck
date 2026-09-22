# Object openness compatibility

MCP tool input schemas often rely on JSON Schema's default object behavior: when `additionalProperties` is omitted, extra keys are allowed. Tightening that contract can break clients that were valid against the previous tool schema even when every declared property is unchanged.

MCP ShipCheck compares `additionalProperties` at the input-schema root, on nested object properties, and after supported local `#/$defs/...` references are resolved.

## Classification

- missing or `true` -> `false`: **breaking**; previously accepted extra keys are rejected.
- missing or `true` -> `{}`: compatible; the empty schema still accepts every extra value.
- missing or `true` -> a non-empty schema: **breaking**; extra values now have a contract they did not have before.
- `false` -> missing, `true`, or a schema: compatible widening; objects that were previously valid remain valid.
- schema -> `false`: **breaking**; extras accepted by the prior schema are now rejected.
- schema -> a different schema: **breaking, fail-closed**. ShipCheck does not claim arbitrary JSON Schema implication, so it will not guess that one non-trivial schema is a widening of another.
- malformed/unsupported candidate forms: **breaking, fail-closed** when the value changes.

The comparison intentionally does not emit a non-breaking change record for pure openness widening. Its job here is to prevent a release from being labeled compatible when the accepted object-input set shrinks.

The identity of a schema-valued policy includes its reachable supported local
`#/$defs/...` targets. An unchanged reference whose target changes is therefore
classified as a changed schema. Unused definitions are ignored. Dependency
scanning has the same supported positions, cycle handling, depth/node bounds,
and conservative unresolved-reference behavior described in
[`schema-composition.md`](schema-composition.md#scope-and-identity).

## Example

A server that changes from:

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"}
  }
}
```

to:

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"}
  },
  "additionalProperties": false
}
```

is now reported as breaking at `tools.<name>.inputSchema.additionalProperties`.

This rule is deliberately bounded to `additionalProperties`. `unevaluatedProperties`, pattern-based property evaluation, and proving semantic implication between arbitrary schema-valued policies remain outside this check rather than being approximated unsafely.
