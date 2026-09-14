"""Proof-aware stock-empty tactical bridge from a generic F3 root.

v0.80 used the cheapest F3 (g141). v0.81 parameterises the same planner
so economics derive from the supplied root. Canonical 172 is not read.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.f3_tactical_bridge import (
    BRIDGE_CEILING,
    F4_PORTFOLIO_MAX,
    V078_JSON,
    assembly_slack,
    inspect_f3_state,
    replay_from_f3,
    search_f4_portfolio,
    select_f4_portfolio,
)
from spider.foundation_cashout import (
    TACTICAL_LANES,
    is_target_cashout,
    search_foundation_cashout,
)
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW
from spider.metrics import replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.operational_viability import foundation_operational_viability
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import as_actions, dump_actions, face_down_count, is_deal, stock_rows, tableau_actions
from spider.structural_analysis import INF, _n, current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

STAGE_A_S = 120.0
STAGE_A_UNIQUE = 200_000
STAGE_B_S = 60.0
STAGE_B_N = 2
STAGE_B_UNIQUE = 200_000
TACTICAL_BUDGET_S = 600.0
TOTAL_S = SEARCH_TIME_S
F4_PER_TARGET = 8
# g141 defaults kept so v0.80 importers remain stable. Live economics
# always come from the supplied root, never these constants.
ROOT_G = 141
ROOT_H = 33
ROOT_F = 174
SURPLUS_SLACK_MIN = 1
COMPLETE_EXHAUSTION_NOTE = (
    "the proof-viable continuation subgraph from the admitted roots was exhausted."
)


class ExactHCache:
    """Exact stock-empty h cache. Identity-neutral; not part of TT."""

    def __init__(self) -> None:
        self.store: Dict[bytes, int] = {}
        self.calls = 0
        self.hits = 0
        self.misses = 0
        self.seconds = 0.0

    def __call__(self, state, g: int) -> int:
        self.calls += 1
        ident = pack_whole_game_identity(state)
        if ident in self.store:
            self.hits += 1
            return self.store[ident]
        t0 = time.perf_counter()
        h = int(stock_empty_assembly_h(state, g))
        self.seconds += time.perf_counter() - t0
        self.misses += 1
        self.store[ident] = h
        return h

    def stats(self) -> dict:
        return {
            "calls": self.calls,
            "hits": self.hits,
            "misses": self.misses,
            "seconds": self.seconds,
            "size": len(self.store),
        }


def is_proof_viable(g: int, h: int, ceiling: int = BRIDGE_CEILING) -> bool:
    return int(g) + int(h) <= int(ceiling)


def is_surplus(g: int, h: int, ceiling: int = BRIDGE_CEILING) -> bool:
    """Quality class: at least +1 proof slack remains. Not a new proof rule."""

    return int(g) + int(h) <= int(ceiling) - SURPLUS_SLACK_MIN


def cashout_class(g: int, h: int, ceiling: int = BRIDGE_CEILING) -> str:
    if is_surplus(g, h, ceiling):
        return "SURPLUS_TARGET_CASHOUT"
    if is_proof_viable(g, h, ceiling):
        return "VIABLE_TARGET_CASHOUT"
    return "RAW_TARGET_CASHOUT"


def assembly_payback(delta_g: int, delta_h: int):
    if int(delta_g) <= 0:
        return None
    return -float(delta_h) / float(delta_g)


def root_relative_economics(
    g: int,
    h: int,
    *,
    root_g: int,
    root_h: int,
    ceiling: int = BRIDGE_CEILING,
) -> dict:
    dg = int(g) - int(root_g)
    dh = int(h) - int(root_h)
    df = dg + dh
    f = int(g) + int(h)
    return {
        "delta_g": dg,
        "delta_h": dh,
        "delta_f": df,
        "remaining_slack": assembly_slack(int(ceiling), f),
        "assembly_payback": assembly_payback(dg, dh),
    }


def target_future_key(state, g: int, target_suit: str, h_fn) -> tuple:
    """Lexicographic future-affordability key. Lower is better. No fitted weights."""

    h = int(h_fn(state, g))
    v = foundation_operational_viability(state, target_suit)
    return (
        int(g) + h,
        h,
        _n(v.get("cover")),
        int(v.get("inaccessible_joins") or 0),
        int(v.get("k_min_blockers") or INF),
        int(v.get("a_min_blockers") or INF),
        _n(v.get("gap")),
        -int(v.get("legal_merge_edges") or 0),
        int(g),
    )


def inspect_stock_empty_root(digest: str, g: int) -> dict:
    """Generic stock-empty inspect. Does not hard-code g141 empty-column count."""

    info = inspect_f3_state(digest, g=int(g))
    info["ok"] = bool(info.get("stock_rows") == 0 and not info.get("can_deal"))
    return info


def load_g158_record() -> dict:
    """First F3 recorded by the v0.78 focused run (cheap_F telemetry, not frontier_list)."""

    data = json.loads(V078_JSON.read_text(encoding="utf-8"))
    first = None
    for snap in data.get("snapshots") or []:
        cheap = snap.get("cheap_F") or {}
        rec = cheap.get("3") or cheap.get(3)
        if not rec or int(rec.get("g") or 0) != 158:
            continue
        out = dict(rec)
        out["snapshot_label"] = snap.get("label")
        out["snapshot_elapsed_s"] = snap.get("elapsed_s")
        if first is None:
            first = out
    if first is None:
        raise KeyError("v0.78 first F3 g=158 record missing from cheap_F telemetry")
    return first


def verify_g158_root() -> dict:
    """Load v0.78 artefact, unpack, recompute. Digest is not a policy constant."""

    rec = load_g158_record()
    digest = rec.get("ordered_digest")
    if not digest:
        return {"ok": False, "reason": "missing_digest", "record": rec}
    info = inspect_stock_empty_root(digest, g=158)
    expected = {
        "g": 158,
        "foundations": 3,
        "assembly_h": 22,
        "assembly_f": 180,
        "face_down": 2,
        "empty_n": 3,
        "legal_tableau": 80,
        "slack": 6,
        "stock_rows": 0,
        "can_deal": False,
    }
    mismatches = {
        k: {"expected": v, "got": info.get(k)}
        for k, v in expected.items()
        if info.get(k) != v
    }
    rec_mismatch = []
    if int(rec.get("h") or rec.get("assembly_h") or 0) != 22:
        rec_mismatch.append("assembly_h")
    if int(rec.get("f") or rec.get("assembly_f") or 0) != 180:
        rec_mismatch.append("assembly_f")
    if int(rec.get("legal") or rec.get("legal_tableau") or 0) != 80:
        rec_mismatch.append("legal")
    if int(rec.get("empty_n") or 0) != 3:
        rec_mismatch.append("empty_n")
    info["boundaries_recorded"] = rec.get("boundaries") or rec.get("boundaries_total")
    info["discovery_elapsed_s"] = rec.get("elapsed_s")
    info["ok"] = bool(info.get("ok") and not mismatches)
    info["mismatches"] = mismatches
    info["record_mismatch"] = rec_mismatch
    info["reason"] = None if info["ok"] else "G158_F3_BRIDGE_CONTRACT_FAILURE"
    info["record"] = {k: rec.get(k) for k in rec if k != "full_actions"}
    info["provenance"] = (
        "opening → autonomous g123 → v0.71 machine tactical → g128 F2 → "
        "SD5 → g129 stock-empty → v0.78 search → g158 F3"
    )
    return info


def continuation_is_exhausted(stop_reason: Optional[str]) -> bool:
    return stop_reason == "complete"


def continuation_is_resource_limited(stop_reason: Optional[str]) -> bool:
    return stop_reason in ("time limit", "unique limit", "rss abort")


def recommend_continue_from_roots(stop_reason: Optional[str], solved: bool = False) -> bool:
    """`complete` means the proof-viable subgraph is exhausted. Do not resume it."""

    if solved:
        return False
    if continuation_is_exhausted(stop_reason):
        return False
    return continuation_is_resource_limited(stop_reason)


def interpret_continuation_stop(stop_reason: Optional[str], *, solved: bool = False) -> dict:
    exhausted = continuation_is_exhausted(stop_reason)
    return {
        "stop_reason": stop_reason,
        "exhausted": exhausted,
        "resource_limited": continuation_is_resource_limited(stop_reason),
        "recommend_continue_from_these_roots": recommend_continue_from_roots(stop_reason, solved),
        "note": COMPLETE_EXHAUSTION_NOTE if exhausted and not solved else None,
    }


def _enrich_term(
    f3: dict,
    target: dict,
    term: dict,
    cache: ExactHCache,
    *,
    root_g: int,
    root_h: int,
    ceiling: int,
) -> Optional[dict]:
    suit = target["suit"]
    before = int(target["target_foundations_before"])
    actions = as_actions(term.get("actions") or [])
    if any(is_deal(a) for a in actions):
        return None
    replayed = replay_from_f3(f3["ordered_digest"], int(f3["g"]), actions)
    if not replayed.get("ok"):
        return None
    st = replayed["state"]
    if not is_target_cashout(st, suit, before) or stock_rows(st) != 0:
        return None
    g = int(replayed["g"])
    h = int(cache(st, g))
    f = g + h
    s = current_tableau_summary(st)
    viable = is_proof_viable(g, h, ceiling)
    surplus = is_surplus(g, h, ceiling)
    rec = {
        "g": g,
        "foundations": len(st.foundations),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": face_down_count(st),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(st)),
        "boundaries": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": f,
        "slack": assembly_slack(int(ceiling), f),
        "ordered_digest": replayed["ordered_digest"],
        "whole_game_identity": replayed["whole_game_identity"],
        "ident": replayed["whole_game_identity"],
        "full_actions": dump_actions(actions),
        "n_actions": len(actions),
        "tactical_target": suit,
        "operational_rank": target.get("operational_rank"),
        "stock_rows": 0,
        "class": cashout_class(g, h, ceiling),
        "viable": viable,
        "surplus": surplus,
        "lineage": [f"v078_f3_g{int(root_g)}", f"proof_aware_{suit}"],
        "portfolio_cat": "viable_f4" if viable else "raw_dead_f4",
    }
    rec.update(root_relative_economics(g, h, root_g=root_g, root_h=root_h, ceiling=ceiling))
    return rec


def _probe_one(
    f3: dict,
    target: dict,
    *,
    time_s: float,
    unique: int,
    stage: str,
    root_g: int,
    root_h: int,
    ceiling: int,
) -> dict:
    cache = ExactHCache()
    suit = target["suit"]

    def future_key(st, g):
        return target_future_key(st, g, suit, cache)

    def viable_fn(st, g):
        return is_proof_viable(int(g), int(cache(st, g)), ceiling)

    t0 = time.perf_counter()
    result = search_foundation_cashout(
        ordered_digest=f3["ordered_digest"],
        root_g=int(f3["g"]),
        target_suit=suit,
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        cost_ceiling=int(ceiling),
        portfolio_limit=F4_PER_TARGET,
        skip_preview=True,
        lower_bound_fn=cache,
        future_cost_key_fn=future_key,
        terminal_viability_fn=viable_fn,
    )
    raw_terms = []
    viable_terms = []
    surplus_terms = []
    kernel = result.kernel
    for rec in list(result.terminals or []):
        if rec.get("node") is not None and kernel is not None and kernel.nodes:
            rec["actions"] = dump_actions(kernel.reconstruct(int(rec["node"])))
        enriched = _enrich_term(
            f3, target, rec, cache, root_g=root_g, root_h=root_h, ceiling=ceiling
        )
        if enriched is None:
            continue
        raw_terms.append(enriched)
        if enriched["viable"]:
            viable_terms.append(enriched)
        if enriched.get("surplus"):
            surplus_terms.append(enriched)
    raw_terms.sort(key=lambda r: (int(r["g"]), int(r["assembly_f"])))
    viable_terms.sort(key=lambda r: (int(r["assembly_f"]), int(r["g"])))
    surplus_terms.sort(key=lambda r: (int(r["assembly_f"]), int(r["g"])))
    first_raw = min(raw_terms, key=lambda r: (r["g"], r["assembly_f"])) if raw_terms else None
    best_raw_f = min(raw_terms, key=lambda r: (r["assembly_f"], r["g"])) if raw_terms else None
    first_viable = min(viable_terms, key=lambda r: (r["g"], r["assembly_f"])) if viable_terms else None
    best_viable = min(viable_terms, key=lambda r: (r["assembly_f"], r["g"])) if viable_terms else None
    max_slack = None
    max_viable_slack = None
    for rec in raw_terms:
        sl = rec.get("slack")
        if sl is None:
            continue
        max_slack = sl if max_slack is None else max(max_slack, sl)
    for rec in viable_terms:
        sl = rec.get("slack")
        if sl is None:
            continue
        max_viable_slack = sl if max_viable_slack is None else max(max_viable_slack, sl)
    prog = result.progress or {}
    peak = None
    if kernel is not None:
        peak = getattr(kernel, "peak_rss_mb", None)
    return {
        "suit": suit,
        "stage": stage,
        "operational_rank": target.get("operational_rank"),
        "already_founded": target.get("already_founded"),
        "target_foundations_before": target.get("target_foundations_before"),
        "cover": target.get("cover"),
        "blockers": target.get("blockers"),
        "inaccessible_joins": target.get("inaccessible_joins"),
        "k_access": target.get("k_access"),
        "a_access": target.get("a_access"),
        "gap": target.get("gap"),
        "merge_edges": target.get("merge_edges"),
        "buried_components": target.get("buried_components"),
        "exposed_components": target.get("exposed_components"),
        "elapsed_s": time.perf_counter() - t0,
        "unique": result.unique,
        "expanded": result.expanded,
        "generated": result.generated,
        "stop_reason": result.stop_reason,
        "lane_exp": dict(result.lane_exp or {}),
        "lane_names": list(result.lane_names or TACTICAL_LANES),
        "proof_prunes": result.lower_bound_prunes,
        "proof_calls": result.lower_bound_calls,
        "h_cache": cache.stats(),
        "peak_rss_mb": peak,
        "min_cover": prog.get("min_cover"),
        "min_blockers": prog.get("min_blockers"),
        "best_k_access": prog.get("best_k_access"),
        "best_a_access": prog.get("best_a_access"),
        "raw_count": len(raw_terms),
        "viable_count": len(viable_terms),
        "surplus_count": len(surplus_terms),
        "first_raw_g": None if first_raw is None else first_raw["g"],
        "first_raw_f": None if first_raw is None else first_raw["assembly_f"],
        "first_raw_s": result.first_s,
        "cheapest_raw_g": None if first_raw is None else first_raw["g"],
        "best_raw_f": None if best_raw_f is None else best_raw_f["assembly_f"],
        "first_viable_g": result.first_viable_g,
        "first_viable_s": result.first_viable_s,
        "cheapest_viable_g": None if first_viable is None else first_viable["g"],
        "best_viable_f": None if best_viable is None else best_viable["assembly_f"],
        "min_h_raw": None if not raw_terms else min(int(r["assembly_h"]) for r in raw_terms),
        "min_f_raw": None if not raw_terms else min(int(r["assembly_f"]) for r in raw_terms),
        "min_h_viable": None if not viable_terms else min(int(r["assembly_h"]) for r in viable_terms),
        "min_f_viable": None if not viable_terms else min(int(r["assembly_f"]) for r in viable_terms),
        "max_slack": max_slack,
        "max_viable_slack": max_viable_slack,
        "max_mobility_viable": None
        if not viable_terms
        else max(int(r["legal_tableau"]) for r in viable_terms),
        "best_surplus_f": None if not surplus_terms else min(int(r["assembly_f"]) for r in surplus_terms),
        "economics_cheapest_raw": None
        if first_raw is None
        else root_relative_economics(
            first_raw["g"], first_raw["assembly_h"], root_g=root_g, root_h=root_h, ceiling=ceiling
        ),
        "economics_cheapest_viable": None
        if first_viable is None
        else root_relative_economics(
            first_viable["g"],
            first_viable["assembly_h"],
            root_g=root_g,
            root_h=root_h,
            ceiling=ceiling,
        ),
        "raw_terminals": raw_terms[:8],
        "viable_terminals": viable_terms[:F4_PER_TARGET],
        "surplus_terminals": surplus_terms[:F4_PER_TARGET],
        "stage_a_budget_s": STAGE_A_S,
        "stage_a_unique": STAGE_A_UNIQUE,
    }


def probe_proof_aware_target(
    root_record: dict,
    target: dict,
    *,
    time_s: float,
    unique: int,
    stage: str,
    ceiling: int = BRIDGE_CEILING,
) -> dict:
    """Public screening wrapper. Economics derive from the supplied root."""

    inspect = inspect_stock_empty_root(root_record["ordered_digest"], g=int(root_record["g"]))
    return _probe_one(
        root_record,
        target,
        time_s=float(time_s),
        unique=int(unique),
        stage=stage,
        root_g=int(inspect["g"]),
        root_h=int(inspect["assembly_h"]),
        ceiling=int(ceiling),
    )


def _family_key(probe: dict) -> tuple:
    if int(probe.get("viable_count") or 0) > 0:
        slack = probe.get("max_viable_slack")
        if slack is None:
            slack = probe.get("max_slack")
        return (
            0,
            -int(slack if slack is not None else -10**9),
            int(probe.get("best_viable_f") or 10**9),
            int(probe.get("cheapest_viable_g") or 10**9),
            int(probe.get("min_h_viable") or 10**9),
            -int(probe.get("max_mobility_viable") or 0),
        )
    return (
        1,
        int(probe.get("min_f_raw") if probe.get("min_f_raw") is not None else 10**9),
        int(probe.get("min_h_raw") if probe.get("min_h_raw") is not None else 10**9),
        int(probe.get("min_cover") if probe.get("min_cover") is not None else 10**9),
        int(probe.get("min_blockers") if probe.get("min_blockers") is not None else 10**9),
        -int(probe.get("max_slack") if probe.get("max_slack") is not None else -10**9),
    )


def run_proof_aware_bridge(root_record, ceiling: int = BRIDGE_CEILING) -> dict:
    inspect = inspect_stock_empty_root(root_record["ordered_digest"], g=int(root_record["g"]))
    targets = list(inspect["remaining_targets"] or [])
    root_g = int(inspect["g"])
    root_h = int(inspect["assembly_h"])
    root_f = int(inspect["assembly_f"])
    t0 = time.perf_counter()
    stage_a = []
    for tgt in targets[:4]:
        stage_a.append(
            _probe_one(
                root_record,
                tgt,
                time_s=STAGE_A_S,
                unique=STAGE_A_UNIQUE,
                stage="A",
                root_g=root_g,
                root_h=root_h,
                ceiling=int(ceiling),
            )
        )
    used = time.perf_counter() - t0
    remain_b = max(0.0, TACTICAL_BUDGET_S - used)
    ordered = sorted(stage_a, key=_family_key)
    any_viable = any(int(p.get("viable_count") or 0) > 0 for p in stage_a)
    if any_viable:
        promote = [p for p in ordered if int(p.get("viable_count") or 0) > 0][:STAGE_B_N]
    else:
        promote = ordered[:STAGE_B_N]
    tgt_by_suit = {t["suit"]: t for t in targets}
    stage_b = []
    if remain_b >= 1.0 and promote:
        per = min(STAGE_B_S, remain_b / float(len(promote)))
        for pr in promote:
            tgt = tgt_by_suit.get(pr["suit"])
            if tgt is None:
                continue
            stage_b.append(
                _probe_one(
                    root_record,
                    tgt,
                    time_s=per,
                    unique=STAGE_B_UNIQUE,
                    stage="B",
                    root_g=root_g,
                    root_h=root_h,
                    ceiling=int(ceiling),
                )
            )
    all_viable = []
    all_raw = []
    all_surplus = []
    for pr in stage_a + stage_b:
        all_raw.extend(pr.get("raw_terminals") or [])
        all_viable.extend(pr.get("viable_terminals") or [])
        all_surplus.extend(pr.get("surplus_terminals") or [])
    portfolio = select_f4_portfolio(
        [r for r in all_viable if is_proof_viable(int(r["g"]), int(r["assembly_h"]), int(ceiling))],
        hard_max=F4_PORTFOLIO_MAX,
    )
    for rec in portfolio:
        if int(rec["assembly_f"]) > int(ceiling):
            raise AssertionError("proof-dead F4 leaked into production portfolio")
    elapsed = time.perf_counter() - t0
    best_slack = None if not portfolio else max(int(r["slack"]) for r in portfolio)
    return {
        "inspect": inspect,
        "root_g": root_g,
        "root_h": root_h,
        "root_f": root_f,
        "root_slack": assembly_slack(int(ceiling), root_f),
        "ceiling": int(ceiling),
        "stage_a": stage_a,
        "stage_b": stage_b,
        "promoted_suits": [p.get("suit") for p in promote],
        "any_viable": bool(portfolio),
        "n_viable": len(portfolio),
        "n_raw": len(all_raw),
        "n_surplus": len({r.get("ident") for r in all_surplus if r.get("ident")}),
        "f4_roots": portfolio,
        "elapsed_s": elapsed,
        "stage_a_s": sum(float(p.get("elapsed_s") or 0) for p in stage_a),
        "stage_b_s": sum(float(p.get("elapsed_s") or 0) for p in stage_b),
        "budget_s": TACTICAL_BUDGET_S,
        "cheapest_raw_g": None if not all_raw else min(int(r["g"]) for r in all_raw),
        "cheapest_viable_g": None if not portfolio else min(int(r["g"]) for r in portfolio),
        "best_viable_f": None if not portfolio else min(int(r["assembly_f"]) for r in portfolio),
        "lowest_h_viable": None if not portfolio else min(int(r["assembly_h"]) for r in portfolio),
        "best_slack": best_slack,
        "best_surplus_f": None if not all_surplus else min(int(r["assembly_f"]) for r in all_surplus),
        "h_cache_calls": sum(int((p.get("h_cache") or {}).get("calls") or 0) for p in stage_a + stage_b),
        "h_cache_hits": sum(int((p.get("h_cache") or {}).get("hits") or 0) for p in stage_a + stage_b),
        "h_cache_misses": sum(int((p.get("h_cache") or {}).get("misses") or 0) for p in stage_a + stage_b),
        "h_cache_seconds": sum(float((p.get("h_cache") or {}).get("seconds") or 0) for p in stage_a + stage_b),
        "proof_prunes": sum(int(p.get("proof_prunes") or 0) for p in stage_a + stage_b),
        "proof_calls": sum(int(p.get("proof_calls") or 0) for p in stage_a + stage_b),
        "tactical_unique": sum(int(p.get("unique") or 0) for p in stage_a + stage_b),
        "tactical_expanded": sum(int(p.get("expanded") or 0) for p in stage_a + stage_b),
        "tactical_generated": sum(int(p.get("generated") or 0) for p in stage_a + stage_b),
        "peak_rss_mb": max((p.get("peak_rss_mb") or 0) for p in (stage_a + stage_b) or [{"peak_rss_mb": 0}]),
        "surplus_terminals": all_surplus[:F4_PER_TARGET],
    }


def f3_as_continuation_root(inspect: dict) -> dict:
    return {
        "g": int(inspect["g"]),
        "ordered_digest": inspect["ordered_digest"],
        "ident": inspect["whole_game_identity"],
        "whole_game_identity": inspect["whole_game_identity"],
        "full_actions": [],
        "stock_rows": 0,
        "foundations": inspect["foundations"],
        "face_down": inspect["face_down"],
        "lineage": [f"v078_f3_g{int(inspect['g'])}"],
        "portfolio_cat": "f3_fallback",
        "assembly_h": inspect["assembly_h"],
        "assembly_f": inspect["assembly_f"],
    }


class GenericDigestHunter:
    """Provenance-only hunter for an exact ordered digest at expected g."""

    def __init__(self, digest: str, expected_g: int) -> None:
        self.digest = digest
        self.expected_g = int(expected_g)
        self.hit: Optional[dict] = None
        self.n_seen = 0

    def _consider(self, rec: dict) -> None:
        self.n_seen += 1
        if rec.get("ordered_digest") != self.digest or not rec.get("full_actions"):
            return
        if self.hit is None or int(rec["g"]) < int(self.hit["g"]):
            self.hit = {
                "g": int(rec["g"]),
                "ordered_digest": rec["ordered_digest"],
                "full_actions": rec["full_actions"],
                "ident": rec.get("ident") or rec.get("whole_game_identity"),
            }

    def extra_track(self, tops, rec, min_root_g, class_best) -> None:
        self._consider(rec)

    def abort_when(self, out, rec) -> bool:
        self._consider(rec)
        return self.hit is not None and int(self.hit["g"]) <= self.expected_g


def recover_digest_path(opening, post: dict, digest: str, expected_g: int, *, time_s: float = 180.0, unique: int = 200_000) -> dict:
    hunter = GenericDigestHunter(digest, expected_g)
    root = {
        "g": int(post["g"]),
        "ordered_digest": post["ordered_digest"],
        "ident": post["whole_game_identity"],
        "whole_game_identity": post["whole_game_identity"],
        "full_actions": post["full_actions"],
        "stock_rows": 0,
        "foundations": post["foundations"],
        "face_down": post["face_down"],
        "lineage": ["g128_tactical_v071"],
        "portfolio_cat": "g129_recover_root",
    }
    t0 = time.perf_counter()
    res = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": AUTONOMOUS_INCUMBENT_MW},
        cost_ceiling=BRIDGE_CEILING,
        incumbent_by_rows={},
        initial_roots=[root],
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        harvest_cats=OP_HARVEST_CATS,
        enrich_fn=enrich_assembly,
        lane_names=COMPLETION_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=None,
        continuation_table=None,
        extra_track=hunter.extra_track,
        abort_when=hunter.abort_when,
    )
    hit = hunter.hit
    ok = False
    replay_g = None
    if hit is not None:
        end = opening.clone()
        try:
            replay_g = replay_actions(end, as_actions(hit["full_actions"]))
        except Exception:
            replay_g = None
        ok = (
            replay_g == int(hit["g"])
            and pack_state(end).hex() == digest
            and int(hit["g"]) == int(expected_g)
        )
    return {
        "ok": ok,
        "reason": None if ok else ("digest_not_recovered" if hit is None else "digest_replay_mismatch"),
        "elapsed_s": time.perf_counter() - t0,
        "unique": res.unique,
        "expanded": res.expanded,
        "stop_reason": res.stop_reason,
        "hit": hit,
        "replay_g": replay_g,
        "expected_digest": digest,
        "expected_g": int(expected_g),
    }


def recover_g158(opening, *, time_s: float = 180.0, unique: int = 200_000) -> dict:
    root = reconstruct_g128_root(opening)
    if not root.get("ok"):
        return {"ok": False, "reason": "g128_root_failed"}
    rec = load_g158_record()
    return recover_digest_path(
        opening,
        root["post"],
        rec["ordered_digest"],
        158,
        time_s=time_s,
        unique=unique,
    )


def choose_proof_aware_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "PROOF_AWARE_BRIDGE_CONTRACT_FAILURE", p.get("contract_reason") or "root/rules/accounting/lower-bound/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    n_viable = int((p.get("bridge") or {}).get("n_viable") or 0)
    n_raw = int((p.get("bridge") or {}).get("n_raw") or 0)
    max_f = int(p.get("max_foundations") or 0)
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "PROOF_AWARE_BRIDGE_COST_IMPROVED", f"solved at g={best}"
    if n_viable > 0 and max_f >= 5:
        return "PROOF_AWARE_BRIDGE_DEEP_ENDGAME", f"viable F4 n={n_viable} maxF={max_f}"
    if n_viable > 0:
        return "PROOF_AWARE_BRIDGE_FINDS_VIABLE_F4", f"viable F4 n={n_viable}"
    if n_raw > 0:
        return "PROOF_AWARE_BRIDGE_ONLY_DEAD_F4", "target foundations found but all proof-dead under 186"
    probes = ((p.get("bridge") or {}).get("stage_a") or []) + ((p.get("bridge") or {}).get("stage_b") or [])
    if any(int(pr.get("proof_prunes") or 0) > 0 and int(pr.get("unique") or 0) >= 5000 for pr in probes):
        return "PROOF_AWARE_BRIDGE_SEARCH_LIMITED", "proof-viable progress at expiry but F4 unresolved"
    return "PROOF_AWARE_BRIDGE_NO_F4", "no target foundation reached"


def choose_g158_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "G158_BRIDGE_CONTRACT_FAILURE", p.get("contract_reason") or "root/proof/accounting/identity/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    br = p.get("bridge") or {}
    n_viable = int(br.get("n_viable") or 0)
    n_surplus = int(br.get("n_surplus") or 0)
    best_f = br.get("best_viable_f")
    max_f = int(p.get("max_foundations") or 0)
    stop = p.get("stop_reason")
    exhausted = continuation_is_exhausted(stop)
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "G158_BRIDGE_COST_IMPROVED", f"solved at g={best}"
    if n_viable > 0 and max_f >= 5:
        return "G158_BRIDGE_DEEP_ENDGAME", f"viable F4 n={n_viable} maxF={max_f}"
    if n_surplus > 0 or (best_f is not None and int(best_f) <= 185):
        return "G158_BRIDGE_FINDS_SURPLUS_F4", f"surplus F4 n={n_surplus} best_f={best_f}"
    if n_viable > 0 and exhausted and not p.get("solved") and (best_f is None or int(best_f) >= 186):
        return "G158_BRIDGE_F4_EXHAUSTED", COMPLETE_EXHAUSTION_NOTE
    if n_viable > 0:
        return "G158_BRIDGE_FINDS_VIABLE_F4", f"viable F4 n={n_viable} best_f={best_f} slack={br.get('best_slack')}"
    if continuation_is_resource_limited(stop) or any(
        int(pr.get("proof_prunes") or 0) > 0 and int(pr.get("unique") or 0) >= 5000
        for pr in (br.get("stage_a") or []) + (br.get("stage_b") or [])
    ):
        return "G158_BRIDGE_SEARCH_LIMITED", "proof-live progress remains at a resource limit"
    return "G158_BRIDGE_NO_VIABLE_F4", "no F4 under f<=186"
