"""Minimal, side-effect-free stdio MCP release probe.

The probe intentionally never calls tools. It verifies only process startup,
JSON-RPC initialization, and the public tools/list surface.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

PROTOCOL_VERSION = "2024-11-05"
MAX_JSONRPC_LINE = 1_048_576


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
            return raw.decode("utf-8")
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


def _write(process: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise StartupError("server stdin is unavailable")
    try:
        process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise StartupError(f"could not write to server: {exc}") from exc


def _request(
    server: _ServerProcess, request_id: int, method: str, params: dict[str, Any], timeout: float
) -> dict[str, Any]:
    process = server.process
    _write(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    raw = _readline(server, timeout)
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"server wrote non-JSON output to stdout: {raw[:160].strip()!r}") from exc
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
        raise ProtocolError("server response is not a JSON-RPC 2.0 object")
    if response.get("id") != request_id:
        raise ProtocolError(f"server response id {response.get('id')!r} does not match request id {request_id}")
    if "error" in response:
        error = response["error"]
        message = error.get("message", "unknown error") if isinstance(error, dict) else str(error)
        raise ProtocolError(f"{method} returned JSON-RPC error: {message}")
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


def probe_command(command: Iterable[str], timeout: float = 5.0) -> dict[str, Any]:
    """Probe a stdio MCP server and return a JSON-serializable release snapshot.

    ``command`` is executed without a shell. Only initialize, the initialized
    notification, and tools/list are requested; no tool calls, environment
    values, request arguments, or tool outputs are captured. Server stderr is
    discarded and is never included in probe errors.
    """
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
        _write(
            process,
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        tools_result = _request(server, 2, "tools/list", {}, timeout)
        if "tools" not in tools_result:
            raise ProtocolError("tools/list result has no tools array")
        raw_tools = tools_result.get("tools")
        if not isinstance(raw_tools, list) or not all(isinstance(tool, dict) for tool in raw_tools):
            raise ProtocolError("tools/list result has no tools array")
        names = [str(tool.get("name", "")) for tool in raw_tools]
        if len(names) != len(set(names)):
            raise ProtocolError("tools/list contains duplicate tool names")
        tools = sorted((_normalize_tool(tool) for tool in raw_tools), key=lambda tool: tool["name"])
        if any(not tool["name"] for tool in tools):
            raise ProtocolError("tools/list contains a tool without a non-empty name")
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
