# MCP ShipCheck

**Ship the MCP server you actually packaged.**

MCP ShipCheck starts an explicitly supplied **stdio** MCP server command, sends only `initialize` and `tools/list`, and writes a safe release snapshot. In CI, it compares that snapshot to a trusted baseline and exits non-zero when a public tool contract breaks.

> It never executes `tools/call`. It never records tool arguments, environment variables, tool output, or stderr.

This is not a full MCP test framework or a security scanner. It is the small release gate between “tests passed in the repository” and “the package your user installs still starts and exposes a compatible tool surface.”

## Install and run in under 60 seconds

```bash
# From a source checkout or release-candidate artifact:
python -m pip install .

# Probe the command that a user or CI job would really start.
mcp-shipcheck verify --output .shipcheck/baseline.json -- \
  python -m your_mcp_server

# On the next release, compare the published artifact to the trusted baseline.
mcp-shipcheck verify --baseline .shipcheck/baseline.json \
  --output .shipcheck/candidate.json \
  --compare-output .shipcheck/compare.json -- \
  python -m your_mcp_server
```

A successful compatible run exits `0`. A server startup/protocol failure exits `1`. A server that starts but breaks the baseline exits `2`, which is convenient for a CI release gate.

## Killer feature: artifact-aware compatibility evidence

A source-tree unit test cannot catch a package that forgot to ship an environment-variable fix, a command that fails in an editor/CI `PATH`, or a server whose installed dependency changed its public tool schema. ShipCheck probes the **command and environment you choose**, then compares only client-visible release data.

| Command | What it does | Safety property |
|---|---|---|
| `verify` | Starts one command, calls `initialize` and `tools/list`, writes a snapshot. | Does not execute any MCP tool. |
| `verify --baseline` | Creates a candidate snapshot and checks it against a trusted baseline. | Emits exit code `2` only for classified public breakage. |
| `compare` | Compares two existing snapshots; writes JSON to stdout or a file. | Does not start any process. |

## What counts as breaking

ShipCheck reports a breaking change when it observes a removed tool, removed input, newly required input, input type change, narrowed `enum`, changed `const`, protocol-version change, or server-capability change. A newly added tool or optional input is reported as non-breaking. Description-only changes are intentionally ignored.

Snapshot JSON is deterministic except for the observation timestamp and probe duration. It contains server info, capabilities, tool names, descriptions and input schemas. It does **not** contain requests beyond the two fixed protocol requests, tool call inputs, tool results, environment variables, or server stderr.

## Full local demo

The repository includes a real JSON-RPC fixture server; it is not a mocked CLI output. The demo captures a baseline, accepts a compatible new tool, and then deliberately detects a removed tool plus a narrowed input contract.

```bash
git clone https://github.com/pangxueyuan2-creator/mcp-shipcheck
cd mcp-shipcheck
python -m pip install -e .
bash demo/run_demo.sh
```

## GitHub Actions example

Run this after building and installing the release candidate artifact in a clean job. Pin the executable/version you mean to ship; ShipCheck does not download anything itself.

```yaml
- name: Install release candidate
  run: python -m pip install dist/your_mcp_server-*.whl

- name: Check public MCP contract
  run: |
    mcp-shipcheck verify \
      --baseline .shipcheck/baseline.json \
      --output .shipcheck/candidate.json \
      --compare-output .shipcheck/compare.json -- \
      python -m your_mcp_server
```

## Why a separate project?

PatchWitness validates a code change’s scope, policies, checks, secrets and evidence after the change exists. GuardSpec derives allowed agent behavior before work begins. TaskToPR turns one Issue into an isolated tested change and optional PR. ShipCheck is a language- and package-manager-neutral **black-box release probe** for MCP server maintainers. It can complement all three, but it neither analyses patches nor grants agent permissions nor writes a PR. See the cited research and boundary decision in [`docs/research.md`](docs/research.md).

## Known limitations

MVP supports only local stdio JSON-RPC and only the `initialize`/`tools/list` release surface. It does not test remote Streamable HTTP/SSE transports, resources/prompts, pagination, authentication, stateful tool behavior, or full JSON Schema semantics. It cannot prove that a tool is secure or semantically correct; it proves only that the specified server process starts and has a compatible observed handshake/tool contract. Some server commands have startup side effects; execute untrusted commands only in an isolated environment.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
bash demo/run_demo.sh
```

The project targets Python 3.10+ and uses no runtime dependencies outside the standard library. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE).
