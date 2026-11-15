"""Tests for TraceRecorder, TraceStore (JSONL & SQLite), and SHA-256 hash chaining."""

from pathlib import Path

from agent_trace_replay.models import GENESIS_HASH, verify_trace_chain
from agent_trace_replay.recorder import TraceRecorder, TraceStore, create_demo_trace


def test_deterministic_recording_and_sha256_chain():
    rec1 = TraceRecorder(trace_id="tr-det", seed=99, deterministic_clock=True)
    rec1.record_seed_init({"env": "ci"})
    rec1.record_llm_call("gpt-4o", "ping", "pong", tokens_in=10, tokens_out=5, duration_ms=12.5)
    rec1.record_tool_call("mcp:grep", {"q": "auth"}, {"hits": 2}, duration_ms=3.1)

    rec2 = TraceRecorder(trace_id="tr-det", seed=99, deterministic_clock=True)
    rec2.record_seed_init({"env": "ci"})
    rec2.record_llm_call("gpt-4o", "ping", "pong", tokens_in=10, tokens_out=5, duration_ms=12.5)
    rec2.record_tool_call("mcp:grep", {"q": "auth"}, {"hits": 2}, duration_ms=3.1)

    assert len(rec1.events) == 3
    assert rec1.events[0].prev_hash == GENESIS_HASH
    assert rec1.events[1].prev_hash == rec1.events[0].event_hash
    assert [e.event_hash for e in rec1.events] == [e.event_hash for e in rec2.events]

    valid, errors = verify_trace_chain(rec1.events)
    assert valid is True
    assert errors == []


def test_tamper_detection_breaks_sha256_chain():
    events = create_demo_trace()
    valid, _ = verify_trace_chain(events)
    assert valid is True

    # Tamper with step 2 output
    events[2].output_data["matches"] = []
    valid_after, errors = verify_trace_chain(events)
    assert valid_after is False
    assert any("SHA-256 integrity mismatch" in err for err in errors)


def test_jsonl_persistence_roundtrip(tmp_path: Path):
    events = create_demo_trace(trace_id="tr-jsonl")
    out = tmp_path / "trace.jsonl"
    TraceStore.save_auto(events, out)
    loaded = TraceStore.load_auto(out)

    assert len(loaded) == len(events)
    assert [e.event_hash for e in loaded] == [e.event_hash for e in events]
    valid, errors = verify_trace_chain(loaded)
    assert valid is True
    assert errors == []


def test_sqlite_persistence_roundtrip_and_listing(tmp_path: Path):
    db = tmp_path / "traces.sqlite"
    ev1 = create_demo_trace(trace_id="tr-sql-1", seed=1)
    ev2 = create_demo_trace(trace_id="tr-sql-2", seed=2)

    TraceStore.save_sqlite(ev1, db)
    TraceStore.save_sqlite(ev2, db)

    listed = TraceStore.list_sqlite_traces(db)
    assert len(listed) == 2
    assert {item["trace_id"] for item in listed} == {"tr-sql-1", "tr-sql-2"}

    loaded_1 = TraceStore.load_sqlite(db, trace_id="tr-sql-1")
    assert len(loaded_1) == 7
    assert loaded_1[0].seed == 1
    valid, _ = verify_trace_chain(loaded_1)
    assert valid is True

    loaded_latest = TraceStore.load_auto(db)
    assert loaded_latest[0].trace_id == "tr-sql-2"
