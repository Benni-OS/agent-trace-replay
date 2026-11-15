"""Throughput Benchmark Script for agent-trace-replay."""

from __future__ import annotations

import json

from agent_trace_replay.tools.bench_matrix import TraceBenchMatrixRunner


def main() -> None:
    runner = TraceBenchMatrixRunner(step_counts=[10, 50, 100, 500], reps=3)
    report = runner.run_matrix()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
