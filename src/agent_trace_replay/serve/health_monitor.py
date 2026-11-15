"""System Health & Trace Store Integrity Monitor for agent-trace-replay.

Monitors local storage availability, SQLite backend readiness, SHA-256 chain
verification health, and replay drift rates.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..core.models import verify_trace_chain
from ..core.recorder import create_demo_trace


class TraceHealthMonitor:
    """Monitors local trace store health and cryptographic integrity readiness."""

    def __init__(
        self,
        store_dir: str | Path = ".",
        min_free_disk_mb: float = 100.0,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.min_free_disk_mb = min_free_disk_mb

    @staticmethod
    def check_sqlite_ready() -> dict[str, Any]:
        """Verify built-in SQLite3 engine works in-memory."""
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE TABLE _health (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO _health (id) VALUES (1)")
            row = conn.execute("SELECT id FROM _health").fetchone()
            conn.close()
            return {"available": row == (1,), "sqlite_version": sqlite3.sqlite_version}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    @staticmethod
    def check_hash_chain_self_test() -> dict[str, Any]:
        """Run a fast in-memory SHA-256 chain self-test."""
        t0 = time.perf_counter()
        events = create_demo_trace(seed=42, trace_id="health-selftest")
        valid, errors = verify_trace_chain(events)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "passed": valid and len(errors) == 0,
            "events_verified": len(events),
            "elapsed_ms": elapsed_ms,
        }

    def check_health(self) -> dict[str, Any]:
        """Generate structured health assessment for the local trace runtime."""
        target = self.store_dir if self.store_dir.exists() else Path(".")
        usage = shutil.disk_usage(target)
        free_mb = round(usage.free / (1024 * 1024), 2)
        total_mb = round(usage.total / (1024 * 1024), 2)

        sqlite_info = self.check_sqlite_ready()
        chain_info = self.check_hash_chain_self_test()

        status = "healthy"
        warnings: list[str] = []

        if free_mb < self.min_free_disk_mb:
            status = "degraded"
            warnings.append(f"Low disk space: {free_mb} MB free (< {self.min_free_disk_mb} MB).")
        if not sqlite_info.get("available"):
            status = "critical"
            warnings.append("SQLite3 backend unavailable.")
        if not chain_info.get("passed"):
            status = "critical"
            warnings.append("SHA-256 trace chain self-test failed.")

        return {
            "status": status,
            "warnings": warnings,
            "disk": {
                "path": str(target.resolve()),
                "free_mb": free_mb,
                "total_mb": total_mb,
            },
            "sqlite": sqlite_info,
            "sha256_self_test": chain_info,
            "timestamp": time.time(),
        }
