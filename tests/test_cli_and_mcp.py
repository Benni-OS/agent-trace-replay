"""Integration tests for the `trace-replay` CLI and JSON-RPC 2.0 MCP server."""

import io
import json
from pathlib import Path

from agent_trace_replay.cli import main as cli_main
from agent_trace_replay.mcp_server import MCPServer


def test_cli_end_to_end_workflow(tmp_path: Path, capsys):
    trace_path = tmp_path / "demo.jsonl"
    fork_path = tmp_path / "demo.fork.jsonl"

    assert cli_main(["record-demo", "--out", str(trace_path), "--seed", "7"]) == 0
    assert trace_path.exists()
    capsys.readouterr()

    assert cli_main(["inspect", str(trace_path), "--seq", "2", "--json"]) == 0
    insp_out = json.loads(capsys.readouterr().out)
    assert insp_out["seq"] == 2
    assert insp_out["hash_valid"] is True

    assert cli_main(["replay", str(trace_path), "--json"]) == 0
    rep_out = json.loads(capsys.readouterr().out)
    assert rep_out["zero_token_burn"] is True
    assert rep_out["chain_valid"] is True
    assert rep_out["drift_detected"] is False

    assert (
        cli_main(
            [
                "fork",
                str(trace_path),
                "--seq",
                "1",
                "--prompt-override",
                "Check SQL injection instead",
                "--out",
                str(fork_path),
                "--json",
            ]
        )
        == 0
    )
    fork_out = json.loads(capsys.readouterr().out)
    assert fork_out["fork_seq"] == 1
    assert fork_path.exists()

    assert cli_main(["diff", str(trace_path), str(fork_path), "--json"]) == 0
    diff_out = json.loads(capsys.readouterr().out)
    assert diff_out["identical_steps"] == 1
    assert diff_out["modified_steps"] == 1


def test_mcp_server_jsonrpc_lifecycle_and_all_tools(tmp_path: Path):
    trace_path = tmp_path / "mcp_demo.jsonl"
    cli_main(["record-demo", "--out", str(trace_path)])

    server = MCPServer()

    init_resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_resp["result"]["serverInfo"]["name"] == "agent-trace-replay"

    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    list_resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_names = {t["name"] for t in list_resp["result"]["tools"]}
    assert tool_names == {"trace_inspect", "trace_replay", "trace_fork", "trace_diff"}

    # trace_inspect
    r_insp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "trace_inspect", "arguments": {"trace_path": str(trace_path), "seq": 5}},
        }
    )
    insp_data = json.loads(r_insp["result"]["content"][0]["text"])
    assert insp_data["name"] == "mcp:run_tests"
    assert insp_data["chain_valid"] is True

    # trace_replay
    r_rep = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "trace_replay", "arguments": {"trace_path": str(trace_path)}},
        }
    )
    rep_data = json.loads(r_rep["result"]["content"][0]["text"])
    assert rep_data["zero_token_burn"] is True
    assert rep_data["drift_detected"] is False

    # trace_fork
    fork_path = tmp_path / "mcp_fork.jsonl"
    r_fork = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "trace_fork",
                "arguments": {
                    "trace_path": str(trace_path),
                    "fork_seq": 5,
                    "new_output": {"passed": 11, "failed": 1, "status": "fail"},
                    "out_path": str(fork_path),
                },
            },
        }
    )
    fork_data = json.loads(r_fork["result"]["content"][0]["text"])
    assert fork_data["fork_seq"] == 5
    assert fork_path.exists()

    # trace_diff
    r_diff = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "trace_diff",
                "arguments": {"base_path": str(trace_path), "fork_path": str(fork_path)},
            },
        }
    )
    diff_data = json.loads(r_diff["result"]["content"][0]["text"])
    assert diff_data["identical_steps"] == 5

    # Unknown method returns -32601
    r_err = server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "unknown/method"})
    assert r_err["error"]["code"] == -32601


def test_mcp_serve_stdio_stream():
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        + "{invalid json\n"
    )
    stdout = io.StringIO()
    MCPServer().serve_stdio(stdin=stdin, stdout=stdout)
    lines = [json.loads(line) for line in stdout.getvalue().strip().splitlines()]
    assert lines[0]["id"] == 1
    assert lines[0]["result"] == {}
    assert lines[1]["error"]["code"] == -32700
