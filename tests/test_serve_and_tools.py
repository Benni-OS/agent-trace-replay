"""Tests for core/serve/tools subpackages in agent-trace-replay."""

from __future__ import annotations

import json

from agent_trace_replay.cli import main as cli_main
from agent_trace_replay.core import create_demo_trace
from agent_trace_replay.serve import TraceHealthMonitor, TraceTelemetryEngine
from agent_trace_replay.tools import TraceBenchMatrixRunner, run_doctor


def test_telemetry_engine_records_replay_and_fork() -> None:
    tel = TraceTelemetryEngine(max_history=10)
    tel.record_replay(
        latency_ms=1.25,
        steps_count=7,
        tokens_saved=1200,
        drift_count=0,
        chain_valid=True,
        event_types=["seed_init", "llm_call", "tool_call"],
    )
    tel.record_fork(latency_ms=0.85)
    summary = tel.get_summary()

    assert summary["total_replays"] == 1
    assert summary["total_forks"] == 1
    assert summary["total_steps_replayed"] == 7
    assert summary["total_tokens_saved"] == 1200
    assert summary["replay_latency_ms"]["p50"] == 1.25
    assert summary["fork_latency_ms"]["p50"] == 0.85
    assert summary["event_type_distribution"]["llm_call"] == 1


def test_health_monitor_and_doctor() -> None:
    monitor = TraceHealthMonitor()
    health = monitor.check_health()
    assert health["status"] == "healthy"
    assert health["sqlite"]["available"] is True
    assert health["sha256_self_test"]["passed"] is True

    report = run_doctor()
    assert report["ok"] is True
    assert report["pipeline_probe"]["replay_passed"] is True
    assert report["pipeline_probe"]["fork_chain_valid"] is True


def test_bench_matrix_runner() -> None:
    runner = TraceBenchMatrixRunner(step_counts=[5, 10], reps=2)
    res = runner.run_matrix()
    assert res["reps"] == 2
    assert len(res["matrix"]) == 2
    assert res["matrix"][0]["steps"] == 5
    assert res["matrix"][1]["steps"] == 10
    assert res["matrix"][0]["token_burn_usd"] == 0.0


def test_cli_doctor_and_matrix_json(capsys) -> None:
    rc_doc = cli_main(["doctor", "--json"])
    assert rc_doc == 0
    doc_payload = json.loads(capsys.readouterr().out)
    assert doc_payload["ok"] is True

    rc_mat = cli_main(["matrix", "--steps", "5", "10", "--reps", "1", "--json"])
    assert rc_mat == 0
    mat_payload = json.loads(capsys.readouterr().out)
    assert len(mat_payload["matrix"]) == 2
