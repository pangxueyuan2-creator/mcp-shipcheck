#!/usr/bin/env python3
"""Tiny stdio MCP fixture used by the ShipCheck demo and test suite."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

MODES = [
    "baseline",
    "compatible",
    "breaking",
    "silent",
    "noise",
    "stderr-noise",
    "early-exit",
    "malformed",
    "wrong-id",
    "wrong-protocol",
    "missing-tools",
    "duplicate-names",
    "unicode-name",
    "large-schema",
    "call-trap",
    "require-initialized",
    "secret-stderr",
    "huge-line",
    "non-utf8",
    "int-name",
    "interleaved-notification",
]


def tool(name: str, properties: dict, required: list[str] | None = None, description: str = "") -> dict:
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


def toolset(mode: str) -> list[dict]:
    read = tool("read_note", {"path": {"type": "string"}}, ["path"], "Read a note.")
    search = tool("search_notes", {"query": {"type": "string"}}, ["query"], "Search notes.")
    if mode == "compatible":
        return [read, search, tool("list_notes", {}, None, "List notes.")]
    if mode == "breaking":
        # Removing a public tool and making another input required are both breaking.
        return [tool("read_note", {"path": {"type": "string"}, "format": {"type": "string", "enum": ["text"]}}, ["path", "format"], "Read a note.")]
    if mode == "duplicate-names":
        return [read, dict(read)]
    if mode == "unicode-name":
        return [tool("读取笔记", {"path": {"type": "string"}}, ["path"], "读取一条笔记。")]
    if mode == "large-schema":
        properties = {f"field_{index}": {"type": "string"} for index in range(200)}
        return [tool("bulk_note", properties, ["field_0"], "Large schema.")]
    if mode == "missing-tools":
        return []
    if mode == "int-name":
        return [{"name": 12345, "description": "bad name type", "inputSchema": {}}]
    return [read, search]


def reply(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _log_method(method: object) -> None:
    path = os.environ.get("MCP_SHIPCHECK_METHOD_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{method}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES, default="baseline")
    args = parser.parse_args()
    if args.mode == "early-exit":
        return 7
    if args.mode == "secret-stderr":
        print("API_TOKEN=shipcheck-redteam-secret", file=sys.stderr, flush=True)
        return 7
    if args.mode == "noise":
        print("fixture startup log accidentally on stdout", flush=True)
    if args.mode == "stderr-noise":
        print("fixture diagnostic log on stderr", file=sys.stderr, flush=True)
    if args.mode == "silent":
        time.sleep(30)
        return 0
    initialized = False
    for raw in sys.stdin:
        request = json.loads(raw)
        method = request.get("method")
        request_id = request.get("id")
        _log_method(method)
        if method == "notifications/initialized" or request_id is None:
            if method == "notifications/initialized":
                initialized = True
            continue
        if args.mode == "malformed":
            sys.stdout.write("{not-json\n")
            sys.stdout.flush()
            continue
        if args.mode == "wrong-id":
            reply({"jsonrpc": "2.0", "id": "not-the-request", "result": {}})
            continue
        if method == "initialize":
            if args.mode == "non-utf8":
                sys.stdout.buffer.write(b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"\xff\xfe"}}\n')
                sys.stdout.flush()
                continue
            if args.mode == "huge-line":
                sys.stdout.write(
                    '{"jsonrpc":"2.0","id":%s,"result":{"pad":"%s"}}\n'
                    % (json.dumps(request_id), "x" * 2_000_000)
                )
                sys.stdout.flush()
                continue
            if args.mode == "interleaved-notification":
                reply(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {"level": "info", "data": "warming up"},
                    }
                )
            protocol = "99.99.99" if args.mode == "wrong-protocol" else "2024-11-05"
            reply(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": protocol,
                        "serverInfo": {"name": "fixture-notes", "version": "1.0.0"},
                        "capabilities": {"tools": {}},
                    },
                }
            )
        elif method == "tools/list":
            if args.mode == "require-initialized" and not initialized:
                reply(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32002, "message": "server not initialized"},
                    }
                )
            elif args.mode == "missing-tools":
                reply({"jsonrpc": "2.0", "id": request_id, "result": {}})
            else:
                if args.mode == "interleaved-notification":
                    reply(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/message",
                            "params": {"level": "debug", "data": "listing tools"},
                        }
                    )
                reply({"jsonrpc": "2.0", "id": request_id, "result": {"tools": toolset(args.mode)}})
        elif method == "tools/call":
            reply(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "TOOLS_CALL_EXECUTED"}]},
                }
            )
        else:
            reply({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())