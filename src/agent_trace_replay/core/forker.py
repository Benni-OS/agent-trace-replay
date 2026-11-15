"""Counterfactual branching & structural trajectory diff engine."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .models import GENESIS_HASH, TraceEvent


@dataclass
class ForkOverride:
    """Counterfactual injection applied at a specific step ``seq``."""

    seq: int
    new_input: dict[str, Any] | None = None
    new_output: dict[str, Any] | None = None
    new_prompt: str | None = None
    state_patch: dict[str, Any] | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: float | None = None


@dataclass
class StepDiff:
    """Structural comparison between base and forked trajectory at step ``seq``."""

    seq: int
    status: str  # "identical" | "modified" | "diverged" | "added" | "removed"
    name: str
    field_diffs: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    token_delta: int = 0
    latency_delta_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrajectoryDiff:
    """Full structural, token, and latency diff between two trajectories."""

    base_trace_id: str
    fork_trace_id: str
    fork_point_seq: int | None
    identical_steps: int
    modified_steps: int
    diverged_steps: int
    added_steps: int
    removed_steps: int
    total_token_delta: int
    total_latency_delta_ms: float
    divergence_summary: str
    step_diffs: list[StepDiff] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_trace_id": self.base_trace_id,
            "fork_trace_id": self.fork_trace_id,
            "fork_point_seq": self.fork_point_seq,
            "identical_steps": self.identical_steps,
            "modified_steps": self.modified_steps,
            "diverged_steps": self.diverged_steps,
            "added_steps": self.added_steps,
            "removed_steps": self.removed_steps,
            "total_token_delta": self.total_token_delta,
            "total_latency_delta_ms": round(self.total_latency_delta_ms, 3),
            "divergence_summary": self.divergence_summary,
            "step_diffs": [s.to_dict() for s in self.step_diffs],
        }


@dataclass
class ForkResult:
    """Result of a counterfactual fork operation including new events and diff."""

    base_trace_id: str
    fork_trace_id: str
    fork_seq: int
    events: list[TraceEvent]
    diff: TrajectoryDiff

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_trace_id": self.base_trace_id,
            "fork_trace_id": self.fork_trace_id,
            "fork_seq": self.fork_seq,
            "fork_steps": len(self.events),
            "diff": self.diff.to_dict(),
        }


DownstreamSimulator = Callable[[TraceEvent, dict[str, Any]], TraceEvent]


class CounterfactualForker:
    """Branches an existing trajectory at step N and computes structural/cost deltas."""

    @classmethod
    def fork(
        cls,
        events: list[TraceEvent],
        override: ForkOverride,
        downstream_simulator: DownstreamSimulator | None = None,
        new_trace_id: str | None = None,
    ) -> ForkResult:
        """Create a counterfactual branch from ``events`` at ``override.seq``."""
        if not events:
            raise ValueError("Cannot fork an empty trajectory.")
        if override.seq < 0 or override.seq >= len(events):
            raise IndexError(f"fork_seq={override.seq} out of range [0, {len(events) - 1}]")

        base_trace_id = events[0].trace_id
        fork_trace_id = new_trace_id or f"{base_trace_id}-fork-{override.seq}"

        forked_events: list[TraceEvent] = []
        prev_hash = GENESIS_HASH
        running_state: dict[str, Any] = {}

        for idx, base_ev in enumerate(events):
            ev = copy.deepcopy(base_ev)
            ev.trace_id = fork_trace_id
            ev.seq = idx

            if idx < override.seq:
                running_state = dict(ev.state_snapshot)
            elif idx == override.seq:
                if override.new_input is not None:
                    ev.input_data = dict(override.new_input)
                if override.new_prompt is not None:
                    ev.input_data["prompt"] = override.new_prompt
                if override.new_output is not None:
                    ev.output_data = dict(override.new_output)
                if override.tokens_in is not None:
                    ev.tokens_in = int(override.tokens_in)
                if override.tokens_out is not None:
                    ev.tokens_out = int(override.tokens_out)
                if override.duration_ms is not None:
                    ev.duration_ms = float(override.duration_ms)

                running_state = dict(ev.state_snapshot)
                running_state["counterfactual_fork_at"] = override.seq
                if override.state_patch:
                    running_state.update(override.state_patch)
                ev.state_snapshot = dict(running_state)
            else:
                if downstream_simulator is not None:
                    ev = downstream_simulator(ev, dict(running_state))
                    ev.trace_id = fork_trace_id
                    ev.seq = idx
                    running_state = dict(ev.state_snapshot)
                else:
                    merged_state = dict(ev.state_snapshot)
                    merged_state["counterfactual_fork_at"] = override.seq
                    if override.state_patch:
                        merged_state.update(override.state_patch)
                    ev.state_snapshot = merged_state
                    running_state = merged_state

            ev.prev_hash = prev_hash
            ev.seal()
            prev_hash = ev.event_hash
            forked_events.append(ev)

        diff_result = cls.diff(events, forked_events, fork_point_seq=override.seq)
        return ForkResult(
            base_trace_id=base_trace_id,
            fork_trace_id=fork_trace_id,
            fork_seq=override.seq,
            events=forked_events,
            diff=diff_result,
        )

    @staticmethod
    def diff(
        base_events: list[TraceEvent],
        fork_events: list[TraceEvent],
        fork_point_seq: int | None = None,
    ) -> TrajectoryDiff:
        """Compute a structural, token, and latency diff between two trajectories."""
        base_id = base_events[0].trace_id if base_events else "empty"
        fork_id = fork_events[0].trace_id if fork_events else "empty"

        if fork_point_seq is None:
            for ev in fork_events:
                if "counterfactual_fork_at" in ev.state_snapshot:
                    fork_point_seq = int(ev.state_snapshot["counterfactual_fork_at"])
                    break

        max_len = max(len(base_events), len(fork_events))
        step_diffs: list[StepDiff] = []

        identical = modified = diverged = added = removed = 0
        total_token_delta = 0
        total_latency_delta = 0.0
        first_div_seq: int | None = None

        for idx in range(max_len):
            if idx >= len(base_events):
                f_ev = fork_events[idx]
                added += 1
                tok_d = f_ev.tokens_in + f_ev.tokens_out
                lat_d = f_ev.duration_ms
                total_token_delta += tok_d
                total_latency_delta += lat_d
                if first_div_seq is None:
                    first_div_seq = idx
                step_diffs.append(
                    StepDiff(
                        seq=idx,
                        status="added",
                        name=f_ev.name,
                        token_delta=tok_d,
                        latency_delta_ms=round(lat_d, 3),
                    )
                )
                continue

            if idx >= len(fork_events):
                b_ev = base_events[idx]
                removed += 1
                tok_d = -(b_ev.tokens_in + b_ev.tokens_out)
                lat_d = -b_ev.duration_ms
                total_token_delta += tok_d
                total_latency_delta += lat_d
                if first_div_seq is None:
                    first_div_seq = idx
                step_diffs.append(
                    StepDiff(
                        seq=idx,
                        status="removed",
                        name=b_ev.name,
                        token_delta=tok_d,
                        latency_delta_ms=round(lat_d, 3),
                    )
                )
                continue

            b_ev = base_events[idx]
            f_ev = fork_events[idx]
            field_diffs: dict[str, tuple[Any, Any]] = {}

            for attr in ("event_type", "name", "input_data", "output_data", "state_snapshot"):
                bv = getattr(b_ev, attr)
                fv = getattr(f_ev, attr)
                if bv != fv:
                    field_diffs[attr] = (bv, fv)

            tok_d = (f_ev.tokens_in + f_ev.tokens_out) - (b_ev.tokens_in + b_ev.tokens_out)
            lat_d = f_ev.duration_ms - b_ev.duration_ms
            total_token_delta += tok_d
            total_latency_delta += lat_d

            if not field_diffs and tok_d == 0 and abs(lat_d) < 1e-6:
                status = "identical"
                identical += 1
            elif fork_point_seq is not None and idx == fork_point_seq:
                status = "modified"
                modified += 1
                if first_div_seq is None:
                    first_div_seq = idx
            else:
                status = "diverged"
                diverged += 1
                if first_div_seq is None:
                    first_div_seq = idx

            step_diffs.append(
                StepDiff(
                    seq=idx,
                    status=status,
                    name=f_ev.name,
                    field_diffs=field_diffs,
                    token_delta=tok_d,
                    latency_delta_ms=round(lat_d, 3),
                )
            )

        if first_div_seq is None:
            summary = "Trajectories are structurally identical."
        else:
            summary = (
                f"Diverged at step {first_div_seq}: {identical} identical, "
                f"{modified} modified, {diverged} downstream diverged, "
                f"token_delta={total_token_delta:+d}, latency_delta={total_latency_delta:+.2f}ms."
            )

        return TrajectoryDiff(
            base_trace_id=base_id,
            fork_trace_id=fork_id,
            fork_point_seq=fork_point_seq if fork_point_seq is not None else first_div_seq,
            identical_steps=identical,
            modified_steps=modified,
            diverged_steps=diverged,
            added_steps=added,
            removed_steps=removed,
            total_token_delta=total_token_delta,
            total_latency_delta_ms=round(total_latency_delta, 3),
            divergence_summary=summary,
            step_diffs=step_diffs,
        )
