#!/usr/bin/env python3
"""v0.25: convert the 16 v0.24 fd13 boundary classes.  No new heuristic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.simple_fd13_portfolio import (
    KNOWN_DEAD_FD12,
    NEW_FD12_REGION,
    as_actions,
    classify_fd12_exits,
    fd13_portfolio_plateau,
    regenerate_known_dead_fd12,
)
from spider.simple_legacy_fd13_alternatives import (
    checkpoint_record,
    reveal_target_from_transition,
)
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import (
    face_down_count,
    layered_reachability,
    post_stock_identity,
)

EXPERIMENT = "simple_progressive_new_fd13_portfolio_v0_25"
BASE_SHA = "9936014b24b8b7523b216f162cb07c27504c954f"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD14_FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
CURRENT_FD13 = ROOT / "solutions" / "4925153_simple_v0_23_b281_fd13.moves.txt"
EMPTY1 = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FD12_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
FIRST_NEW = ROOT / "solutions" / "4925153_simple_v0_24_new_fd13.moves.txt"
V24_JSONL = (
    ROOT / "research" / "results" / "simple_progressive_fd14_boundary_search_v0_24" / "new_fd13_exits.jsonl"
)
V19_EXITS = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "fd12_exit_classes.jsonl"
)
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
EXITS_JSONL = OUT_DIR / "fd12_boundary_exits.jsonl"
DEAD_JSONL = OUT_DIR / "known_dead_fd12_futures.jsonl"
FD12_NEW_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_25_new_fd12.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_25_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_25_first_foundation.moves.txt"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def load_v24_rows() -> list:
    rows = [json.loads(line) for line in V24_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 16:
        raise SystemExit(f"expected 16 v0.24 exits, got {len(rows)}")
    return rows


def audit_sources(opening, prefix, fd14, current_sym: str) -> list:
    rows = load_v24_rows()
    audited = []
    for index, rec in enumerate(rows):
        local = as_actions(rec["actions"])
        full = list(prefix) + local
        end = opening.clone()
        cost = replay_actions(end, full)
        fd14_state = fd14.clone()
        reveal = reveal_target_from_transition(fd14_state, end)
        cp = checkpoint_record(
            end, arm=f"v024_{index}", path_length=len(full), cost=cost, kind="NEW_FD13_SOURCE"
        )
        ok = (
            cp["fd"] == 13
            and cp["stock"] == 0
            and cp["foundations"] == 0
            and reveal.get("signature_key") == "c11"
            and cp["ordered_digest"] == rec["ordered_digest"]
            and cp["symmetry_digest"] == rec["symmetry_digest"]
            and cp["symmetry_digest"] != current_sym
        )
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "total_primitive_path": len(full),
                "mw_cost": cost,
                "local_depth": rec.get("local_depth"),
                "empties": cp["empties"],
                "longest_run": cp["longest_run"],
                "adjacencies": cp["adjacencies"],
                "movable_blocks": cp["movable_blocks"],
                "legal_action_count": cp["legal_action_count"],
                "ordered_digest": cp["ordered_digest"],
                "symmetry_digest": cp["symmetry_digest"],
                "reveal_target": reveal.get("signature_key"),
                "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in full],
            }
        )
        print(
            f"SOURCE {index} ok={ok} path={len(full)} MW={cost} run={cp['longest_run']} "
            f"legal={cp['legal_action_count']} empty={cp['empties']}",
            flush=True,
        )
    keys = [row["symmetry_digest"] for row in audited]
    if len(set(keys)) != 16:
        raise SystemExit("source symmetry keys are not 16-distinct")
    if current_sym in keys:
        raise SystemExit("a v0.24 source collapsed to CURRENT_FD13")
    if not all(row["ok"] for row in audited):
        raise SystemExit("SOURCE_REPLAY_FAILURE")
    return audited


def write_dead_jsonl(members: set, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for digest in sorted(members):
            handle.write(json.dumps({"symmetry_digest": digest}) + "\n")


def choose_verdict(audit_ok, phase2, classified, phase3) -> tuple[str, str]:
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "the v0.24 portfolio could not be reconstructed"
    if phase2.foundation_witness or (phase3 and (phase3.get("max_foundations") or 0) >= 1):
        return "NEW_FD13_PORTFOLIO_REACHES_FOUNDATION", "a v0.24 alternative reached a foundation"
    if phase2.stronger_progress and (phase2.stronger_progress.get("fd") or 99) <= 10:
        return "NEW_FD13_PORTFOLIO_REACHES_FD10", "unexpected fd<=10 from the fd13 plateau"
    if phase3 and (phase3.get("min_fd") or 99) <= 10:
        return "NEW_FD13_PORTFOLIO_REACHES_FD10", "a v0.24 alternative reached replay-valid fd10"
    new_n = sum(1 for r in classified if r["class"] == NEW_FD12_REGION)
    dead_n = sum(1 for r in classified if r["class"] == KNOWN_DEAD_FD12)
    if phase2.stop_reason in ("unique limit", "time limit", "rss abort") and phase2.completed_expanded_depth < 4:
        return "NEW_FD13_PORTFOLIO_STATE_EXPLOSION", "limits bound before a useful short-horizon comparison"
    if not classified:
        if phase2.stop_reason in ("unique limit", "time limit", "rss abort"):
            return "NEW_FD13_PORTFOLIO_STATE_EXPLOSION", "limits bound with no fd12 boundary exit"
        return "NEW_FD13_PORTFOLIO_NO_SHORT_FD12", "no fd12 boundary exit through the depth-12 envelope"
    if new_n == 0 and dead_n:
        return (
            "NEW_FD13_PORTFOLIO_ONLY_KNOWN_DEAD_FD12",
            "every fd12 exit belongs to an exact certified dead future",
        )
    if new_n and phase3 and phase3.get("exhausted") and (phase3.get("min_fd") or 99) > 10:
        return (
            "NEW_FD13_PORTFOLIO_FINDS_NEW_FD12_BUT_THEY_STALL",
            "new fd12 regions exhaust without fd10 or foundation",
        )
    if new_n and phase3 and not phase3.get("exhausted"):
        return (
            "NEW_FD13_PORTFOLIO_FINDS_NEW_FD12_REGION",
            "new fd12 region(s) reached; downstream viability unresolved because limits bind",
        )
    if new_n and not phase3:
        return "NEW_FD13_PORTFOLIO_FINDS_NEW_FD12_REGION", "new fd12 region(s) reached; phase 3 did not run"
    return "INCONCLUSIVE", f"unclassified stop={phase2.stop_reason}"


def next_recommendation(verdict: str) -> str:
    if verdict in ("NEW_FD13_PORTFOLIO_REACHES_FD10", "NEW_FD13_PORTFOLIO_REACHES_FOUNDATION"):
        return (
            "SAME c11 REVEAL, DIFFERENT ARRANGEMENT, DIFFERENT FUTURE. Continue exact search "
            "from the successful v0.24 source. Do not add a heuristic."
        )
    if verdict == "NEW_FD13_PORTFOLIO_FINDS_NEW_FD12_BUT_THEY_STALL":
        return (
            "This 16-state cluster is downstream-unproductive. Next: resume v0.24-style "
            "fd14 boundary search on the four untouched root frontiers. Do not add a heuristic."
        )
    if verdict == "NEW_FD13_PORTFOLIO_ONLY_KNOWN_DEAD_FD12":
        return (
            "The 16 new fd13 doors reopen only already-dead fd12 futures. Next: harvest more "
            "fd14 boundary exits from the untouched root arms. Do not add a heuristic."
        )
    if verdict == "NEW_FD13_PORTFOLIO_NO_SHORT_FD12":
        return (
            "No short conversion in this envelope; the 16 states are not proven dead. Next: "
            "either a deeper exact fd13 probe of this portfolio or more fd14 exits. Do not add a heuristic."
        )
    if verdict == "NEW_FD13_PORTFOLIO_FINDS_NEW_FD12_REGION":
        return (
            "Continue exact search from the harvested new fd12 classes. fd10 remains the milestone. "
            "Do not add a heuristic."
        )
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Reconstruct the v0.24 witnesses before any further conversion test."
    return "Do not invent a heuristic. Keep testing exact harvested fd13 checkpoints or resume fd14 boundary search."


def write_report(payload: dict) -> None:
    p2 = payload.get("phase2") or {}
    p3 = payload.get("phase3") or {}
    lines = [
        "# Simple Progressive Search v0.25 — New FD13 Boundary-Portfolio Conversion",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Previous verdict: `FD14_BOUNDARY_FINDS_NEW_FD13_EXIT`",
        "- No new heuristic. No fresh fd14 search. No untouched-root expansion.",
        "",
        "## 2. Source audit",
        "",
        f"- sources={payload.get('n_sources')} distinct_sym={payload.get('distinct_source_syms')} "
        f"path_range={payload.get('source_path_range')} MW_range={payload.get('source_mw_range')}",
        f"- current_fd13_path=101 current_to_fd12=+9",
        "",
        "| Source set | fd13 total path | Local search | FD12 exits | New FD12 regions | Reaches fd10 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Historical/current | 101 | known +9 | known | 0 established | no established |",
        f"| v0.24 new portfolio | {payload.get('source_path_range')} | <=12 BFS | "
        f"{p2.get('exit_classes')} | {payload.get('new_fd12_classes')} | "
        f"{'yes' if payload.get('fd10') else 'no'} |",
        "",
        "## 3. Known-dead cache",
        "",
        json.dumps({k: v for k, v in (payload.get("dead_cache") or {}).items() if k != "members"}, indent=2),
        "",
        "## 4. Phase 2",
        "",
        f"- unique={p2.get('unique')} expanded={p2.get('expanded')} generated={p2.get('generated')} "
        f"dups={p2.get('duplicate_skips')} cross_origin={p2.get('cross_origin_dups')}",
        f"- completed_expanded={p2.get('completed_expanded_depth')} generated_depth={p2.get('completed_generated_depth')} "
        f"stop={p2.get('stop_reason')} exhausted={p2.get('exhausted')}",
        f"- fd12 edges={p2.get('exit_edges')} classes={p2.get('exit_classes')} "
        f"known_dead={payload.get('known_dead_fd12_classes')} new={payload.get('new_fd12_classes')}",
        f"- current_fd13_hits={p2.get('watch_hits', {}).get('current_fd13', 0)} "
        f"empty1_hits={p2.get('watch_hits', {}).get('current_empty1', 0)}",
        f"- elapsed_s={p2.get('elapsed_s')} rss_mb={p2.get('peak_rss_mb')}",
        "",
        "## 5. Phase 3",
        "",
    ]
    if not p3.get("ran"):
        lines.append(f"Skipped: {p3.get('reason')}")
        lines.append("")
    else:
        lines.append(
            f"- sources={p3.get('sources')} unique={p3.get('unique')} stop={p3.get('stop_reason')} "
            f"min_fd={p3.get('min_fd')} fnd={p3.get('max_foundations')} exhausted={p3.get('exhausted')} "
            f"known_dead_prunes={p3.get('known_dead_prunes')} elapsed={p3.get('elapsed_s')} rss={p3.get('peak_rss_mb')}"
        )
        lines.append("")
    lines.extend(
        [
            "## 6. Exactly one next recommendation",
            "",
            payload.get("next_recommendation", ""),
            "",
            "## Integrity",
            "",
            f"Verdict {payload.get('verdict')}. fd10={payload.get('fd10')} foundation={payload.get('foundation')}.",
            "",
            f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
            "No new heuristic. No fresh fd14 search. No production change.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    prefix = parse_moves_file(FD14_FIXTURE)
    fd14 = opening.clone()
    replay_actions(fd14, prefix)
    current_actions = parse_moves_file(CURRENT_FD13)
    current = opening.clone()
    replay_actions(current, current_actions)
    current_sym = post_stock_identity(current)
    empty1_actions = parse_moves_file(EMPTY1)
    empty1 = opening.clone()
    replay_actions(empty1, empty1_actions)
    print(
        f"CURRENT path={len(current_actions)} fd={face_down_count(current)} "
        f"sym={current_sym.hex()[:24]}",
        flush=True,
    )
    audited = audit_sources(opening, prefix, fd14, current_sym.hex())
    sources = []
    origin_paths = []
    for row in audited:
        st = unpack_state(bytes.fromhex(row["ordered_digest"]))
        sources.append(st)
        origin_paths.append(as_actions(row["full_actions"]))

    fd12_actions = parse_moves_file(FD12_FIXTURE)
    fd12 = opening.clone()
    replay_actions(fd12, fd12_actions)
    extra_sources = []
    extra_paths = []
    fd13_empty_actions = parse_moves_file(EMPTY1)
    if V19_EXITS.exists():
        for line in V19_EXITS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("class") != "NEW_FD12_EXIT":
                continue
            local = as_actions(rec["actions"])
            st = opening.clone()
            replay_actions(st, fd13_empty_actions)
            replay_actions(st, local)
            if face_down_count(st) == 12:
                extra_sources.append(st)
                extra_paths.append(list(fd13_empty_actions) + local)
    print(f"DEAD extra new-fd12 sources={len(extra_sources)}", flush=True)
    dead_meta = regenerate_known_dead_fd12(fd12, extra_sources, extra_paths=extra_paths)
    members = dead_meta.pop("members")
    write_dead_jsonl(members, DEAD_JSONL)
    dead_brief = {k: v for k, v in dead_meta.items()}
    print(
        f"KNOWN_DEAD_FD12_FUTURES union={dead_brief['union']} a={dead_brief['set_a']} "
        f"b={dead_brief['set_b']} overlap={dead_brief['overlap']}",
        flush=True,
    )

    print("PHASE2 START 16-source fd13 plateau depth_cap=12", flush=True)
    phase2 = fd13_portfolio_plateau(
        sources,
        origin_paths=origin_paths,
        plateau_fd=13,
        max_depth=12,
        max_unique=1_250_000,
        time_limit_s=1200.0,
        rss_abort_mb=3 * 1024.0,
        watch_identities={
            "current_fd13": current_sym,
            "current_empty1": post_stock_identity(empty1),
        },
    )
    print(
        f"PHASE2 unique={phase2.unique} exp={phase2.expanded} gen={phase2.generated} "
        f"dups={phase2.duplicate_skips} exits={phase2.exit_classes} edges={phase2.exit_edges} "
        f"stop={phase2.stop_reason} depth={phase2.completed_expanded_depth} "
        f"current_hits={phase2.watch_hits} elapsed={phase2.elapsed_s:.1f} rss={phase2.peak_rss_mb}",
        flush=True,
    )
    classified = classify_fd12_exits(phase2.exits, members)
    new_rows = [row for row in classified if row["class"] == NEW_FD12_REGION]
    dead_rows = [row for row in classified if row["class"] == KNOWN_DEAD_FD12]
    with EXITS_JSONL.open("w", encoding="utf-8") as handle:
        for rec in classified:
            handle.write(json.dumps(rec) + "\n")
    first_new_fd12 = None
    if new_rows:
        rec = min(new_rows, key=lambda r: (r["depth"], r.get("origin", 0)))
        origin = rec["origin"]
        full = list(origin_paths[origin]) + as_actions(rec["actions"])
        FD12_NEW_FIXTURE.write_text(
            format_moves_text(
                full,
                header="\n".join(
                    [
                        "# v0.25 first NEW_FD12_REGION from v0.24 fd13 portfolio",
                        f"# source_id: {origin}",
                        f"# local_depth: {rec['depth']}",
                        f"# symmetry: {rec['symmetry_digest']}",
                    ]
                ),
            ),
            encoding="utf-8",
        )
        first_new_fd12 = dict(rec)
        first_new_fd12["fixture"] = FD12_NEW_FIXTURE.relative_to(ROOT).as_posix()
        first_new_fd12["full_path_length"] = len(full)

    phase3 = {"ran": False, "reason": "no NEW_FD12_REGION"}
    if new_rows:
        p3_sources = []
        p3_paths = []
        for rec in new_rows:
            origin = rec["origin"]
            st = sources[origin].clone()
            replay_actions(st, as_actions(rec["actions"]))
            p3_sources.append(st)
            p3_paths.append(list(origin_paths[origin]) + as_actions(rec["actions"]))
        dead_bytes = {bytes.fromhex(h) for h in members}
        print(f"PHASE3 START sources={len(p3_sources)}", flush=True)
        cont = layered_reachability(
            sources=p3_sources,
            origin_paths=p3_paths,
            max_depth=10_000,
            max_unique=1_000_000,
            time_limit_s=1200.0,
            rss_abort_mb=4 * 1024.0,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            dead_identities=dead_bytes,
            checkpoints=(8, 16, 24, 32),
        )
        print(
            f"PHASE3 unique={cont.unique} stop={cont.stop_reason} min_fd={cont.min_fd} "
            f"fnd={cont.max_foundations} prunes={cont.known_dead_prunes} "
            f"elapsed={cont.elapsed_s:.1f} rss={cont.peak_rss_mb}",
            flush=True,
        )
        phase3 = {
            "ran": True,
            "sources": len(p3_sources),
            "unique": cont.unique,
            "generated": cont.generated,
            "duplicate_skips": cont.duplicate_skips,
            "stop_reason": cont.stop_reason,
            "exhausted": cont.stop_reason == "frontier empty",
            "min_fd": cont.min_fd,
            "max_foundations": cont.max_foundations,
            "known_dead_prunes": cont.known_dead_prunes,
            "elapsed_s": cont.elapsed_s,
            "peak_rss_mb": cont.peak_rss_mb,
            "fresh_tt": cont.fresh_tt,
        }
        fd10 = cont.witnesses.get("fd_le_10")
        fnd = cont.witnesses.get("foundation")
        if fd10:
            origin = fd10.get("origin", 0)
            full = list(p3_paths[origin]) + as_actions(fd10.get("actions") or [])
            FD10_FIXTURE.write_text(format_moves_text(full, header="# v0.25 fd10 from new fd13 portfolio"), encoding="utf-8")
            phase3["fd10_fixture"] = FD10_FIXTURE.relative_to(ROOT).as_posix()
            phase3["fd10"] = fd10
        if fnd:
            origin = fnd.get("origin", 0)
            full = list(p3_paths[origin]) + as_actions(fnd.get("actions") or [])
            FOUNDATION_FIXTURE.write_text(
                format_moves_text(full, header="# v0.25 foundation from new fd13 portfolio"), encoding="utf-8"
            )
            phase3["foundation_fixture"] = FOUNDATION_FIXTURE.relative_to(ROOT).as_posix()
            phase3["foundation"] = fnd

    paths = [row["total_primitive_path"] for row in audited]
    costs = [row["mw_cost"] for row in audited]
    p2_brief = {
        "unique": phase2.unique,
        "expanded": phase2.expanded,
        "generated": phase2.generated,
        "duplicate_skips": phase2.duplicate_skips,
        "exit_edges": phase2.exit_edges,
        "exit_classes": phase2.exit_classes,
        "completed_expanded_depth": phase2.completed_expanded_depth,
        "completed_generated_depth": phase2.completed_generated_depth,
        "stop_reason": phase2.stop_reason,
        "exhausted": phase2.exhausted,
        "min_fd": phase2.min_fd,
        "cross_origin_dups": phase2.cross_origin_dups,
        "watch_hits": phase2.watch_hits,
        "first_watch": phase2.first_watch,
        "layers": phase2.layers,
        "elapsed_s": phase2.elapsed_s,
        "peak_rss_mb": phase2.peak_rss_mb,
        "domain_violations": phase2.domain_violations,
        "heuristic": False,
        "all_legal_tableau": True,
    }
    verdict, reason = choose_verdict(True, phase2, classified, phase3)
    if verdict == "NEW_FD13_PORTFOLIO_REACHES_FD10":
        interpretation = "SAME c11 REVEAL, DIFFERENT ARRANGEMENT, DIFFERENT FUTURE."
    elif verdict == "NEW_FD13_PORTFOLIO_ONLY_KNOWN_DEAD_FD12":
        interpretation = (
            "The 16 new fd13 checkpoints reopen only already-certified dead fd12 futures. "
            "Same card, different arrangement, same downstream deadness in this envelope."
        )
    elif verdict == "NEW_FD13_PORTFOLIO_NO_SHORT_FD12":
        interpretation = "No short conversion in this envelope. The 16 states are not proven dead."
    elif verdict == "NEW_FD13_PORTFOLIO_FINDS_NEW_FD12_BUT_THEY_STALL":
        interpretation = "New fd12 regions exist from this portfolio but their exact futures stall."
    else:
        interpretation = reason
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-new-fd13-portfolio-v0-25",
        "previous_verdict": "FD14_BOUNDARY_FINDS_NEW_FD13_EXIT",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "n_sources": len(audited),
        "distinct_source_syms": len({row["symmetry_digest"] for row in audited}),
        "source_path_range": f"{min(paths)}-{max(paths)}" if len(set(paths)) > 1 else str(paths[0]),
        "source_mw_range": f"{min(costs)}-{max(costs)}" if len(set(costs)) > 1 else str(costs[0]),
        "sources": audited,
        "dead_cache": dead_brief,
        "phase2": p2_brief,
        "known_dead_fd12_classes": len(dead_rows),
        "new_fd12_classes": len(new_rows),
        "first_new_fd12": first_new_fd12,
        "phase3": phase3,
        "fd10": bool(phase3.get("fd10") or (phase3.get("min_fd") or 99) <= 10),
        "foundation": bool(phase3.get("foundation") or (phase3.get("max_foundations") or 0) >= 1),
        "current_fd13_convergence": (phase2.watch_hits.get("current_fd13") or 0) > 0,
        "current_empty1_convergence": (phase2.watch_hits.get("current_empty1") or 0) > 0,
        "no_new_heuristic": True,
        "no_fresh_fd14_search": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
