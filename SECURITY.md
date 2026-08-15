# Security Policy

## Supported versions

The current `0.1.x` line is supported with security fixes. Earlier releases are unsupported.

## Reporting a vulnerability

Please do **not** file public issues for suspected vulnerabilities. Use GitHub's private vulnerability reporting flow for this repository, or contact the maintainer through the repository owner profile with a minimal reproduction and impact summary. Reports are acknowledged within seven days when possible.

## Security boundary

MCP ShipCheck starts a command that **you explicitly supply** and sends only `initialize` and `tools/list` JSON-RPC requests. It never calls MCP tools, but starting an untrusted executable can still have side effects. Run checks in an isolated CI job or disposable environment when the package or command is not trusted.

Snapshots intentionally omit request arguments, environment variables, tool results, and stderr. They may still reveal public tool names, descriptions, server metadata, and JSON schemas. Do not publish a snapshot if those fields are sensitive in your deployment.
