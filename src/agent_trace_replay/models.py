"""Core data models and cryptographic SHA-256 hash-chain primitives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

GENESIS_HASH = "0" * 64


class EventType(str, Enum):
    """Canonical event types recorded in an agent execution trajectory."""

    SEED_INIT = "seed_init"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    STATE_SNAPSHOT = "state_snapshot"
    SYSTEM = "system"


def canonical_json(obj: Any) -> str:
    """Serialize any JSON-compatible value into deterministic canonical JSON."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_event_hash(
    *,
    trace_id: str,
    seq: int,
    event_type: str,
    name: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    state_snapshot: dict[str, Any],
    seed: int,
    timestamp_ns: int,
    duration_ms: float,
    tokens_in: int,
    tokens_out: int,
    prev_hash: str,
) -> str:
    """Compute a deterministic SHA-256 integrity hash chaining to ``prev_hash``."""
    payload = {
        "trace_id": trace_id,
        "seq": seq,
        "event_type": event_type,
        "name": name,
        "input_data": input_data,
        "output_data": output_data,
        "state_snapshot": state_snapshot,
        "seed": seed,
        "timestamp_ns": timestamp_ns,
        "duration_ms": round(float(duration_ms), 6),
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "prev_hash": prev_hash,
    }
    encoded = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class TraceEvent:
    """A single deterministic, cryptographically chained event in an agent trajectory."""

    trace_id: str
    seq: int
    event_type: str
    name: str
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    seed: int = 42
    timestamp_ns: int = 0
    duration_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    prev_hash: str = GENESIS_HASH
    event_hash: str = ""

    def compute_hash(self) -> str:
        """Compute the expected SHA-256 hash for this event's current fields."""
        return compute_event_hash(
            trace_id=self.trace_id,
            seq=self.seq,
            event_type=self.event_type,
            name=self.name,
            input_data=self.input_data,
            output_data=self.output_data,
            state_snapshot=self.state_snapshot,
            seed=self.seed,
            timestamp_ns=self.timestamp_ns,
            duration_ms=self.duration_ms,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            prev_hash=self.prev_hash,
        )

    def seal(self) -> TraceEvent:
        """Compute and assign ``event_hash`` in-place and return self."""
        self.event_hash = self.compute_hash()
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceEvent:
        """Reconstruct a ``TraceEvent`` from a dictionary."""
        return cls(
            trace_id=str(data["trace_id"]),
            seq=int(data["seq"]),
            event_type=str(data["event_type"]),
            name=str(data["name"]),
            input_data=dict(data.get("input_data") or {}),
            output_data=dict(data.get("output_data") or {}),
            state_snapshot=dict(data.get("state_snapshot") or {}),
            seed=int(data.get("seed", 42)),
            timestamp_ns=int(data.get("timestamp_ns", 0)),
            duration_ms=float(data.get("duration_ms", 0.0)),
            tokens_in=int(data.get("tokens_in", 0)),
            tokens_out=int(data.get("tokens_out", 0)),
            prev_hash=str(data.get("prev_hash", GENESIS_HASH)),
            event_hash=str(data.get("event_hash", "")),
        )


def verify_trace_chain(events: list[TraceEvent]) -> tuple[bool, list[str]]:
    """Verify sequential ordering, ``prev_hash`` linkage, and SHA-256 hashes.

    Returns ``(is_valid, errors)``.
    """
    if not events:
        return True, []

    errors: list[str] = []
    expected_prev = GENESIS_HASH

    for idx, ev in enumerate(events):
        if ev.seq != idx:
            errors.append(f"Step {idx}: expected seq={idx}, got seq={ev.seq}")
        if ev.prev_hash != expected_prev:
            errors.append(
                f"Step {idx}: prev_hash mismatch (expected {expected_prev[:12]}..., got {ev.prev_hash[:12]}...)"
            )
        expected_hash = ev.compute_hash()
        if ev.event_hash != expected_hash:
            errors.append(
                f"Step {idx}: SHA-256 integrity mismatch (expected {expected_hash[:12]}..., got {ev.event_hash[:12]}...)"
            )
        expected_prev = ev.event_hash

    return len(errors) == 0, errors
