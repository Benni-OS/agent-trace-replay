"""Deterministic trace & span recorder with JSONL and SQLite persistence."""

from __future__ import annotations

import json
import random
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .models import EventType, GENESIS_HASH, TraceEvent


class TraceStore:
    """Zero-dependency local persistence for agent traces (JSONL & SQLite)."""

    @staticmethod
    def save_jsonl(events: list[TraceEvent], path: str | Path) -> Path:
        """Persist a trajectory to a local JSONL file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        return target

    @staticmethod
    def load_jsonl(path: str | Path) -> list[TraceEvent]:
        """Load a trajectory from a local JSONL file."""
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(f"Trace file not found: {source}")
        events: list[TraceEvent] = []
        with source.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    events.append(TraceEvent.from_dict(json.loads(stripped)))
        return events

    @staticmethod
    def _init_sqlite(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                trace_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                seed INTEGER NOT NULL,
                timestamp_ns INTEGER NOT NULL,
                duration_ms REAL NOT NULL,
                tokens_in INTEGER NOT NULL,
                tokens_out INTEGER NOT NULL,
                prev_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                PRIMARY KEY (trace_id, seq)
            )
            """
        )
        conn.commit()

    @classmethod
    def save_sqlite(cls, events: list[TraceEvent], db_path: str | Path) -> Path:
        """Persist a trajectory to a local SQLite database."""
        target = Path(db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(target)) as conn:
            cls._init_sqlite(conn)
            if events:
                trace_id = events[0].trace_id
                conn.execute("DELETE FROM trace_events WHERE trace_id = ?", (trace_id,))
            rows = [
                (
                    ev.trace_id,
                    ev.seq,
                    ev.event_type,
                    ev.name,
                    json.dumps(ev.input_data, ensure_ascii=False),
                    json.dumps(ev.output_data, ensure_ascii=False),
                    json.dumps(ev.state_snapshot, ensure_ascii=False),
                    ev.seed,
                    ev.timestamp_ns,
                    ev.duration_ms,
                    ev.tokens_in,
                    ev.tokens_out,
                    ev.prev_hash,
                    ev.event_hash,
                )
                for ev in events
            ]
            conn.executemany(
                """
                INSERT INTO trace_events (
                    trace_id, seq, event_type, name, input_json, output_json,
                    state_json, seed, timestamp_ns, duration_ms, tokens_in,
                    tokens_out, prev_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        return target

    @classmethod
    def load_sqlite(cls, db_path: str | Path, trace_id: str | None = None) -> list[TraceEvent]:
        """Load a trajectory from a local SQLite database.

        If ``trace_id`` is omitted, loads the most recently inserted trace.
        """
        source = Path(db_path)
        if not source.exists():
            raise FileNotFoundError(f"SQLite trace database not found: {source}")
        with sqlite3.connect(str(source)) as conn:
            cls._init_sqlite(conn)
            if trace_id is None:
                row = conn.execute(
                    "SELECT trace_id FROM trace_events ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return []
                trace_id = str(row[0])
            rows = conn.execute(
                """
                SELECT trace_id, seq, event_type, name, input_json, output_json,
                       state_json, seed, timestamp_ns, duration_ms, tokens_in,
                       tokens_out, prev_hash, event_hash
                FROM trace_events
                WHERE trace_id = ?
                ORDER BY seq ASC
                """,
                (trace_id,),
            ).fetchall()

        return [
            TraceEvent(
                trace_id=r[0],
                seq=r[1],
                event_type=r[2],
                name=r[3],
                input_data=json.loads(r[4]),
                output_data=json.loads(r[5]),
                state_snapshot=json.loads(r[6]),
                seed=r[7],
                timestamp_ns=r[8],
                duration_ms=r[9],
                tokens_in=r[10],
                tokens_out=r[11],
                prev_hash=r[12],
                event_hash=r[13],
            )
            for r in rows
        ]

    @classmethod
    def list_sqlite_traces(cls, db_path: str | Path) -> list[dict[str, Any]]:
        """List all trace IDs and step counts stored in a SQLite database."""
        source = Path(db_path)
        if not source.exists():
            return []
        with sqlite3.connect(str(source)) as conn:
            cls._init_sqlite(conn)
            rows = conn.execute(
                """
                SELECT trace_id, COUNT(*) as steps,
                       SUM(tokens_in + tokens_out) as total_tokens,
                       SUM(duration_ms) as total_duration_ms
                FROM trace_events
                GROUP BY trace_id
                ORDER BY MIN(rowid) ASC
                """
            ).fetchall()
        return [
            {
                "trace_id": r[0],
                "steps": r[1],
                "total_tokens": r[2] or 0,
                "total_duration_ms": round(float(r[3] or 0.0), 3),
            }
            for r in rows
        ]

    @classmethod
    def load_auto(cls, path: str | Path, trace_id: str | None = None) -> list[TraceEvent]:
        """Load a trace from either JSONL or SQLite based on file extension."""
        p = Path(path)
        if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            return cls.load_sqlite(p, trace_id=trace_id)
        return cls.load_jsonl(p)

    @classmethod
    def save_auto(cls, events: list[TraceEvent], path: str | Path) -> Path:
        """Save a trace to either JSONL or SQLite based on file extension."""
        p = Path(path)
        if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            return cls.save_sqlite(events, p)
        return cls.save_jsonl(events, p)


class TraceRecorder:
    """Records deterministic AI agent & MCP trajectories with SHA-256 hash chaining."""

    def __init__(
        self,
        trace_id: str | None = None,
        seed: int = 42,
        deterministic_clock: bool = False,
    ) -> None:
        self.trace_id = trace_id or f"tr-{uuid.uuid4().hex[:12]}"
        self.seed = seed
        self.rng = random.Random(seed)
        self.deterministic_clock = deterministic_clock
        self._base_ns = 1_700_000_000_000_000_000 if deterministic_clock else time.time_ns()
        self._events: list[TraceEvent] = []
        self._state: dict[str, Any] = {}
        self._prev_hash = GENESIS_HASH

    @property
    def events(self) -> list[TraceEvent]:
        """Return a shallow copy of recorded events."""
        return list(self._events)

    @property
    def state(self) -> dict[str, Any]:
        """Return a shallow copy of the current agent state."""
        return dict(self._state)

    def _next_timestamp_ns(self) -> int:
        if self.deterministic_clock:
            return self._base_ns + len(self._events) * 1_000_000
        return time.time_ns()

    def record_event(
        self,
        event_type: EventType | str,
        name: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        state_update: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> TraceEvent:
        """Append a cryptographically sealed event to the trajectory."""
        if state_update:
            self._state.update(state_update)

        ev = TraceEvent(
            trace_id=self.trace_id,
            seq=len(self._events),
            event_type=event_type.value if isinstance(event_type, EventType) else str(event_type),
            name=name,
            input_data=dict(input_data or {}),
            output_data=dict(output_data or {}),
            state_snapshot=dict(self._state),
            seed=self.seed,
            timestamp_ns=self._next_timestamp_ns(),
            duration_ms=float(duration_ms),
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            prev_hash=self._prev_hash,
        ).seal()

        self._prev_hash = ev.event_hash
        self._events.append(ev)
        return ev

    def record_seed_init(self, metadata: dict[str, Any] | None = None) -> TraceEvent:
        """Record the initial RNG seed and environment metadata."""
        return self.record_event(
            EventType.SEED_INIT,
            name="seed_init",
            input_data={"seed": self.seed, **(metadata or {})},
            output_data={"rng_sample": round(self.rng.random(), 8)},
            state_update={"initialized": True, "seed": self.seed},
            duration_ms=0.05,
        )

    def record_llm_call(
        self,
        model: str,
        prompt: str,
        response: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
        state_update: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record an LLM inference span."""
        return self.record_event(
            EventType.LLM_CALL,
            name=model,
            input_data={"prompt": prompt, **(metadata or {})},
            output_data={"response": response},
            state_update=state_update,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        duration_ms: float = 0.0,
        state_update: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record an MCP or local tool invocation span."""
        return self.record_event(
            EventType.TOOL_CALL,
            name=tool_name,
            input_data=arguments,
            output_data=result,
            state_update=state_update,
            duration_ms=duration_ms,
        )

    def record_state_snapshot(
        self,
        label: str = "checkpoint",
        state_update: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Record an explicit state checkpoint."""
        return self.record_event(
            EventType.STATE_SNAPSHOT,
            name=label,
            input_data={"label": label},
            output_data={"state_keys": sorted((self._state | (state_update or {})).keys())},
            state_update=state_update,
            duration_ms=0.02,
        )

    def save(self, path: str | Path) -> Path:
        """Persist recorded events to JSONL or SQLite."""
        return TraceStore.save_auto(self._events, path)


def create_demo_trace(
    trace_id: str = "demo-agent-run-001",
    seed: int = 42,
) -> list[TraceEvent]:
    """Generate a realistic 7-step deterministic AI agent + MCP trajectory."""
    rec = TraceRecorder(trace_id=trace_id, seed=seed, deterministic_clock=True)
    rec.record_seed_init({"agent": "benni-coder", "mcp_protocol": "2024-11-05"})
    rec.record_llm_call(
        model="claude-sonnet-4",
        prompt="Locate the auth middleware bug and verify tests.",
        response="Plan: search auth.py via mcp:repo_search, then run pytest.",
        tokens_in=420,
        tokens_out=115,
        duration_ms=640.0,
        state_update={"phase": "plan", "target_file": "src/auth.py"},
    )
    rec.record_tool_call(
        tool_name="mcp:repo_search",
        arguments={"query": "verify_jwt", "path": "src/"},
        result={"matches": [{"file": "src/auth.py", "line": 48, "issue": "missing exp check"}]},
        duration_ms=14.2,
        state_update={"found_issue": "missing exp check"},
    )
    rec.record_state_snapshot(
        label="post_search_checkpoint",
        state_update={"phase": "patch_ready"},
    )
    rec.record_llm_call(
        model="claude-sonnet-4",
        prompt="Draft patch for src/auth.py line 48 to enforce JWT exp claim.",
        response="Applied exp validation guard in verify_jwt().",
        tokens_in=610,
        tokens_out=190,
        duration_ms=780.0,
        state_update={"phase": "patched", "patch_applied": True},
    )
    rec.record_tool_call(
        tool_name="mcp:run_tests",
        arguments={"suite": "tests/test_auth.py"},
        result={"passed": 12, "failed": 0, "status": "ok"},
        duration_ms=128.5,
        state_update={"tests_passed": True},
    )
    rec.record_llm_call(
        model="claude-sonnet-4",
        prompt="Summarize resolution for user.",
        response="Fixed JWT exp validation in src/auth.py:48; 12/12 tests pass.",
        tokens_in=310,
        tokens_out=85,
        duration_ms=410.0,
        state_update={"phase": "completed"},
    )
    return rec.events
