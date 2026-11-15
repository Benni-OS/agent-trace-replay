# agent-trace-replay Architecture

`agent-trace-replay` is organized into three clean architectural layers matching the Benni OS v9.4 Python OSS standard:

## 1. `core/` — Deterministic Trajectory & Cryptography Layer
- `core/models.py`: Canonical `TraceEvent`, `EventType`, `GENESIS_HASH`, `compute_event_hash()`, and `verify_trace_chain()` implementing SHA-256 hash-chained event ledgers.
- `core/recorder.py`: `TraceRecorder` (deterministic RNG seed, monotonic or deterministic clock, cumulative state snapshots) and `TraceStore` (local JSONL and SQLite3 persistence).
- `core/replayer.py`: `TraceReplayer` for `$0.00` offline deterministic replay, schema/output drift detection, and step-by-step time-travel (`inspect_step`, `step_through`).
- `core/forker.py`: `CounterfactualForker` for branching any trajectory at step `N` with `ForkOverride`, resealing the downstream SHA-256 chain, and computing `TrajectoryDiff`.

## 2. `serve/` — MCP Transport, Telemetry & Health Monitoring
- `serve/mcp_server.py`: Zero-dependency JSON-RPC 2.0 stdio MCP server exposing `trace_inspect`, `trace_replay`, `trace_fork`, and `trace_diff`.
- `serve/telemetry.py`: `TraceTelemetryEngine` tracking replay/fork P50/P90/P99 latencies, steps/sec, saved token volume, and drift violations.
- `serve/health_monitor.py`: `TraceHealthMonitor` verifying local disk headroom, SQLite3 readiness, and live SHA-256 chain self-tests.

## 3. `tools/` — Diagnostics & Benchmark Matrix
- `tools/doctor.py`: `run_doctor()` and `trace-replay doctor` CLI probe.
- `tools/bench_matrix.py`: `TraceBenchMatrixRunner` and `trace-replay matrix` CLI sweep across `[10, 50, 100, 500]` step trajectories.
