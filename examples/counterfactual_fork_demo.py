"""Counterfactual Forking Demo: Branch at Step N and Diff Trajectories."""

from __future__ import annotations

from agent_trace_replay.core import (
    CounterfactualForker,
    ForkOverride,
    create_demo_trace,
    verify_trace_chain,
)


def main() -> None:
    base_events = create_demo_trace(seed=42, trace_id="fork-demo-base")
    fork_result = CounterfactualForker.fork(
        base_events,
        ForkOverride(
            seq=3,
            new_output={"passed": 11, "failed": 1, "status": "fail"},
            tokens_out=48,
        ),
    )

    valid, _ = verify_trace_chain(fork_result.events)
    assert valid
    print(f"Base: {fork_result.base_trace_id} -> Fork: {fork_result.fork_trace_id}")
    print(f"Diff Summary: {fork_result.diff.divergence_summary}")


if __name__ == "__main__":
    main()
