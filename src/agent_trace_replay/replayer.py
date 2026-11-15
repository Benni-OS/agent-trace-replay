"""Offline zero-token-burn deterministic trajectory replay & time-travel engine."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator

from .models import EventType, TraceEvent, verify_trace_chain


@dataclass
class DriftViolation:
    """Represents a determinism, schema, or cryptographic integrity violation."""

    seq: int
    kind: str
    message: str
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReplayStepResult:
    """Result of replaying a single trajectory step offline."""

    seq: int
    event_type: str
    name: str
    matched: bool
    stub_used: str
    output_data: dict[str, Any]
    state_snapshot: dict[str, Any]
    drift_violations: list[DriftViolation] = field(default_factory=list)
    original_duration_ms: float = 0.0
    replay_duration_ms: float = 0.0
    tokens_saved: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["drift_violations"] = [v.to_dict() for v in self.drift_violations]
        return d


@dataclass
class ReplayResult:
    """Aggregate result of an offline deterministic trajectory replay."""

    trace_id: str
    total_steps: int
    replayed_steps: int
    zero_token_burn: bool
    tokens_saved: int
    original_duration_ms: float
    replay_duration_ms: float
    chain_valid: bool
    drift_detected: bool
    violations: list[DriftViolation] = field(default_factory=list)
    steps: list[ReplayStepResult] = field(default_factory=list)
    final_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_steps": self.total_steps,
            "replayed_steps": self.replayed_steps,
            "zero_token_burn": self.zero_token_burn,
            "tokens_saved": self.tokens_saved,
            "original_duration_ms": round(self.original_duration_ms, 3),
            "replay_duration_ms": round(self.replay_duration_ms, 3),
            "chain_valid": self.chain_valid,
            "drift_detected": self.drift_detected,
            "violations": [v.to_dict() for v in self.violations],
            "steps": [s.to_dict() for s in self.steps],
            "final_state": self.final_state,
        }


StubFn = Callable[[dict[str, Any]], dict[str, Any]]
SchemaSpec = list[str] | Callable[[dict[str, Any]], tuple[bool, str]]


class TraceReplayer:
    """Offline zero-token-burn deterministic replay & time-travel debugger."""

    def __init__(
        self,
        events: list[TraceEvent],
        tool_stubs: dict[str, StubFn] | None = None,
        llm_stubs: dict[str, StubFn] | None = None,
        schema_validators: dict[str, SchemaSpec] | None = None,
    ) -> None:
        self.events = list(events)
        self.tool_stubs = dict(tool_stubs or {})
        self.llm_stubs = dict(llm_stubs or {})
        self.schema_validators = dict(schema_validators or {})

    def inspect_step(self, seq: int) -> dict[str, Any]:
        """Time-travel to exact step ``seq`` and return full context & cumulative metrics."""
        if not self.events:
            raise IndexError("Cannot inspect an empty trajectory.")
        if seq < 0 or seq >= len(self.events):
            raise IndexError(f"Step seq={seq} out of range [0, {len(self.events) - 1}]")

        ev = self.events[seq]
        cum_tokens_in = sum(e.tokens_in for e in self.events[: seq + 1])
        cum_tokens_out = sum(e.tokens_out for e in self.events[: seq + 1])
        cum_duration_ms = sum(e.duration_ms for e in self.events[: seq + 1])

        return {
            "trace_id": ev.trace_id,
            "seq": ev.seq,
            "total_steps": len(self.events),
            "event_type": ev.event_type,
            "name": ev.name,
            "input_data": ev.input_data,
            "output_data": ev.output_data,
            "state_snapshot": ev.state_snapshot,
            "seed": ev.seed,
            "timestamp_ns": ev.timestamp_ns,
            "duration_ms": ev.duration_ms,
            "tokens_in": ev.tokens_in,
            "tokens_out": ev.tokens_out,
            "cumulative_tokens": cum_tokens_in + cum_tokens_out,
            "cumulative_duration_ms": round(cum_duration_ms, 3),
            "prev_hash": ev.prev_hash,
            "event_hash": ev.event_hash,
            "hash_valid": ev.event_hash == ev.compute_hash(),
        }

    def _validate_schema(self, ev: TraceEvent, output: dict[str, Any]) -> list[DriftViolation]:
        spec = self.schema_validators.get(ev.name)
        if spec is None:
            return []

        violations: list[DriftViolation] = []
        if callable(spec):
            ok, msg = spec(output)
            if not ok:
                violations.append(
                    DriftViolation(
                        seq=ev.seq,
                        kind="output_schema_mismatch",
                        message=msg,
                        expected="valid schema",
                        actual=output,
                    )
                )
        elif isinstance(spec, list):
            missing = [k for k in spec if k not in output]
            if missing:
                violations.append(
                    DriftViolation(
                        seq=ev.seq,
                        kind="output_schema_mismatch",
                        message=f"Missing required output keys for '{ev.name}': {missing}",
                        expected=spec,
                        actual=sorted(output.keys()),
                    )
                )
        return violations

    def step_through(
        self,
        start_seq: int = 0,
        end_seq: int | None = None,
        strict: bool = False,
    ) -> Iterator[ReplayStepResult]:
        """Yield ``ReplayStepResult`` one step at a time for interactive time-travel."""
        if not self.events:
            return

        stop = len(self.events) if end_seq is None else min(len(self.events), end_seq + 1)
        for idx in range(max(0, start_seq), stop):
            ev = self.events[idx]
            t0 = time.perf_counter()
            step_violations: list[DriftViolation] = []

            if ev.event_type == EventType.TOOL_CALL.value and ev.name in self.tool_stubs:
                actual_output = dict(self.tool_stubs[ev.name](ev.input_data))
                stub_used = "custom_tool_stub"
            elif ev.event_type == EventType.LLM_CALL.value and ev.name in self.llm_stubs:
                actual_output = dict(self.llm_stubs[ev.name](ev.input_data))
                stub_used = "custom_llm_stub"
            else:
                actual_output = dict(ev.output_data)
                stub_used = "recorded_tape"

            if actual_output != ev.output_data:
                step_violations.append(
                    DriftViolation(
                        seq=ev.seq,
                        kind="output_drift",
                        message=f"Output diverged from recorded trajectory at step {ev.seq} ({ev.name})",
                        expected=ev.output_data,
                        actual=actual_output,
                    )
                )

            step_violations.extend(self._validate_schema(ev, actual_output))

            if strict and not actual_output and ev.event_type in {
                EventType.TOOL_CALL.value,
                EventType.LLM_CALL.value,
            }:
                step_violations.append(
                    DriftViolation(
                        seq=ev.seq,
                        kind="missing_stub",
                        message=f"Empty output in strict mode for step {ev.seq} ({ev.name})",
                        expected="non-empty output",
                        actual=actual_output,
                    )
                )

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            tokens_saved = ev.tokens_in + ev.tokens_out

            yield ReplayStepResult(
                seq=ev.seq,
                event_type=ev.event_type,
                name=ev.name,
                matched=len(step_violations) == 0,
                stub_used=stub_used,
                output_data=actual_output,
                state_snapshot=dict(ev.state_snapshot),
                drift_violations=step_violations,
                original_duration_ms=ev.duration_ms,
                replay_duration_ms=round(elapsed_ms, 4),
                tokens_saved=tokens_saved,
            )

    def replay(self, verify_chain: bool = True, strict: bool = False) -> ReplayResult:
        """Execute a full offline deterministic replay of the recorded trajectory."""
        violations: list[DriftViolation] = []
        chain_valid = True

        if verify_chain:
            chain_valid, chain_errors = verify_trace_chain(self.events)
            for err in chain_errors:
                violations.append(
                    DriftViolation(
                        seq=-1,
                        kind="hash_chain_broken",
                        message=err,
                    )
                )

        steps = list(self.step_through(strict=strict))
        for st in steps:
            violations.extend(st.drift_violations)

        trace_id = self.events[0].trace_id if self.events else "empty"
        tokens_saved = sum(st.tokens_saved for st in steps)
        orig_ms = sum(st.original_duration_ms for st in steps)
        replay_ms = sum(st.replay_duration_ms for st in steps)
        final_state = dict(steps[-1].state_snapshot) if steps else {}

        return ReplayResult(
            trace_id=trace_id,
            total_steps=len(self.events),
            replayed_steps=len(steps),
            zero_token_burn=True,
            tokens_saved=tokens_saved,
            original_duration_ms=orig_ms,
            replay_duration_ms=replay_ms,
            chain_valid=chain_valid,
            drift_detected=len(violations) > 0,
            violations=violations,
            steps=steps,
            final_state=final_state,
        )
