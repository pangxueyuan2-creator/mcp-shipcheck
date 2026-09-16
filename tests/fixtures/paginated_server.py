"""Scripted real stdio server; rejects unexpected cursors, IDs, and tool calls."""
import json
from pathlib import Path
import sys
import time

pages = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
log = Path(sys.argv[2])
index = 0
expected_cursor = None
for line in sys.stdin:
    request = json.loads(line)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(request) + "\n")
    method = request["method"]
    response = {"jsonrpc": "2.0", "id": request.get("id")}
    if method == "initialize":
        response["result"] = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "pagination-fixture", "version": "1"},
            "capabilities": {"tools": {}},
        }
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        assert request["id"] == index + 2
        expected = {} if index == 0 else {"cursor": expected_cursor}
        assert request["params"] == expected
        page = pages[index]
        time.sleep(page.get("delay", 0))
        if page.get("notification"):
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}), flush=True)
        if "raw" in page:
            print(page["raw"], flush=True)
            continue
        if page.get("exit"):
            raise SystemExit(3)
        if "error" in page:
            response["error"] = {"code": -32602, "message": page["error"]}
        else:
            response["result"] = page["result"]
            expected_cursor = page["result"].get("nextCursor")
        index += 1
    else:
        raise AssertionError("unexpected method: " + method)
    print(json.dumps(response), flush=True)
    if method == "tools/list":
        time.sleep(page.get("after_response_delay", 0))
