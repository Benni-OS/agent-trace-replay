"""Real-Time Telemetry Engine for agent-trace-replay.

Captures replay & fork latency percentiles (P50, P90, P99), step throughput,
saved LLM token volume, and drift/tamper incident counts.
"""

from __future__ import annotations

import statistics
import time
from typing import Any


class TraceTelemetryEngine:
    """Collects real-time trajectory replay, fork, and verification telemetry."""

    def __init__(self, max_history: int = 500) -> None:
        self.max_history = max_history
        self.replay_latencies_ms: list[float] = []
        self.fork_latencies_ms: list[float] = []
        self.event_type_counts: dict[str, int] = {}
        self.start_time = time.time()
        self.total_replays = 0
        self.total_forks = 0
        self.total_steps_replayed = 0
        self.total_tokens_saved = 0
        self.total_drift_violations = 0
        self.total_chain_failures = 0

    def record_replay(
        self,
        latency_ms: float,
        steps_count: int,
        tokens_saved: int = 0,
        drift_count: int = 0,
        chain_valid: bool = True,
        event_types: list[str] | None = None,
    ) -> None:
        """Record metrics for an offline deterministic replay execution."""
        self.replay_latencies_ms.append(latency_ms)
        if len(self.replay_latencies_ms) > self.max_history:
            self.replay_latencies_ms.pop(0)

        self.total_replays += 1
        self.total_steps_replayed += steps_count
        self.total_tokens_saved += tokens_saved
        self.total_drift_violations += drift_count
        if not chain_valid:
            self.total_chain_failures += 1

        if event_types:
            for etype in event_types:
                self.event_type_counts[etype] = self.event_type_counts.get(etype, 0) + 1

    def record_fork(self, latency_ms: float) -> None:
        """Record metrics for a counterfactual fork + diff operation."""
        self.fork_latencies_ms.append(latency_ms)
        if len(self.fork_latencies_ms) > self.max_history:
            self.fork_latencies_ms.pop(0)
        self.total_forks += 1

    @staticmethod
    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
        return round(sorted_vals[idx], 3)

    def get_summary(self) -> dict[str, Any]:
        """Return aggregated telemetry snapshot."""
        uptime = max(0.001, time.time() - self.start_time)
        avg_replay_ms = (
            round(statistics.mean(self.replay_latencies_ms), 3)
            if self.replay_latencies_ms
            else 0.0
        )
        avg_fork_ms = (
            round(statistics.mean(self.fork_latencies_ms), 3)
            if self.fork_latencies_ms
            else 0.0
        )
        return {
            "uptime_s": round(uptime, 2),
            "total_replays": self.total_replays,
            "total_forks": self.total_forks,
            "total_steps_replayed": self.total_steps_replayed,
            "total_tokens_saved": self.total_tokens_saved,
            "estimated_usd_saved": round((self.total_tokens_saved / 1_000_000) * 15.0, 4),
            "total_drift_violations": self.total_drift_violations,
            "total_chain_failures": self.total_chain_failures,
            "replay_latency_ms": {
                "avg": avg_replay_ms,
                "p50": self._percentile(self.replay_latencies_ms, 50),
                "p90": self._percentile(self.replay_latencies_ms, 90),
                "p99": self._percentile(self.replay_latencies_ms, 99),
            },
            "fork_latency_ms": {
                "avg": avg_fork_ms,
                "p50": self._percentile(self.fork_latencies_ms, 50),
                "p99": self._percentile(self.fork_latencies_ms, 99),
            },
            "event_type_distribution": dict(self.event_type_counts),
        }
