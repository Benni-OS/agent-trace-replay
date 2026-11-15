"""Tests for TraceReplayer: offline zero-token-burn replay, drift detection, and time-travel."""

import pytest

from agent_trace_replay.recorder import create_demo_trace
from agent_trace_replay.replayer import TraceReplayer


def test_offline_zero_token_burn_replay():
    events = create_demo_trace()
    replayer = TraceReplayer(events)
    res = replayer.replay()

    assert res.zero_token_burn is True
    assert res.chain_valid is True
    assert res.drift_detected is False
    assert res.replayed_steps == 7
    assert res.tokens_saved == sum(e.tokens_in + e.tokens_out for e in events)
    assert res.tokens_saved > 0
    assert res.final_state["phase"] == "completed"


def test_custom_stub_drift_detection():
    events = create_demo_trace()
    replayer = TraceReplayer(
        events,
        tool_stubs={
            "mcp:run_tests": lambda args: {"passed": 10, "failed": 2, "status": "fail"}
        },
    )
    res = replayer.replay()

    assert res.drift_detected is True
    assert any(v.kind == "output_drift" and v.seq == 5 for v in res.violations)


def test_schema_validator_detects_missing_keys_and_custom_rule():
    events = create_demo_trace()
    replayer = TraceReplayer(
        events,
        schema_validators={
            "mcp:run_tests": ["passed", "failed", "coverage_pct"],
            "mcp:repo_search": lambda out: (
                len(out.get("matches", [])) > 1,
                "Expected at least 2 matches",
            ),
        },
    )
    res = replayer.replay()

    assert res.drift_detected is True
    kinds = {v.kind for v in res.violations}
    assert "output_schema_mismatch" in kinds
    assert len(res.violations) == 2


def test_replay_flags_broken_hash_chain():
    events = create_demo_trace()
    events[1].output_data["response"] = "tampered"
    res = TraceReplayer(events).replay(verify_chain=True)

    assert res.chain_valid is False
    assert res.drift_detected is True
    assert any(v.kind == "hash_chain_broken" for v in res.violations)


def test_time_travel_inspect_step_and_step_through():
    events = create_demo_trace()
    replayer = TraceReplayer(events)

    step2 = replayer.inspect_step(2)
    assert step2["seq"] == 2
    assert step2["name"] == "mcp:repo_search"
    assert step2["hash_valid"] is True
    assert step2["state_snapshot"]["found_issue"] == "missing exp check"

    sliced = list(replayer.step_through(start_seq=1, end_seq=3))
    assert [s.seq for s in sliced] == [1, 2, 3]

    with pytest.raises(IndexError):
        replayer.inspect_step(99)
