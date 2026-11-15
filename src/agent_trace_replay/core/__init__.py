"""Core trajectory recording, deterministic replay, and counterfactual forking."""

from .forker import CounterfactualForker, ForkOverride, ForkResult, StepDiff, TrajectoryDiff
from .models import EventType, GENESIS_HASH, TraceEvent, compute_event_hash, verify_trace_chain
from .recorder import TraceRecorder, TraceStore, create_demo_trace
from .replayer import DriftViolation, ReplayResult, ReplayStepResult, TraceReplayer

__all__ = [
    "CounterfactualForker",
    "DriftViolation",
    "EventType",
    "ForkOverride",
    "ForkResult",
    "GENESIS_HASH",
    "ReplayResult",
    "ReplayStepResult",
    "StepDiff",
    "TraceEvent",
    "TraceRecorder",
    "TraceReplayer",
    "TraceStore",
    "TrajectoryDiff",
    "compute_event_hash",
    "create_demo_trace",
    "verify_trace_chain",
]
