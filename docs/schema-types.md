# JSON Schema type compatibility

MCP ShipCheck treats a JSON Schema `type` value as the set of JSON instance kinds accepted by that schema node. The supported JSON Schema forms are a single string such as `"string"` or a non-empty array of strings such as `["string", "null"]`.

This matters for release compatibility because nullable and other union-shaped input contracts are common in generated MCP schemas. A textual `type` change is not automatically breaking: `"string"` to `["string", "null"]` preserves every previously valid string and adds null, while the reverse transition rejects inputs that were valid before.

## Classification

- If a candidate adds a `type` where the baseline had none, the candidate is breaking because it introduces a new restriction.
- If every baseline type remains accepted and the candidate adds more types, ShipCheck emits a non-breaking `input-type-widened` change.
- If the candidate removes any previously accepted type, ShipCheck emits a breaking `input-type-changed` change.
- Reordering a `type` array is ignored because order has no schema meaning.
- Removing a `type` constraint is treated as widening and remains compatible.
- If either changed `type` value is malformed or outside the supported string/array forms, ShipCheck fails closed and treats the changed constraint as breaking rather than guessing at semantics.

The same comparison runs at the tool input-schema root, nested properties, and schemas reached through supported local `#/$defs/...` references.

## Boundary

This is deliberately set-based reasoning about the `type` keyword, not a general JSON Schema theorem prover. Other keywords can still make two schemas semantically different even when their accepted type sets match. ShipCheck separately handles the bounded constraints documented elsewhere, including required properties, enums, const values, numeric/string/array bounds, and selected `anyOf`/`oneOf` changes.
