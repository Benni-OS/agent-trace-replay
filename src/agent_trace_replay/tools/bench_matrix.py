"""Matrix Benchmark Suite for agent-trace-replay.

Executes automated sweeps across trajectory lengths (e.g. 10, 50, 100, 500 steps)
to measure recording latency, SHA-256 verification speed, offline replay throughput,
and counterfactual fork + diff latency.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any

from ..core.forker import CounterfactualForker, ForkOverride
from ..core.models import EventType, verify_trace_chain
from ..core.recorder import TraceRecorder
from ..core.replayer import TraceReplayer


class TraceBenchMatrixRunner:
    """Executes a multi-scale trajectory benchmark matrix."""

    def __init__(
        self,
        step_counts: list[int] | None = None,
        reps: int = 3,
    ) -> None:
        self.step_counts = step_counts or [10, 50, 100, 500]
        self.reps = reps

    @staticmethod
    def _build_synthetic_trace(steps: int, seed: int = 42) -> list[Any]:
        rec = TraceRecorder(trace_id=f"bench-{steps}", seed=seed, deterministic_clock=True)
        rec.record_seed_init({"bench_steps": steps})
        for idx in range(1, steps):
            if idx % 2 == 1:
                rec.record_llm_call(
                    model="local-qwen3-30b",
                    prompt=f"Step {idx} reasoning",
                    response=f"action_{idx}",
                    tokens_in=120,
                    tokens_out=64,
                    duration_ms=12.5,
                )
            else:
                rec.record_tool_call(
                    tool_name="sandbox_exec",
                    arguments={"step": idx},
                    result={"exit_code": 0, "ok": True},
                    duration_ms=4.2,
                )
        return rec.events

    def run_matrix(self) -> dict[str, Any]:
        """Run the benchmark sweep across configured step counts."""
        rows: list[dict[str, Any]] = []

        for count in self.step_counts:
            rec_ms: list[float] = []
            verify_ms: list[float] = []
            replay_ms: list[float] = []
            fork_diff_ms: list[float] = []

            for _ in range(self.reps):
                t0 = time.perf_counter()
                events = self._build_synthetic_trace(count)
                rec_ms.append((time.perf_counter() - t0) * 1000.0)

                t1 = time.perf_counter()
                valid, _ = verify_trace_chain(events)
                assert valid
                verify_ms.append((time.perf_counter() - t1) * 1000.0)

                t2 = time.perf_counter()
                rep = TraceReplayer(events).replay()
                assert rep.chain_valid and not rep.drift_detected
                replay_ms.append((time.perf_counter() - t2) * 1000.0)

                fork_seq = max(1, count // 2)
                t3 = time.perf_counter()
                fork_res = CounterfactualForker.fork(
                    events,
                    ForkOverride(seq=fork_seq, new_output={"overridden": True}),
                )
                CounterfactualForker.diff(events, fork_res.events)
                fork_diff_ms.append((time.perf_counter() - t3) * 1000.0)

            avg_replay = statistics.mean(replay_ms)
            steps_per_sec = (count / (avg_replay / 1000.0)) if avg_replay > 0 else 0.0
            rows.append(
                {
                    "steps": count,
                    "record_ms": round(statistics.mean(rec_ms), 3),
                    "verify_ms": round(statistics.mean(verify_ms), 3),
                    "replay_ms": round(avg_replay, 3),
                    "fork_diff_ms": round(statistics.mean(fork_diff_ms), 3),
                    "replay_steps_per_sec": round(steps_per_sec, 1),
                    "token_burn_usd": 0.0,
                }
            )

        return {"reps": self.reps, "matrix": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trace-replay matrix",
        description="Run multi-scale trajectory replay & counterfactual fork benchmark matrix.",
    )
    parser.add_argument("--steps", nargs="+", type=int, default=[10, 50, 100, 500])
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    runner = TraceBenchMatrixRunner(step_counts=args.steps, reps=args.reps)
    result = runner.run_matrix()
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[trace-replay matrix] reps={result['reps']}")
        for row in result["matrix"]:
            print(
                f"  steps={row['steps']:>4} | record={row['record_ms']:>6.2f}ms | "
                f"verify={row['verify_ms']:>6.2f}ms | replay={row['replay_ms']:>6.2f}ms | "
                f"fork+diff={row['fork_diff_ms']:>6.2f}ms | {row['replay_steps_per_sec']:>9.1f} steps/s"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
