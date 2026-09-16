"""Minimal, side-effect-free stdio MCP release probe.

The probe intentionally never calls tools. It verifies only process startup,
JSON-RPC initialization, and the public tools/list surface.
"""

from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({PROTOCOL_VERSION})
MAX_JSONRPC_LINE = 1_048_576
MAX_TOOL_PAGES = 100
MAX_TOOLS = 10_000
MAX_TOOL_RESULT_BYTES = 16 * 1_048_576


class ShipcheckError(RuntimeError):
    """Base error for expected probe failures."""


class StartupError(ShipcheckError):
    """The requested server command could not be started."""


class ProbeTimeout(ShipcheckError):
    """The server did not return a response before the configured deadline."""


class ProtocolError(ShipcheckError):
    """The server returned malformed JSON-RPC or an error response."""


@dataclass
class _ServerProcess:
    process: subprocess.Popen[bytes]
    leftover: bytearray = field(default_factory=bytearray)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _canonical(value: Any) -> Any:
    """Return a deterministically ordered JSON-compatible value."""
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _read_available(stream: Any, size: int, timeout: float) -> bytes | None:
    """Read up to ``size`` bytes with a portable timeout.

    ``select.select`` is not defined for Windows pipes and raises OSError
    (WinError 10038 / 10093). A worker thread plus ``queue.Queue.get``
    works on POSIX and Windows. ``None`` means timeout.
    """

    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=1)

    def reader() -> None:
        try:
            data = stream.read1(size) if hasattr(stream, "read1") else stream.read(size)
            chunks.put(b"" if data is None else data)
        except OSError:
            chunks.put(None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        return chunks.get(timeout=timeout)
    except queue.Empty:
        return None


def _readline(server: _ServerProcess, timeout: float) -> str:
    """Read one stdout JSON-RPC line, bounded to ``MAX_JSONRPC_LINE`` bytes."""

    process = server.process
    if process.stdout is None:
        raise ProtocolError("server stdout is unavailable")
    leftover = server.leftover
    deadline = time.monotonic() + timeout
    while True:
        newline = leftover.find(b"\n")
        if newline != -1:
            raw = bytes(leftover[:newline])
            del leftover[: newline + 1]
            if len(raw) > MAX_JSONRPC_LINE:
                raise ProtocolError(f"JSON-RPC line exceeds {MAX_JSONRPC_LINE} bytes")
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ProtocolError("server wrote non-UTF-8 output to stdout") from None
        if len(leftover) > MAX_JSONRPC_LINE:
            raise ProtocolError(f"JSON-RPC line exceeds {MAX_JSONRPC_LINE} bytes")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if process.poll() is not None:
                raise StartupError(f"server exited before responding (exit {process.returncode})")
            raise ProbeTimeout(f"no JSON-RPC response within {timeout:.2f}s") from None
        chunk = _read_available(process.stdout, 65_536, remaining)
        if chunk is None:
            if process.poll() is not None:
                raise StartupError(f"server exited before responding (exit {process.returncode})")
            raise ProbeTimeout(f"no JSON-RPC response within {timeout:.2f}s") from None
        if not chunk:
            raise StartupError("server closed stdout before responding")
        leftover.extend(chunk)


def _write(process: subprocess.Popen[bytes], payload: dict[str, Any], timeout: float) -> None:
    if process.stdin is None:
        raise StartupError("server stdin is unavailable")
    stream = process.stdin
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    completed: queue.Queue[bool] = queue.Queue(maxsize=1)

    def writer() -> None:
        try:
            pending = memoryview(data)
            while pending:
                written = stream.write(pending)
                if not written:
                    raise OSError("server stdin did not accept data")
                pending = pending[written:]
            stream.flush()
            completed.put(True)
        except (OSError, ValueError):
            completed.put(False)

    # A returned opaque cursor can be larger than the pipe buffer. A server
    # that stops reading must not defeat the catalog deadline with a blocked write.
    threading.Thread(target=writer, daemon=True).start()
    try:
        success = completed.get(timeout=timeout)
    except queue.Empty:
        raise ProbeTimeout("server did not read the JSON-RPC request before the deadline") from None
    if not success:
        raise StartupError("could not write to server")


def _request(
    server: _ServerProcess, request_id: int, method: str, params: dict[str, Any], timeout: float
) -> dict[str, Any]:
    process = server.process
    deadline = time.monotonic() + timeout
    _write(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, timeout)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeTimeout(f"no JSON-RPC response within {timeout:.2f}s")
        raw = _readline(server, remaining)
        try:
            response = json.loads(raw)
        except json.JSONDecodeError:
            # Server output may contain opaque cursors or credentials.
            raise ProtocolError("server wrote non-JSON output to stdout") from None
        if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
            raise ProtocolError("server response is not a JSON-RPC 2.0 object")
        if "id" not in response and "method" in response:
            notification_method = response.get("method")
            if not isinstance(notification_method, str) or not notification_method:
                raise ProtocolError("server notification has an invalid method")
            continue
        if response.get("id") != request_id:
            raise ProtocolError("server response id does not match request id")
        if "error" in response:
            raise ProtocolError(f"{method} returned JSON-RPC error")
        if "result" not in response or not isinstance(response["result"], dict):
            raise ProtocolError(f"{method} returned no object result")
        return response["result"]


def _normalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema", {})
    if not isinstance(schema, dict):
        schema = {"_invalidInputSchema": True}
    normalized: dict[str, Any] = {"name": tool.get("name", "")}
    if "description" in tool:
        normalized["description"] = tool["description"]
    normalized["inputSchema"] = _canonical(schema)
    return normalized


def _list_tools(server: _ServerProcess, timeout: float) -> list[dict[str, Any]]:
    """Collect a complete catalog, or fail without returning a partial surface.

    The timeout covers the entire listing, not each page independently. Cursors
    remain opaque and in memory only; even an empty cursor requests another page.
    """
    deadline = time.monotonic() + timeout
    params: dict[str, Any] = {}
    cursors: set[str] = set()
    names: set[str] = set()
    tools: list[dict[str, Any]] = []
    result_bytes = 0
    for page in range(MAX_TOOL_PAGES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeTimeout("tools/list exceeded the catalog timeout")
        result = _request(server, page + 2, "tools/list", params, remaining)
        result_bytes += len(json.dumps(result, ensure_ascii=True).encode("utf-8"))
        if result_bytes > MAX_TOOL_RESULT_BYTES:
            raise ProtocolError("tools/list exceeds the catalog byte limit")
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list) or not all(isinstance(tool, dict) for tool in raw_tools):
            raise ProtocolError("tools/list result has no tools array")
        if len(tools) + len(raw_tools) > MAX_TOOLS:
            raise ProtocolError("tools/list exceeds the tool count limit")
        for tool in raw_tools:
            name = tool.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProtocolError("tools/list contains a tool without a non-empty string name")
            if name in names:
                raise ProtocolError("tools/list contains duplicate tool names")
            names.add(name)
            tools.append(_normalize_tool(tool))
        if "nextCursor" not in result:
            return sorted(tools, key=lambda tool: tool["name"])
        cursor = result["nextCursor"]
        if not isinstance(cursor, str):
            raise ProtocolError("tools/list nextCursor must be a string when present")
        if cursor in cursors:
            raise ProtocolError("tools/list contains a repeated pagination cursor")
        cursors.add(cursor)
        params = {"cursor": cursor}
    raise ProtocolError("tools/list exceeds the page count limit")


def probe_command(command: Iterable[str], timeout: float = 5.0) -> dict[str, Any]:
    """Probe a stdio MCP server and return a JSON-serializable release snapshot.

    ``command`` is executed without a shell. Only initialize, the initialized
    notification, and tools/list are requested; no tool calls, environment
    values, request arguments, or tool outputs are captured. Server stderr is
    discarded and is never included in probe errors.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a finite positive number")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    argv = list(command)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        raise StartupError("a server command is required after '--'")
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
            bufsize=0,
            env=os.environ.copy(),
        )
    except OSError as exc:
        raise StartupError(f"could not start {argv[0]!r}: {exc}") from exc
    server = _ServerProcess(process)
    try:
        initialize = _request(
            server,
            1,
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-shipcheck", "version": "0.1.0"},
            },
            timeout,
        )
        protocol_version = initialize.get("protocolVersion", PROTOCOL_VERSION)
        if not isinstance(protocol_version, str) or not protocol_version:
            raise ProtocolError("initialize protocolVersion is not a non-empty string")
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ProtocolError(f"unsupported initialize protocolVersion: {protocol_version!r}")
        _write(
            process,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout,
        )
        tools = _list_tools(server, timeout)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "format": "mcp-shipcheck/v1",
            "protocolVersion": protocol_version,
            "serverInfo": _canonical(initialize.get("serverInfo", {})),
            "capabilities": _canonical(initialize.get("capabilities", {})),
            "tools": tools,
            "probe": {
                "method": "stdio",
                "toolCallsExecuted": 0,
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "durationMs": elapsed_ms,
            },
        }
    finally:
        server.close()
