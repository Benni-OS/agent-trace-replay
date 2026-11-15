<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0D0D0D,50:1a1a2e,100:00B4D8&height=200&section=header&text=agent-trace-replay&fontSize=52&fontColor=ffffff&fontAlignY=38&desc=Zero-Cloud%20Time-Travel%20Debugger%2C%20Deterministic%20Trajectory%20Replay%20%26%20Counterfactual%20Forking&descAlignY=58&descSize=15&animation=fadeIn" width="100%"/>

<br/>

[![Tests](https://img.shields.io/badge/Tests-15%20Passed-00C853?style=for-the-badge&logo=pytest&logoColor=white)](#-quickstart)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-00B4D8?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-JSON--RPC%202.0-8a2be2?style=for-the-badge)](https://modelcontextprotocol.io/)
[![Replay Cost](https://img.shields.io/badge/Replay%20Burn-%240.00%20Offline-00C853?style=for-the-badge)](#-architectural-benchmark-cloud-observability-vs-agent-trace-replay)
[![Integrity](https://img.shields.io/badge/Integrity-SHA--256%20Chained-7000FF?style=for-the-badge)](#-architecture)
[![License: MIT](https://img.shields.io/badge/License-MIT-00C853?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Benni OS](https://img.shields.io/badge/Benni%20OS-benni--os.net-0D0D0D?style=for-the-badge)](https://benni-os.net)

<br/>

> **Zero-Cloud Time-Travel Debugger, Deterministic Trajectory Replay & Counterfactual Forking for AI Agents & MCP.**  
> Zero external LLM token burn. Zero telemetry leaks. Cryptographic SHA-256 event chains. Branch from any step `N` and diff trajectories in `< 1ms`.

<br/>

<img src="assets/demo.gif" alt="agent-trace-replay DAG telemetry demo" width="100%"/>

</div>

---

## ⚡ The Problem: Why Debugging AI Agents in Production Breaks

When an autonomous agent fails at step 14 of a 20-step MCP workflow, re-running the entire trajectory from scratch is slow, expensive, and non-deterministic:

1. **Cloud Telemetry Lock-In & Data Exfiltration:** Platforms like `LangSmith`, `Arize Phoenix`, and `AgentOps` ship sensitive prompts, tool arguments, and proprietary codebases to external cloud SaaS or heavy OpenTelemetry collectors.
2. **Repeated LLM Token Burn During Debugging:** Re-running a multi-step agent loop just to reproduce a bug at step 14 burns fresh GPT-4 / Claude tokens on steps 1–13 every single time.
3. **No Counterfactual Branching ("What If Step N Returned X?"):** Existing observability tools are read-only trace viewers—you cannot fork from step `N`, inject a modified tool output or prompt variant, and measure the exact structural, token, and latency delta.
4. **No Cryptographic Tamper Proofing:** Plain JSON logs can be silently mutated without breaking integrity checks, making post-mortem audits unreliable.

---

## 🏆 Architectural Benchmark: Cloud Observability vs `agent-trace-replay`

| Feature / Metric | `LangSmith` | `Arize Phoenix` | `AgentOps` | `agent-trace-replay` (Benni OS) |
| :--- | :---: | :---: | :---: | :---: |
| **Telemetry Privacy** | ❌ Cloud SaaS | ⚠️ Local / Cloud OTEL Server | ❌ Cloud SaaS | **✅ 100% Zero-Cloud (JSONL / SQLite)** |
| **Replay Token Cost** | Paid re-execution | Read-only viewer | Read-only viewer | **✅ $0.00 (Offline Deterministic Stubs)** |
| **Counterfactual Forking** | ⚠️ Manual playground | ❌ No | ❌ No | **✅ Branch at Step N + Structural Diff** |
| **Integrity Verification** | ❌ Mutable logs | ❌ Mutable spans | ❌ Mutable events | **✅ SHA-256 Chained Event Ledger** |
| **Runtime Dependencies** | Heavy SDK + API key | Heavy OTEL + SQL/Server | Heavy SDK + API key | **✅ Pure Python 3.10+ (Zero Dependencies)** |
| **Native MCP Server** | ❌ No | ❌ No | ❌ No | **✅ Built-in JSON-RPC 2.0 stdio** |

---

## 🧱 Architecture

```text
  [Agent / MCP Run]
         │
         ▼
  TraceRecorder ──► SHA-256 Chained Events (seed, LLM, MCP tool, state_snapshot)
         │
         ├──► TraceStore (Local JSONL / SQLite)
         │
         ├──► TraceReplayer ──► Offline $0.00 Replay + Schema/Drift Detection + Time-Travel
         │
         └──► CounterfactualForker ──► Branch at Step N ──► Structural, Token & Latency Diff
                                                                      │
                                                                      ▼
                                                           MCPServer (JSON-RPC 2.0 stdio)
```

- `recorder.py`: Captures `seed_init`, `llm_call`, `tool_call`, and `state_snapshot` spans with deterministic RNG/timestamps and chains every event with `SHA-256(canonical_json + prev_hash)` into local **JSONL** or **SQLite**.
- `replayer.py`: Replays recorded trajectories offline with `$0.00` token burn against recorded tapes or custom tool/LLM stubs, flags schema/output drift, verifies the SHA-256 chain, and supports step-by-step time-travel (`inspect_step`, `step_through`).
- `forker.py`: Forks any trajectory at step `N` with modified tool outputs, prompt variants, or downstream simulators, reseals the new SHA-256 chain, and computes a `TrajectoryDiff` (identical, modified, diverged, added/removed steps, token & latency deltas).
- `mcp_server.py`: Native zero-dependency JSON-RPC 2.0 stdio MCP server exposing `trace_inspect`, `trace_replay`, `trace_fork`, and `trace_diff`.

---

## 🚀 Quickstart

### 1. Installation

```bash
pip install -e .
```

### 2. Record, Time-Travel Inspect, Replay & Fork via CLI

```bash
# 1. Record a deterministic 7-step AI agent + MCP demo trajectory
trace-replay record-demo --out .traces/demo.jsonl

# 2. Time-travel inspect step 2 (verify SHA-256 hash & cumulative state)
trace-replay inspect .traces/demo.jsonl --seq 2

# 3. Replay offline with $0.00 token burn and drift detection
trace-replay replay .traces/demo.jsonl

# 4. Counterfactual fork from step 5 with a simulated test failure
trace-replay fork .traces/demo.jsonl --seq 5 \
  --output-override '{"passed": 11, "failed": 1, "status": "fail"}' \
  --out .traces/demo.fork5.jsonl

# 5. Diff base vs counterfactual fork
trace-replay diff .traces/demo.jsonl .traces/demo.fork5.jsonl
```

### 3. Run Verification Tests

```bash
pytest -v
```

---

## 🏗️ Model Context Protocol (MCP) Integration

`agent-trace-replay` ships with a native JSON-RPC 2.0 stdio MCP server for **Claude Desktop, Claude Code, Cursor, Windsurf, and Cline**.

Add to your `claude_desktop_config.json` or `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "agent-trace-replay": {
      "command": "trace-replay",
      "args": ["mcp"]
    }
  }
}
```

Exposed MCP tools:
- `trace_inspect` — Time-travel inspect a trajectory or jump to step `seq` with SHA-256 verification.
- `trace_replay` — Deterministic offline replay with `$0.00` token burn and drift detection.
- `trace_fork` — Counterfactual branch from step `fork_seq` with modified tool output or prompt variant.
- `trace_diff` — Structural, token, and latency diff between base and forked trajectories.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
