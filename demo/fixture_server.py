#!/usr/bin/env python3
"""Tiny stdio MCP fixture used by the ShipCheck demo and test suite."""

from __future__ import annotations

import argparse
import json
import sys
import time


def tool(name: str, properties: dict, required: list[str] | None = None, description: str = "") -> dict:
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


def toolset(mode: str) -> list[dict]:
    read = tool("read_note", {"path": {"type": "string"}}, ["path"], "Read a note.")
    search = tool("search_notes", {"query": {"type": "string"}}, ["query"], "Search notes.")
    if mode == "baseline":
        return [read, search]
    if mode == "compatible":
        return [read, search, tool("list_notes", {}, None, "List notes.")]
    if mode == "breaking":
        # Removing a public tool and making another input required are both breaking.
        return [tool("read_note", {"path": {"type": "string"}, "format": {"type": "string", "enum": ["text"]}}, ["path", "format"], "Read a note.")]
    return [read]


def reply(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "compatible", "breaking", "silent", "noise"], default="baseline")
    args = parser.parse_args()
    if args.mode == "noise":
        print("fixture startup log accidentally on stdout", flush=True)
    if args.mode == "silent":
        time.sleep(30)
        return 0
    for raw in sys.stdin:
        request = json.loads(raw)
        method = request.get("method")
        request_id = request.get("id")
        if method == "initialize":
            reply({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "fixture-notes", "version": "1.0.0"}, "capabilities": {"tools": {}}}})
        elif method == "tools/list":
            reply({"jsonrpc": "2.0", "id": request_id, "result": {"tools": toolset(args.mode)}})
        else:
            reply({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
