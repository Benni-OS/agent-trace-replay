"""Trace Doctor — Runtime diagnostics, SHA-256 chain self-test, and store probe.

Inspects Python runtime, SQLite3 availability, local storage headroom, and runs
an end-to-end deterministic record -> verify -> replay -> fork diagnostic.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from typing import Any

from ..core.forker import CounterfactualForker, ForkOverride
from ..core.models import verify_trace_chain
from ..core.recorder import create_demo_trace
from ..core.replayer import TraceReplayer
from ..serve.health_monitor import TraceHealthMonitor


def run_doctor(store_dir: str = ".") -> dict[str, Any]:
    """Run full diagnostic suite for agent-trace-replay."""
    monitor = TraceHealthMonitor(store_dir=store_dir)
    health = monitor.check_health()

    t0 = time.perf_counter()
    base_events = create_demo_trace(seed=42, trace_id="doctor-probe")
    replay_res = TraceReplayer(base_events).replay()
    fork_res = CounterfactualForker.fork(
        base_events,
        ForkOverride(seq=3, new_output={"doctor_probe": True}),
    )
    fork_valid, _ = verify_trace_chain(fork_res.events)
    pipeline_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    ok = (
        health["status"] == "healthy"
        and replay_res.chain_valid
        and not replay_res.drift_detected
        and fork_valid
    )

    return {
        "ok": ok,
        "status": health["status"],
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": health["sqlite"],
        "disk": health["disk"],
        "sha256_self_test": health["sha256_self_test"],
        "pipeline_probe": {
            "base_events": len(base_events),
            "replay_passed": replay_res.chain_valid and not replay_res.drift_detected,
            "fork_chain_valid": fork_valid,
            "elapsed_ms": pipeline_ms,
        },
        "warnings": health["warnings"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trace-replay doctor",
        description="Run local diagnostics and SHA-256 trajectory self-tests.",
    )
    parser.add_argument("--store-dir", default=".", help="Directory to check disk headroom.")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output.")
    args = parser.parse_args(argv)

    report = run_doctor(store_dir=args.store_dir)
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        badge = "OK" if report["ok"] else "WARN"
        print(f"[trace-replay doctor] Status: {badge} ({report['status']})")
        print(f"  Python   : {report['python_version']} ({report['platform']})")
        print(f"  SQLite3  : {report['sqlite'].get('sqlite_version')} (ready={report['sqlite'].get('available')})")
        print(f"  Disk Free: {report['disk']['free_mb']} MB")
        print(f"  SHA-256  : {report['sha256_self_test']['events_verified']} events verified in {report['sha256_self_test']['elapsed_ms']} ms")
        print(f"  Pipeline : replay={report['pipeline_probe']['replay_passed']} fork={report['pipeline_probe']['fork_chain_valid']} ({report['pipeline_probe']['elapsed_ms']} ms)")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
