"""Tests for CounterfactualForker: branching at step N and structural/cost trajectory diff."""

import copy

from agent_trace_replay.forker import CounterfactualForker, ForkOverride
from agent_trace_replay.models import verify_trace_chain
from agent_trace_replay.recorder import create_demo_trace


def test_counterfactual_fork_preserves_prefix_and_reseals_chain():
    base = create_demo_trace()
    override = ForkOverride(
        seq=2,
        new_output={"matches": [{"file": "src/auth.py", "line": 48, "issue": "expired refresh token"}]},
        state_patch={"found_issue": "expired refresh token"},
    )
    fork_res = CounterfactualForker.fork(base, override)

    assert fork_res.fork_seq == 2
    assert len(fork_res.events) == len(base)
    valid, errors = verify_trace_chain(fork_res.events)
    assert valid is True
    assert errors == []

    # Steps 0 and 1 must be identical
    assert fork_res.diff.step_diffs[0].status == "identical"
    assert fork_res.diff.step_diffs[1].status == "identical"
    # Step 2 is modified
    assert fork_res.diff.step_diffs[2].status == "modified"
    assert "output_data" in fork_res.diff.step_diffs[2].field_diffs
    assert fork_res.diff.identical_steps == 2
    assert fork_res.diff.modified_steps == 1


def test_counterfactual_fork_with_downstream_simulator_and_cost_delta():
    base = create_demo_trace()

    def sim(ev, state):
        new_ev = copy.deepcopy(ev)
        if new_ev.seq == 4:
            new_ev.tokens_in += 120
            new_ev.tokens_out += 40
            new_ev.duration_ms += 150.0
            new_ev.output_data = {"response": "Patched alternate branch."}
        new_ev.state_snapshot = dict(state)
        return new_ev

    override = ForkOverride(
        seq=1,
        new_prompt="Investigate OAuth2 refresh token rotation instead.",
        tokens_in=450,
    )
    fork_res = CounterfactualForker.fork(base, override, downstream_simulator=sim)

    assert fork_res.diff.total_token_delta == (30 + 120 + 40)
    assert fork_res.diff.total_latency_delta_ms == 150.0
    assert fork_res.diff.fork_point_seq == 1


def test_trajectory_diff_handles_added_and_removed_steps():
    base = create_demo_trace()
    shorter = base[:5]
    diff_removed = CounterfactualForker.diff(base, shorter)
    assert diff_removed.removed_steps == 2
    assert diff_removed.total_token_delta < 0

    diff_added = CounterfactualForker.diff(shorter, base)
    assert diff_added.added_steps == 2
    assert diff_added.total_token_delta > 0
