"""Native zero-dependency JSON-RPC 2.0 stdio MCP server for agent-trace-replay."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from ..core.forker import CounterfactualForker, ForkOverride
from ..core.models import verify_trace_chain
from ..core.recorder import TraceStore
from ..core.replayer import TraceReplayer

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "agent-trace-replay", "version": "0.1.0"}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "trace_inspect",
        "description": "Time-travel inspect a recorded AI agent trajectory (JSONL or SQLite), optionally jumping to step seq.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_path": {"type": "string", "description": "Path to .jsonl or .sqlite trace file."},
                "seq": {"type": "integer", "description": "Optional step index to inspect in detail."},
                "trace_id": {"type": "string", "description": "Optional trace_id when reading from SQLite."},
            },
            "required": ["trace_path"],
        },
    },
    {
        "name": "trace_replay",
        "description": "Offline zero-token-burn deterministic replay of a recorded trajectory with SHA-256 chain verification.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_path": {"type": "string", "description": "Path to .jsonl or .sqlite trace file."},
                "verify_chain": {"type": "boolean", "default": True},
                "strict": {"type": "boolean", "default": False},
                "trace_id": {"type": "string", "description": "Optional trace_id when reading from SQLite."},
            },
            "required": ["trace_path"],
        },
    },
    {
        "name": "trace_fork",
        "description": "Counterfactual fork from step N with modified tool output or prompt variant, saving the forked trace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_path": {"type": "string", "description": "Path to base .jsonl or .sqlite trace file."},
                "fork_seq": {"type": "integer", "description": "Step index N to branch from."},
                "new_output": {"type": "object", "description": "Optional modified output_data dict at step N."},
                "new_prompt": {"type": "string", "description": "Optional modified prompt string at step N."},
                "out_path": {"type": "string", "description": "Optional output path for the forked trace."},
            },
            "required": ["trace_path", "fork_seq"],
        },
    },
    {
        "name": "trace_diff",
        "description": "Compute structural, token, and latency diff between a base trajectory and a forked trajectory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_path": {"type": "string", "description": "Path to base trace file."},
                "fork_path": {"type": "string", "description": "Path to forked trace file."},
            },
            "required": ["base_path", "fork_path"],
        },
    },
]


class MCPServer:
    """Zero-dependency JSON-RPC 2.0 MCP server exposing time-travel debugging tools."""

    def __init__(self) -> None:
        self.initialized = False

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process a single JSON-RPC 2.0 message and return a response dict (or None for notifications)."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        if method == "notifications/initialized":
            self.initialized = True
            return None

        if method == "initialize":
            self.initialized = True
            return self._ok(
                req_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                },
            )

        if method == "ping":
            return self._ok(req_id, {})

        if method == "tools/list":
            return self._ok(req_id, {"tools": TOOL_DEFINITIONS})

        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            try:
                result = self._dispatch_tool(name, args)
                return self._ok(
                    req_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
                        "isError": False,
                    },
                )
            except Exception as exc:
                return self._ok(
                    req_id,
                    {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                )

        if req_id is None:
            return None
        return self._err(req_id, -32601, f"Method not found: {method}")

    def _dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "trace_inspect":
            events = TraceStore.load_auto(args["trace_path"], trace_id=args.get("trace_id"))
            chain_valid, chain_errors = verify_trace_chain(events)
            replayer = TraceReplayer(events)
            if "seq" in args and args["seq"] is not None:
                step_info = replayer.inspect_step(int(args["seq"]))
                step_info["chain_valid"] = chain_valid
                return step_info
            return {
                "trace_id": events[0].trace_id if events else "empty",
                "total_steps": len(events),
                "chain_valid": chain_valid,
                "chain_errors": chain_errors,
                "total_tokens": sum(e.tokens_in + e.tokens_out for e in events),
                "total_duration_ms": round(sum(e.duration_ms for e in events), 3),
                "steps": [
                    {
                        "seq": e.seq,
                        "event_type": e.event_type,
                        "name": e.name,
                        "tokens": e.tokens_in + e.tokens_out,
                        "duration_ms": e.duration_ms,
                    }
                    for e in events
                ],
            }

        if name == "trace_replay":
            events = TraceStore.load_auto(args["trace_path"], trace_id=args.get("trace_id"))
            replayer = TraceReplayer(events)
            res = replayer.replay(
                verify_chain=bool(args.get("verify_chain", True)),
                strict=bool(args.get("strict", False)),
            )
            return res.to_dict()

        if name == "trace_fork":
            events = TraceStore.load_auto(args["trace_path"])
            fork_seq = int(args["fork_seq"])
            override = ForkOverride(
                seq=fork_seq,
                new_output=args.get("new_output"),
                new_prompt=args.get("new_prompt"),
            )
            fork_res = CounterfactualForker.fork(events, override)
            out_path = args.get("out_path")
            if not out_path:
                src = Path(args["trace_path"])
                out_path = str(src.with_name(f"{src.stem}.fork-{fork_seq}{src.suffix}"))
            saved = TraceStore.save_auto(fork_res.events, out_path)
            payload = fork_res.to_dict()
            payload["saved_path"] = str(saved)
            return payload

        if name == "trace_diff":
            base_events = TraceStore.load_auto(args["base_path"])
            fork_events = TraceStore.load_auto(args["fork_path"])
            diff_res = CounterfactualForker.diff(base_events, fork_events)
            return diff_res.to_dict()

        raise ValueError(f"Unknown tool: {name}")

    @staticmethod
    def _ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def serve_stdio(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        """Run the blocking JSON-RPC 2.0 stdio loop."""
        in_stream = stdin or sys.stdin
        out_stream = stdout or sys.stdout

        for line in in_stream:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                msg = json.loads(stripped)
            except json.JSONDecodeError as exc:
                err_resp = self._err(None, -32700, f"Parse error: {exc}")
                out_stream.write(json.dumps(err_resp) + "\n")
                out_stream.flush()
                continue

            resp = self.handle_request(msg)
            if resp is not None:
                out_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
                out_stream.flush()
