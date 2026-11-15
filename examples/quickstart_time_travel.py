"""Quickstart: Record, Time-Travel Inspect, and Replay Offline with $0.00 Token Burn."""

from __future__ import annotations

from agent_trace_replay.core import TraceRecorder, TraceReplayer, verify_trace_chain


def main() -> None:
    rec = TraceRecorder(trace_id="quickstart-001", seed=42, deterministic_clock=True)
    rec.record_seed_init({"agent": "benni-coder"})
    rec.record_llm_call(
        model="qwen3-30b-a3b",
        prompt="Inspect workspace health",
        response="Calling trace_doctor",
        tokens_in=85,
        tokens_out=32,
        duration_ms=140.0,
    )
    rec.record_tool_call(
        tool_name="trace_doctor",
        arguments={"store_dir": "."},
        result={"status": "healthy", "ok": True},
        duration_ms=8.5,
    )

    valid, errors = verify_trace_chain(rec.events)
    assert valid, f"Chain error: {errors}"

    replayer = TraceReplayer(rec.events)
    step2 = replayer.inspect_step(2)
    result = replayer.replay()

    print(f"Step 2: {step2['name']} | hash_valid={step2['hash_valid']}")
    print(
        f"Replayed {result.replayed_steps} steps in {result.replay_duration_ms:.3f}ms "
        f"| tokens_saved={result.tokens_saved} | zero_token_burn={result.zero_token_burn}"
    )


if __name__ == "__main__":
    main()
