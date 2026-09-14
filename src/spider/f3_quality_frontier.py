"""v0.82 quality-diverse F3 harvest and proof-aware bridge screening.

Discovers new stock-empty F3 states from the autonomous g129 F2 root,
then screens them with short proof-aware next-foundation probes.
Canonical 172 is not read. Exhausted v0.80/v0.81 roots are not resumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.f3_tactical_bridge import (
    BRIDGE_CEILING,
    F4_PORTFOLIO_MAX,
    assembly_slack,
    load_g141_record,
    search_f4_portfolio,
    select_f4_portfolio,
)
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.proof_aware_tactical_bridge import (
    COMPLETE_EXHAUSTION_NOTE,
    ExactHCache,
    inspect_stock_empty_root,
    interpret_continuation_stop,
    is_proof_viable,
    load_g158_record,
    probe_proof_aware_target,
    recommend_continue_from_roots,
)
from spider.research_actions import as_actions, dump_actions, face_down_count, is_deal, stock_rows, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V080_JSON = ROOT / "docs" / "research" / "proof_aware_tactical_bridge_v0_80.json"
V081_JSON = ROOT / "docs" / "research" / "g158_proof_aware_f4_v0_81.json"

HARVEST_S = 240.0
HARVEST_UNIQUE = 300_000
STAGE_A_S = 10.0
STAGE_A_UNIQUE = 80_000
STAGE_B_S = 20.0
STAGE_B_ROOTS = 4
STAGE_B_TARGETS = 2
STAGE_B_UNIQUE = 80_000
MAX_ACTIVE_F3 = 6
PORTFOLIO_MAX = F4_PORTFOLIO_MAX
TOTAL_S = SEARCH_TIME_S
CONTINUATION_RESERVE_S = 150.0
HARVEST_LANES = ("cost", "reveal", "construction", "readiness", "economy", "completion")
G141_CONTROL = {"g": 141, "h": 33, "f": 174, "bridge_loss": 12, "best_next_f": 186}
G158_CONTROL = {"g": 158, "h": 22, "f": 180, "bridge_loss": 5, "best_next_f": 185}


def f3_harvest_terminal_fn(state) -> bool:
    return len(state.foundations) >= 3


def bridge_loss(root_f, terminal_f):
    if root_f is None or terminal_f is None:
        return None
    return int(terminal_f) - int(root_f)


def next_foundation_quality(f: int, ceiling: int = BRIDGE_CEILING) -> str:
    if int(f) <= 184:
        return "STRONG_SURPLUS"
    if int(f) == 185:
        return "SURPLUS_1"
    if int(f) == 186:
        return "ZERO_SLACK"
    if int(f) <= int(ceiling):
        return "VIABLE"
    return "RAW"


def verify_g129_root(opening=None) -> dict:
    rec = reconstruct_g128_root(opening)
    if not rec.get("ok"):
        return {"ok": False, "reason": rec.get("verdict") or "g129_reconstruct_failed", "raw": rec}
    post = rec["post"]
    expected = {
        "g": 129,
        "foundations": 2,
        "face_down": 2,
        "stock_rows": 0,
        "assembly_h": 43,
        "assembly_f": 172,
    }
    mismatches = {
        k: {"expected": v, "got": post.get(k)}
        for k, v in expected.items()
        if post.get(k) != v
    }
    ok = (
        post.get("ok")
        and not mismatches
        and int(post.get("deal_cost") or 0) == 1
        and not post.get("can_deal", False)
    )
    return {
        "ok": bool(ok),
        "reason": None if ok else "g129_recompute_mismatch",
        "mismatches": mismatches,
        "g": post.get("g"),
        "foundations": post.get("foundations"),
        "face_down": post.get("face_down"),
        "stock_rows": post.get("stock_rows"),
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
        "ordered_digest": post.get("ordered_digest"),
        "whole_game_identity": post.get("whole_game_identity"),
        "full_actions": post.get("full_actions"),
        "legal_tableau": post.get("legal_tableau"),
        "empty_n": post.get("empty_n"),
        "v076_digest_match": post.get("v076_digest_match"),
        "post": post,
        "g123": rec.get("g123"),
        "g128": rec.get("g128"),
    }


def control_digests() -> dict:
    g141 = load_g141_record()
    g158 = load_g158_record()
    return {
        "g141": g141.get("ordered_digest"),
        "g158": g158.get("ordered_digest"),
        "g141_ident": pack_whole_game_identity(unpack_state(bytes.fromhex(g141["ordered_digest"]))).hex(),
        "g158_ident": pack_whole_game_identity(unpack_state(bytes.fromhex(g158["ordered_digest"]))).hex(),
    }


def load_closed_root_table() -> dict:
    """Exact identities of v0.80/v0.81 continuation roots. No similarity."""

    table: Dict[str, dict] = {}
    for path, label in ((V080_JSON, "v080"), (V081_JSON, "v081")):
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for rec in (data.get("bridge") or {}).get("f4_roots") or []:
            digest = rec.get("ordered_digest")
            if not digest:
                continue
            st = unpack_state(bytes.fromhex(digest))
            ident = pack_whole_game_identity(st).hex()
            prev = table.get(ident)
            g = int(rec.get("g") or 0)
            if prev is None or g < int(prev["g"]):
                table[ident] = {
                    "ident": ident,
                    "ordered_digest": digest,
                    "g": g,
                    "source": label,
                    "assembly_f": rec.get("assembly_f"),
                    "foundations": rec.get("foundations"),
                }
    return table


def is_known_closed(ident: str, g: int, table: dict) -> bool:
    rec = table.get(ident)
    if rec is None:
        return False
    return int(g) >= int(rec["g"])


def enrich_stock_empty_state(digest: str, g: int, *, cache: Optional[ExactHCache] = None) -> dict:
    state = unpack_state(bytes.fromhex(digest))
    s = current_tableau_summary(state)
    ranked = rank_ready_suits(state, g=int(g))
    h_fn = cache if cache is not None else stock_empty_assembly_h
    h = int(h_fn(state, int(g)))
    f = int(g) + h
    remaining = []
    counts: Dict[str, int] = {}
    for suit in s["foundation_suits"]:
        counts[suit] = counts.get(suit, 0) + 1
    for i, rec in enumerate(ranked.get("ranked") or []):
        remaining.append(
            {
                "suit": rec["suit"],
                "operational_rank": i + 1,
                "already_founded": int(counts.get(rec["suit"]) or 0),
                "cover": rec.get("cover"),
                "blockers": rec.get("relevant_blockers"),
                "inaccessible_joins": rec.get("inaccessible_joins"),
                "k_access": rec.get("k_min_blockers"),
                "a_access": rec.get("a_min_blockers"),
                "gap": rec.get("gap"),
                "merge_edges": rec.get("legal_merge_edges"),
                "buried_components": rec.get("buried_components"),
                "exposed_components": rec.get("exposed_components"),
                "target_foundations_before": int(counts.get(rec["suit"]) or 0),
            }
        )
    return {
        "g": int(g),
        "foundations": len(state.foundations),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(state)),
        "boundaries": int(s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": f,
        "slack": assembly_slack(BRIDGE_CEILING, f),
        "stock_rows": stock_rows(state),
        "can_deal": bool(state.can_deal()),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "ident": pack_whole_game_identity(state).hex(),
        "ready_suits": list(ranked.get("ready_suits") or []),
        "n_ready": int(ranked.get("n_ready") or 0),
        "remaining_targets": remaining,
        "viable": is_proof_viable(int(g), h),
    }


def dedup_f3_by_identity(records: Iterable[dict]) -> List[dict]:
    best: Dict[str, dict] = {}
    for rec in records:
        ident = rec.get("ident") or rec.get("whole_game_identity")
        if not ident:
            continue
        prev = best.get(ident)
        if prev is None or int(rec["g"]) < int(prev["g"]):
            best[ident] = rec
    return sorted(best.values(), key=lambda r: (int(r["g"]), r.get("ordered_digest") or ""))


def _not_worse(a: dict, b: dict) -> bool:
    return (
        int(a["g"]) <= int(b["g"])
        and int(a["assembly_h"]) <= int(b["assembly_h"])
        and int(a["assembly_f"]) <= int(b["assembly_f"])
        and int(a["slack"]) >= int(b["slack"])
        and int(a["empty_n"]) >= int(b["empty_n"])
        and int(a["legal_tableau"]) >= int(b["legal_tableau"])
        and int(a["boundaries"]) <= int(b["boundaries"])
        and int(a["face_down"]) <= int(b["face_down"])
    )


def _strictly_better(a: dict, b: dict) -> bool:
    if not _not_worse(a, b):
        return False
    return (
        int(a["g"]) < int(b["g"])
        or int(a["assembly_h"]) < int(b["assembly_h"])
        or int(a["assembly_f"]) < int(b["assembly_f"])
        or int(a["slack"]) > int(b["slack"])
        or int(a["empty_n"]) > int(b["empty_n"])
        or int(a["legal_tableau"]) > int(b["legal_tableau"])
        or int(a["boundaries"]) < int(b["boundaries"])
        or int(a["face_down"]) < int(b["face_down"])
    )


def f3_pareto_frontier(records: Sequence[dict]) -> List[dict]:
    pool = list(records)
    out = []
    for rec in pool:
        if any(_strictly_better(other, rec) for other in pool if other is not rec):
            continue
        out.append(rec)
    return sorted(out, key=lambda r: (int(r["assembly_f"]), int(r["g"]), r.get("ordered_digest") or ""))


def mark_control_f3s(records: Sequence[dict], controls: Optional[dict] = None) -> List[dict]:
    controls = controls or control_digests()
    g141 = controls["g141"]
    g158 = controls["g158"]
    out = []
    for rec in records:
        digest = rec.get("ordered_digest")
        ident = rec.get("ident")
        tag = None
        if digest == g141 or ident == controls["g141_ident"]:
            tag = "g141_control"
        elif digest == g158 or ident == controls["g158_ident"]:
            tag = "g158_control"
        rec = dict(rec)
        rec["control_tag"] = tag
        out.append(rec)
    return out


def select_new_f3_representatives(
    records: Sequence[dict],
    *,
    controls: Optional[dict] = None,
    k: int = MAX_ACTIVE_F3,
) -> List[dict]:
    controls = controls or control_digests()
    exclude = {controls["g141"], controls["g158"], controls["g141_ident"], controls["g158_ident"]}
    pool = [
        r
        for r in records
        if r.get("ordered_digest") not in exclude and r.get("ident") not in exclude
    ]
    if not pool:
        return []
    pareto = f3_pareto_frontier(pool)
    picks: List[dict] = []
    seen: Set[str] = set()

    def take(rec: Optional[dict], role: str) -> None:
        if rec is None:
            return
        ident = rec.get("ident")
        if not ident or ident in seen:
            return
        seen.add(ident)
        item = dict(rec)
        item["selection_role"] = role
        picks.append(item)

    take(min(pool, key=lambda r: (int(r["assembly_f"]), int(r["g"]), r["ordered_digest"])), "lowest_f")
    take(min(pool, key=lambda r: (int(r["assembly_h"]), int(r["g"]), r["ordered_digest"])), "lowest_h")
    take(
        max(pool, key=lambda r: (int(r["legal_tableau"]), -int(r["g"]), r["ordered_digest"])),
        "highest_mobility",
    )
    take(max(pool, key=lambda r: (int(r["empty_n"]), -int(r["g"]), r["ordered_digest"])), "most_empties")
    take(
        min(pool, key=lambda r: (int(r["boundaries"]), int(r["g"]), r["ordered_digest"])),
        "lowest_boundaries",
    )
    remaining = [r for r in pareto if r.get("ident") not in seen]
    if remaining:
        gs = sorted(int(r["g"]) for r in remaining)
        hs = sorted(int(r["assembly_h"]) for r in remaining)
        mg = gs[len(gs) // 2]
        mh = hs[len(hs) // 2]
        take(
            min(
                remaining,
                key=lambda r: (
                    abs(int(r["g"]) - mg) + abs(int(r["assembly_h"]) - mh),
                    int(r["g"]),
                    r["ordered_digest"],
                ),
            ),
            "pareto_balanced",
        )
    for rec in sorted(pareto + pool, key=lambda r: (int(r["assembly_f"]), int(r["g"]), r["ordered_digest"])):
        if len(picks) >= int(k):
            break
        take(rec, "fill")
    return picks[: int(k)]


def harvest_f3_terminals(
    g129: dict,
    *,
    time_s: float = HARVEST_S,
    unique: int = HARVEST_UNIQUE,
    rss_abort_mb: float = SEARCH_RSS_MB,
    ceiling: int = BRIDGE_CEILING,
) -> dict:
    cache = ExactHCache()
    root = {
        "g": int(g129["g"]),
        "ordered_digest": g129["ordered_digest"],
        "symmetry_digest": g129.get("whole_game_identity") or g129["ordered_digest"],
    }
    prefix = as_actions(g129.get("full_actions") or [])
    kernel = run_search(
        [root],
        limits=SearchLimits(
            max_unique=int(unique),
            time_limit_s=float(time_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=int(ceiling),
            harvest_slack=None,
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=HARVEST_LANES,
        lane_keys_fn=strategic_lane_keys,
        is_terminal=f3_harvest_terminal_fn,
        actions_fn=tableau_actions,
        lower_bound_fn=cache,
    )
    raw = []
    for rec in kernel.terminals:
        path = kernel.reconstruct(int(rec["node"]))
        if any(is_deal(a) for a in path):
            continue
        st = unpack_state(bytes.fromhex(rec["store"]))
        if stock_rows(st) != 0:
            continue
        g = int(rec["g"])
        info = enrich_stock_empty_state(pack_state(st).hex(), g, cache=cache)
        info["full_actions"] = dump_actions(prefix + path)
        info["from_g129_actions"] = dump_actions(path)
        info["n_actions"] = len(path)
        raw.append(info)
    viable = [r for r in raw if r.get("viable") and int(r.get("foundations") or 0) >= 3]
    f3s = [r for r in viable if int(r["foundations"]) == 3]
    deduped = dedup_f3_by_identity(f3s)
    return {
        "kernel": kernel,
        "elapsed_s": kernel.elapsed_s,
        "unique": kernel.unique,
        "expanded": kernel.expanded,
        "generated": kernel.generated,
        "stop_reason": kernel.stop_reason,
        "proof_prunes": kernel.lower_bound_prunes,
        "proof_calls": kernel.lower_bound_calls,
        "h_cache": cache.stats(),
        "peak_rss_mb": kernel.peak_rss_mb,
        "n_raw_terminals": len(raw),
        "n_viable": len(viable),
        "n_f3": len(deduped),
        "f3s": deduped,
        "lane_exp": dict(kernel.lane_exp or {}),
    }


def screen_f3_targets(
    f3: dict,
    *,
    time_s: float,
    unique: int,
    stage: str,
    ceiling: int = BRIDGE_CEILING,
    suits: Optional[Sequence[str]] = None,
) -> dict:
    inspect = inspect_stock_empty_root(f3["ordered_digest"], g=int(f3["g"]))
    targets = list(inspect["remaining_targets"] or [])
    if suits is not None:
        allow = set(suits)
        targets = [t for t in targets if t.get("suit") in allow]
    probes = []
    for tgt in targets[:4]:
        probes.append(
            probe_proof_aware_target(
                {"g": int(f3["g"]), "ordered_digest": f3["ordered_digest"]},
                tgt,
                time_s=float(time_s),
                unique=int(unique),
                stage=stage,
                ceiling=int(ceiling),
            )
        )
    return aggregate_f3_probes(f3, inspect, probes)


def aggregate_f3_probes(f3: dict, inspect: dict, probes: Sequence[dict]) -> dict:
    raw = []
    viable = []
    surplus = []
    strong = []
    for pr in probes:
        raw.extend(pr.get("raw_terminals") or [])
        viable.extend(pr.get("viable_terminals") or [])
        surplus.extend(pr.get("surplus_terminals") or [])
        for rec in pr.get("viable_terminals") or []:
            rec = dict(rec)
            rec["quality"] = next_foundation_quality(int(rec["assembly_f"]))
            rec["bridge_loss"] = bridge_loss(inspect["assembly_f"], rec["assembly_f"])
            rec["root_g"] = inspect["g"]
            rec["root_h"] = inspect["assembly_h"]
            rec["root_f"] = inspect["assembly_f"]
            if rec["quality"] == "STRONG_SURPLUS":
                strong.append(rec)
    best_f = None if not viable else min(int(r["assembly_f"]) for r in viable)
    best_slack = None if not viable else max(int(r["slack"]) for r in viable)
    cheap_g = None if not viable else min(int(r["g"]) for r in viable)
    low_h = None if not viable else min(int(r["assembly_h"]) for r in viable)
    paybacks = [r.get("assembly_payback") for r in viable if r.get("assembly_payback") is not None]
    live = []
    for pr in probes:
        if pr.get("min_f_raw") is not None:
            live.append(pr)
    strongest_live = None
    if not viable and probes:
        strongest_live = min(
            probes,
            key=lambda p: (
                int(p.get("min_cover") if p.get("min_cover") is not None else 10**9),
                int(p.get("min_blockers") if p.get("min_blockers") is not None else 10**9),
                -int(p.get("unique") or 0),
            ),
        )
    return {
        "root_g": inspect["g"],
        "root_h": inspect["assembly_h"],
        "root_f": inspect["assembly_f"],
        "root_slack": inspect["slack"],
        "root_empty_n": inspect["empty_n"],
        "root_legal": inspect["legal_tableau"],
        "root_boundaries": inspect["boundaries"],
        "root_fd": inspect["face_down"],
        "ordered_digest": inspect["ordered_digest"],
        "ident": inspect["whole_game_identity"],
        "ready_suits": inspect.get("ready_suits"),
        "n_ready": inspect.get("n_ready"),
        "selection_role": f3.get("selection_role"),
        "inspect": inspect,
        "probes": list(probes),
        "raw_count": sum(int(p.get("raw_count") or 0) for p in probes),
        "viable_count": sum(int(p.get("viable_count") or 0) for p in probes),
        "surplus_count": sum(int(p.get("surplus_count") or 0) for p in probes),
        "strong_surplus_count": len(strong),
        "best_terminal_f": best_f,
        "best_slack": best_slack,
        "cheapest_terminal_g": cheap_g,
        "lowest_terminal_h": low_h,
        "bridge_loss": bridge_loss(inspect["assembly_f"], best_f),
        "best_payback": None if not paybacks else max(paybacks),
        "best_mobility": None if not viable else max(int(r["legal_tableau"]) for r in viable),
        "quality": None if best_f is None else next_foundation_quality(best_f),
        "viable_terminals": viable,
        "strong_terminals": strong,
        "strongest_live_suit": None if strongest_live is None else strongest_live.get("suit"),
        "min_live_cover": None if strongest_live is None else strongest_live.get("min_cover"),
        "min_live_blockers": None if strongest_live is None else strongest_live.get("min_blockers"),
        "min_live_f": None if not live else min(int(p["min_f_raw"]) for p in live if p.get("min_f_raw") is not None),
        "elapsed_s": sum(float(p.get("elapsed_s") or 0) for p in probes),
        "unique": sum(int(p.get("unique") or 0) for p in probes),
        "expanded": sum(int(p.get("expanded") or 0) for p in probes),
        "generated": sum(int(p.get("generated") or 0) for p in probes),
        "proof_prunes": sum(int(p.get("proof_prunes") or 0) for p in probes),
        "h_cache_calls": sum(int((p.get("h_cache") or {}).get("calls") or 0) for p in probes),
        "h_cache_hits": sum(int((p.get("h_cache") or {}).get("hits") or 0) for p in probes),
    }


def stage_a_rank_key(agg: dict) -> tuple:
    if agg.get("best_terminal_f") is not None:
        return (
            0,
            int(agg["best_terminal_f"]),
            -int(agg.get("best_slack") if agg.get("best_slack") is not None else -10**9),
            int(agg.get("bridge_loss") if agg.get("bridge_loss") is not None else 10**9),
            int(agg.get("lowest_terminal_h") if agg.get("lowest_terminal_h") is not None else 10**9),
            -int(agg.get("best_mobility") or 0),
            int(agg.get("root_g") or 0),
        )
    live_f = agg.get("min_live_f")
    if live_f is None:
        live_f = agg.get("root_f")
    return (
        1,
        int(live_f if live_f is not None else 10**9),
        int(agg.get("root_h") if agg.get("root_h") is not None else 10**9),
        int(agg.get("min_live_cover") if agg.get("min_live_cover") is not None else 10**9),
        int(agg.get("min_live_blockers") if agg.get("min_live_blockers") is not None else 10**9),
        -int(agg.get("root_slack") or 0),
        int(agg.get("root_g") or 0),
    )


def choose_stage_b_pairs(ranked: Sequence[dict], n_roots: int = STAGE_B_ROOTS, n_targets: int = STAGE_B_TARGETS) -> List[dict]:
    promote = list(ranked)[: int(n_roots)]
    pairs = []
    for agg in promote:
        probes = sorted(agg.get("probes") or [], key=_probe_family_key)
        for pr in probes[: int(n_targets)]:
            pairs.append({"root": agg, "suit": pr.get("suit"), "probe": pr})
    return pairs


def _probe_family_key(pr: dict) -> tuple:
    if int(pr.get("viable_count") or 0) > 0:
        slack = pr.get("max_viable_slack")
        return (
            0,
            int(pr.get("best_viable_f") or 10**9),
            -int(slack if slack is not None else -10**9),
            int(pr.get("min_h_viable") or 10**9),
        )
    return (
        1,
        int(pr.get("min_f_raw") if pr.get("min_f_raw") is not None else 10**9),
        int(pr.get("min_cover") if pr.get("min_cover") is not None else 10**9),
        int(pr.get("min_blockers") if pr.get("min_blockers") is not None else 10**9),
    )


def build_next_foundation_portfolio(
    aggs: Sequence[dict],
    closed: dict,
    *,
    hard_max: int = PORTFOLIO_MAX,
) -> List[dict]:
    pool = []
    for agg in aggs:
        for rec in agg.get("viable_terminals") or []:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            item = dict(rec)
            item["ident"] = ident
            item["closed"] = bool(ident and is_known_closed(ident, int(rec["g"]), closed))
            if item["closed"]:
                item["closed_tag"] = "KNOWN_CLOSED_STATE"
            pool.append(item)
    open_pool = [r for r in pool if not r.get("closed") and is_proof_viable(int(r["g"]), int(r["assembly_h"]))]
    return select_f4_portfolio(open_pool, hard_max=int(hard_max))


def choose_f3_frontier_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F3_FRONTIER_CONTRACT_FAILURE", p.get("contract_reason") or "root/identity/proof/accounting/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "F3_FRONTIER_COST_IMPROVED", f"solved at g={best}"
    best_f = p.get("best_new_f")
    max_f = int(p.get("max_foundations") or 0)
    if best_f is not None and int(best_f) <= 184:
        return "F3_FRONTIER_FINDS_STRONG_SURPLUS", f"new next-foundation f={best_f}"
    if max_f >= 6:
        return "F3_FRONTIER_DEEP_ENDGAME", f"maxF={max_f}"
    if best_f is not None and int(best_f) == 185:
        return "F3_FRONTIER_FINDS_NEW_SURPLUS", f"new next-foundation f={best_f}"
    stop = p.get("stop_reason")
    if p.get("screening_time_limited") or (
        stop in ("time limit", "unique limit", "rss abort") and int(p.get("n_selected") or 0) > 0
    ):
        return "F3_FRONTIER_SEARCH_LIMITED", "promising new F3 branches remain resource-limited"
    return "F3_FRONTIER_NO_BETTER_THAN_G158", "no new F3 produced bridge economics better than g158 f=185"


def next_recommendation(verdict: str) -> str:
    if verdict == "F3_FRONTIER_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "F3_FRONTIER_FINDS_STRONG_SURPLUS":
        return "Make the strong-surplus F4/F5 the next focused hierarchical root."
    if verdict == "F3_FRONTIER_FINDS_NEW_SURPLUS":
        return "Preserve F3 bridge value in final-epoch selection; do not resume closed g141/g158 F4/F5 roots."
    if verdict == "F3_FRONTIER_DEEP_ENDGAME":
        return "Continue hierarchical decomposition from the new F6-capable root, excluding exact closed identities."
    if verdict == "F3_FRONTIER_NO_BETTER_THAN_G158":
        return "Stop further endgame decomposition on this g128 post-SD5 branch; produce a better post-SD5 F2/root."
    if verdict == "F3_FRONTIER_SEARCH_LIMITED":
        return (
            "Reallocate the 900s envelope to v0.80-length proof-aware probes of the "
            "already-harvested cheap/interior F3s (especially g142 f=174 and g160 f=183); "
            "do not resume closed F4/F5 roots and do not widen wall time."
        )
    return "Do not promote; diagnose the contract."
