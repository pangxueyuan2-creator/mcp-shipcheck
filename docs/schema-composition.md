# JSON Schema composition compatibility

MCP ShipCheck is intentionally a bounded release-contract checker, not a complete JSON Schema theorem prover. It classifies a small set of composition changes conservatively so a release does not silently narrow a tool's accepted input surface.

## `anyOf`

`anyOf` accepts an instance when at least one branch validates. ShipCheck therefore treats these cases as follows:

- Adding a brand-new `anyOf` constraint is breaking because previously accepted inputs may now match none of its branches.
- Removing the `anyOf` constraint is compatible at that schema location because it widens the accepted set.
- Reordering branches is compatible.
- Adding branches while retaining every old branch byte-for-byte (after deterministic JSON canonicalization) is compatible.
- Removing or structurally changing any previously present branch is classified as breaking.

That last rule is deliberately conservative. ShipCheck does not try to prove that a rewritten branch is semantically wider than its predecessor.

## `oneOf`

`oneOf` accepts an instance only when exactly one branch validates. Because a newly added branch can overlap an existing branch and make a previously valid instance match two branches, ShipCheck only considers pure reordering of the same branch multiset compatible.

Adding, removing, or structurally changing a `oneOf` branch is therefore classified as breaking/fail-closed. Removing the entire `oneOf` constraint remains compatible at that schema location because the exclusivity restriction disappears.

## Scope and identity

Composition checks apply at the tool input-schema root, inside ordinary properties, and after resolving local `#/$defs/...` references. Existing depth and reference-cycle bounds still apply.

Branch identity is structural, not semantic: objects are canonicalized with sorted JSON keys. Two schemas that are logically equivalent but written with different structures can still be treated as different. This bias is intentional for a release gate: a false-positive review request is preferable to silently approving a contract narrowing that ShipCheck cannot prove safe.

Branch identity also includes reachable supported local `#/$defs/...` targets.
Keeping the same reference text while changing its target is a structural
change. This applies even to target widening in `oneOf`, which can introduce
overlap and reject inputs that previously matched exactly one branch. Changes
to unused definitions do not affect branch identity. Dependency values preserve
JSON's distinction between booleans and numbers; equal numbers such as `1` and
`1.0` have the same identity.

The dependency scan follows ordinary `properties`, `anyOf`, `oneOf`, and
schema-valued `additionalProperties`, plus chains of the existing supported
local references. It does not interpret reference-shaped data inside `enum`,
`const`, or annotations. Each referenced target is recorded once, including in
cycles. A branch scan is bounded to depth 8 and 256 schema nodes; an unresolved
local target or an exceeded bound is conservatively breaking, even if the raw
branch text is unchanged. This does not add remote references, JSON Pointer
escape handling, nested identifier scopes, or `$ref` sibling semantics.

Unsupported JSON Schema constructs remain outside ShipCheck's compatibility claim. A compatible result means no breaking change was found within the documented subset; it is not a proof of full JSON Schema equivalence.
