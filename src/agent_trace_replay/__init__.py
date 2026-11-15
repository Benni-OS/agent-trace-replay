"""agent-trace-replay: Zero-Cloud Time-Travel Debugger, Deterministic Trajectory Replay & Counterfactual Forking."""

from .core import (
    CounterfactualForker,
    DriftViolation,
    EventType,
    ForkOverride,
    ForkResult,
    GENESIS_HASH,
    ReplayResult,
    ReplayStepResult,
    StepDiff,
    TraceEvent,
    TraceRecorder,
    TraceReplayer,
    TraceStore,
    TrajectoryDiff,
    compute_event_hash,
    create_demo_trace,
    verify_trace_chain,
)
from .serve import MCPServer, TraceHealthMonitor, TraceTelemetryEngine
from .tools import TraceBenchMatrixRunner, run_doctor

__version__ = "0.1.0"

__all__ = [
    "CounterfactualForker",
    "DriftViolation",
    "EventType",
    "ForkOverride",
    "ForkResult",
    "GENESIS_HASH",
    "MCPServer",
    "ReplayResult",
    "ReplayStepResult",
    "StepDiff",
    "TraceBenchMatrixRunner",
    "TraceEvent",
    "TraceHealthMonitor",
    "TraceRecorder",
    "TraceReplayer",
    "TraceStore",
    "TraceTelemetryEngine",
    "TrajectoryDiff",
    "__version__",
    "compute_event_hash",
    "create_demo_trace",
    "run_doctor",
    "verify_trace_chain",
]
