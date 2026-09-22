# Snapshot catalog validation

Compatibility comparison requires a complete, unambiguous tool catalog. A malformed catalog is an input error, not evidence that a release is compatible.

## Required structure

- The snapshot must be an object with an explicit `tools` array. An empty array is valid.
- Every array item must be an object.
- Every tool must have a non-empty string `name`; whitespace-only names are rejected. Names must be unique within the complete catalog, including across pagination pages.
- Every tool must provide an object-valued `inputSchema`. An empty schema object is valid. Missing schemas, `null`, booleans, numbers, strings, and arrays are rejected.

The Python `compare_snapshots` API still accepts minimal snapshots such as:

```python
{"tools": [{"name": "lookup", "inputSchema": {}}]}
```

It does not require `format`, `protocolVersion`, or observation metadata. Snapshot files read by the CLI still require `"format": "mcp-shipcheck/v1"`; the format version has not changed.

Validation checks every entry before comparing tool names. It cannot silently discard malformed tools, reinterpret a damaged list as an empty catalog, or let a later duplicate replace an earlier tool. This includes newly added tools whose schemas would not otherwise be compared with a baseline entry.

This is structural validation only. Schema keyword semantics remain bounded by the documented comparator rules; arbitrary JSON Schema validation is not performed. Unknown schema keywords and ordinary input properties named `_invalidInputSchema` are not rejected.

## Errors and outputs

`compare_snapshots` raises `ValueError` for an invalid catalog on either side. The CLI reports an input error and exits `1`, without generating a compatibility result. Exit `2` remains reserved for classified breaking changes between valid catalogs. An existing comparison-output file is preserved on validation failure.

The stdio probe raises `ProtocolError` if a server returns an invalid input schema on any page. It does not normalize that schema into a placeholder or publish a partial candidate snapshot. `verify` leaves its candidate and comparison outputs unchanged on such a probe failure. Validation errors identify the structural problem without echoing invalid schema values.

Catalog validation is separate from the CLI's baseline preflight and output-path protection. A candidate file alone is not evidence that baseline comparison succeeded: always honor the command's exit status, including when output files already existed.

## Migrating legacy invalid-schema markers

Earlier releases substituted `{"_invalidInputSchema": true}` when a server returned a non-object schema. That substitution discarded the original contract, so the placeholder cannot safely serve as a baseline or a candidate.

The top-level `_invalidInputSchema` schema key is reserved for this legacy marker and is rejected with a regeneration diagnostic. Fix the server to return an object-valued `inputSchema`, then regenerate every affected snapshot, including trusted baselines. Do not merely remove the marker or replace it with an empty object: either would assert an unobserved contract.
