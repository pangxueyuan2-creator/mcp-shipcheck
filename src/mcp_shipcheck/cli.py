"""Command-line interface for MCP ShipCheck."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .compare import compare_snapshots
from .probe import ShipcheckError, probe_command


def _read_snapshot(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read snapshot {path!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"snapshot {path!r} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != "mcp-shipcheck/v1":
        raise ValueError(f"snapshot {path!r} is not an mcp-shipcheck/v1 snapshot")
    return value


def _write_json(value: dict[str, Any], output: str | None) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


def _verify(args: argparse.Namespace) -> int:
    if not args.command:
        raise ValueError("verify requires a server command after '--'")
    snapshot = probe_command(args.command, timeout=args.timeout)
    _write_json(snapshot, args.output)
    if args.baseline:
        result = compare_snapshots(_read_snapshot(args.baseline), snapshot)
        if args.compare_output:
            _write_json(result, args.compare_output)
        if not result["compatible"]:
            print(f"mcp-shipcheck: {result['summary']['breaking']} breaking change(s)", file=sys.stderr)
            return 2
    return 0


def _compare(args: argparse.Namespace) -> int:
    result = compare_snapshots(_read_snapshot(args.baseline), _read_snapshot(args.candidate))
    _write_json(result, args.output)
    if not result["compatible"]:
        print(f"mcp-shipcheck: {result['summary']['breaking']} breaking change(s)", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-shipcheck",
        description="Probe a released stdio MCP server without executing any tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    verify = subparsers.add_parser("verify", help="start a server, initialize it, and snapshot tools/list")
    verify.add_argument("--timeout", type=float, default=5.0, help="per-request timeout in seconds (default: 5)")
    verify.add_argument("--output", required=True, help="path for the generated snapshot JSON")
    verify.add_argument("--baseline", help="optional prior snapshot; exits 2 for breaking changes")
    verify.add_argument("--compare-output", help="optional path for the comparison JSON")
    verify.add_argument("command", nargs=argparse.REMAINDER, help="server command after '--'")
    verify.set_defaults(handler=_verify)

    compare = subparsers.add_parser("compare", help="compare two existing release snapshots")
    compare.add_argument("baseline", help="trusted baseline snapshot JSON")
    compare.add_argument("candidate", help="candidate snapshot JSON")
    compare.add_argument("--output", help="path for comparison JSON; defaults to stdout")
    compare.set_defaults(handler=_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ShipcheckError, ValueError) as exc:
        print(f"mcp-shipcheck: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
