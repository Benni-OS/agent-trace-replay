"""Command-line interface (`trace-replay`) for agent-trace-replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .forker import CounterfactualForker, ForkOverride
from .mcp_server import MCPServer
from .models import verify_trace_chain
from .recorder import TraceStore, create_demo_trace
from .replayer import TraceReplayer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trace-replay",
        description="Zero-Cloud Time-Travel Debugger, Deterministic Trajectory Replay & Counterfactual Forking",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # record-demo
    p_demo = sub.add_parser("record-demo", help="Record a deterministic 7-step AI agent + MCP demo trace.")
    p_demo.add_argument("--out", default=".traces/demo.jsonl", help="Output path (.jsonl or .sqlite).")
    p_demo.add_argument("--seed", type=int, default=42, help="Deterministic RNG seed.")
    p_demo.add_argument("--trace-id", default="demo-agent-run-001", help="Trace identifier.")

    # inspect
    p_insp = sub.add_parser("inspect", help="Time-travel inspect a recorded trace or specific step.")
    p_insp.add_argument("trace_path", help="Path to .jsonl or .sqlite trace file.")
    p_insp.add_argument("--seq", type=int, default=None, help="Step index to inspect.")
    p_insp.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output.")

    # replay
    p_rep = sub.add_parser("replay", help="Replay a recorded trajectory offline with $0.00 token burn.")
    p_rep.add_argument("trace_path", help="Path to .jsonl or .sqlite trace file.")
    p_rep.add_argument("--strict", action="store_true", help="Fail on empty tool/LLM outputs.")
    p_rep.add_argument("--no-verify-chain", action="store_true", help="Skip SHA-256 chain verification.")
    p_rep.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output.")

    # fork
    p_fork = sub.add_parser("fork", help="Counterfactual fork from step N with modified output or prompt.")
    p_fork.add_argument("trace_path", help="Path to base trace file.")
    p_fork.add_argument("--seq", type=int, required=True, help="Step index N to branch from.")
    p_fork.add_argument("--output-override", default=None, help="JSON object string for new output_data.")
    p_fork.add_argument("--prompt-override", default=None, help="New prompt string for step N.")
    p_fork.add_argument("--out", default=None, help="Output path for the forked trace.")
    p_fork.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output.")

    # diff
    p_diff = sub.add_parser("diff", help="Compare two trajectories and show structural/token/latency deltas.")
    p_diff.add_argument("base_path", help="Path to base trace file.")
    p_diff.add_argument("fork_path", help="Path to forked trace file.")
    p_diff.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output.")

    # mcp
    sub.add_parser("mcp", help="Start the native JSON-RPC 2.0 stdio MCP server.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "record-demo":
        events = create_demo_trace(trace_id=args.trace_id, seed=args.seed)
        saved = TraceStore.save_auto(events, args.out)
        print(f"Recorded {len(events)} SHA-256 chained events -> {saved}")
        return 0

    if args.command == "inspect":
        events = TraceStore.load_auto(args.trace_path)
        chain_valid, errors = verify_trace_chain(events)
        replayer = TraceReplayer(events)
        if args.seq is not None:
            info = replayer.inspect_step(args.seq)
            info["chain_valid"] = chain_valid
            if args.as_json:
                print(json.dumps(info, indent=2, ensure_ascii=False))
            else:
                print(f"[{info['trace_id']}] Step {info['seq']}/{info['total_steps'] - 1}: {info['event_type']} -> {info['name']}")
                print(f"  Hash Valid : {info['hash_valid']} ({info['event_hash'][:16]}...)")
                print(f"  Tokens Cum : {info['cumulative_tokens']} | Latency Cum: {info['cumulative_duration_ms']}ms")
                print(f"  State      : {json.dumps(info['state_snapshot'])}")
                print(f"  Output     : {json.dumps(info['output_data'])}")
            return 0 if chain_valid else 1

        summary = {
            "trace_id": events[0].trace_id if events else "empty",
            "total_steps": len(events),
            "chain_valid": chain_valid,
            "errors": errors,
            "total_tokens": sum(e.tokens_in + e.tokens_out for e in events),
            "total_duration_ms": round(sum(e.duration_ms for e in events), 3),
        }
        if args.as_json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            print(f"Trace: {summary['trace_id']} ({summary['total_steps']} steps)")
            print(f"SHA-256 Chain: {'VALID' if chain_valid else 'BROKEN'}")
            print(f"Total Tokens: {summary['total_tokens']} | Duration: {summary['total_duration_ms']}ms")
            for ev in events:
                print(f"  [{ev.seq}] {ev.event_type:<14} {ev.name:<20} ({ev.tokens_in + ev.tokens_out} tok, {ev.duration_ms:.1f}ms)")
        return 0 if chain_valid else 1

    if args.command == "replay":
        events = TraceStore.load_auto(args.trace_path)
        replayer = TraceReplayer(events)
        res = replayer.replay(verify_chain=not args.no_verify_chain, strict=args.strict)
        if args.as_json:
            print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"Replayed {res.replayed_steps}/{res.total_steps} steps offline in {res.replay_duration_ms:.3f}ms")
            print(f"Zero-Token Burn: $0.00 ({res.tokens_saved} tokens saved) | Chain Valid: {res.chain_valid} | Drift: {res.drift_detected}")
            for v in res.violations:
                print(f"  [VIOLATION] step={v.seq} {v.kind}: {v.message}")
        return 0 if (res.chain_valid and not res.drift_detected) else 1

    if args.command == "fork":
        events = TraceStore.load_auto(args.trace_path)
        new_out = json.loads(args.output_override) if args.output_override else None
        override = ForkOverride(seq=args.seq, new_output=new_out, new_prompt=args.prompt_override)
        fork_res = CounterfactualForker.fork(events, override)
        src = Path(args.trace_path)
        out_path = args.out or str(src.with_name(f"{src.stem}.fork-{args.seq}{src.suffix}"))
        saved = TraceStore.save_auto(fork_res.events, out_path)
        if args.as_json:
            payload = fork_res.to_dict()
            payload["saved_path"] = str(saved)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Forked {fork_res.base_trace_id} at step {fork_res.fork_seq} -> {saved}")
            print(f"Summary: {fork_res.diff.divergence_summary}")
        return 0

    if args.command == "diff":
        base_events = TraceStore.load_auto(args.base_path)
        fork_events = TraceStore.load_auto(args.fork_path)
        diff_res = CounterfactualForker.diff(base_events, fork_events)
        if args.as_json:
            print(json.dumps(diff_res.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(diff_res.divergence_summary)
            for sd in diff_res.step_diffs:
                if sd.status != "identical":
                    print(f"  [{sd.seq}] {sd.status.upper()} ({sd.name}) fields={list(sd.field_diffs.keys())} tok={sd.token_delta:+d}")
        return 0

    if args.command == "mcp":
        MCPServer().serve_stdio()
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
