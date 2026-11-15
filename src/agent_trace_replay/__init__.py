"""agent-trace-replay: Zero-Cloud Time-Travel Debugger, Deterministic Trajectory Replay & Counterfactual Forking."""

from .forker import CounterfactualForker, ForkOverride, ForkResult, StepDiff, TrajectoryDiff
from .mcp_server import MCPServer
from .models import EventType, GENESIS_HASH, TraceEvent, compute_event_hash, verify_trace_chain
from .recorder import TraceRecorder, TraceStore, create_demo_trace
from .replayer import DriftViolation, ReplayResult, ReplayStepResult, TraceReplayer

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
    "TraceEvent",
    "TraceRecorder",
    "TraceReplayer",
    "TraceStore",
    "TrajectoryDiff",
    "__version__",
    "compute_event_hash",
    "create_demo_trace",
    "verify_trace_chain",
]
