# Contributing to MCP ShipCheck

Thank you for helping make MCP releases safer to ship.

## Local workflow

Use Python 3.10 or newer. Create an environment if desired, then install the editable package and run the complete suite.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
bash demo/run_demo.sh
```

MCP ShipCheck intentionally has no runtime dependency outside the Python standard library. Please keep this property unless a well-explained, security-reviewed exception is accepted.

## Scope and design rules

Contributions must preserve the narrow safety boundary: ShipCheck may start an explicitly supplied server command, but it must not issue `tools/call`, persist secrets, scrape environments, or quietly make network requests. Comparisons should prefer deterministic, explainable rules over model-based judgements.

A change to compatibility classification requires tests for both the newly detected breaking case and a nearby compatible case. Changes to the snapshot format require a format version decision, migration notes, and documentation updates.

## Pull requests

Keep pull requests focused. Explain the user-visible contract change, include test output, and do not commit generated `.demo/` artifacts, credentials, or private snapshots. For larger behavior changes, open an issue first so maintainers can agree on the public semantics before implementation.
