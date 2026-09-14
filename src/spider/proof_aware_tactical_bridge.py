"""v0.80 proof-aware stock-empty tactical bridge from the g141 F3.

Extends v0.71 cash-out with optional assembly proof-pruning and a
TARGET_FUTURE lane. Default cash-out behaviour is unchanged.
Canonical 172 is not read.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.f3_tactical_bridge import (
    BRIDGE_CEILING,
    F4_PORTFOLIO_MAX,
    assembly_slack,
    inspect_f3_state,
    replay_from_f3,
    search_f4_portfolio,
    select_f4_portfolio,
    verify_g141_root,
)
from spider.foundation_cashout import (
    TACTICAL_LANES,
    is_target_cashout,
    search_foundation_cashout,
)
from spider.operational_viability import foundation_operational_viability
from spider.packed_state import pack_whole_game_identity
from spider.research_actions import as_actions, dump_actions, face_down_count, is_deal, stock_rows, tableau_actions
from spider.structural_analysis import INF, _n, current_tableau_summary
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

STAGE_A_S = 120.0
STAGE_A_UNIQUE = 200_000
STAGE_B_S = 60.0
STAGE_B_N = 2
STAGE_B_UNIQUE = 200_000
TACTICAL_BUDGET_S = 600.0
TOTAL_S = SEARCH_TIME_S
F4_PER_TARGET = 8
ROOT_G = 141
ROOT_H = 33
ROOT_F = 174


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


def assembly_payback(delta_g: int, delta_h: int):
    if int(delta_g) <= 0:
        return None
    return -float(delta_h) / float(delta_g)


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


def _economics(g: int, h: int) -> dict:
    dg = int(g) - ROOT_G
    dh = int(h) - ROOT_H
    df = dg + dh
    return {
        "delta_g": dg,
        "delta_h": dh,
        "delta_f": df,
        "remaining_slack": assembly_slack(BRIDGE_CEILING, int(g) + int(h)),
        "assembly_payback": assembly_payback(dg, dh),
    }


def _enrich_term(f3: dict, target: dict, term: dict, cache: ExactHCache) -> Optional[dict]:
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
        "slack": assembly_slack(BRIDGE_CEILING, f),
        "ordered_digest": replayed["ordered_digest"],
        "whole_game_identity": replayed["whole_game_identity"],
        "ident": replayed["whole_game_identity"],
        "full_actions": dump_actions(actions),
        "n_actions": len(actions),
        "tactical_target": suit,
        "operational_rank": target.get("operational_rank"),
        "stock_rows": 0,
        "class": "VIABLE_TARGET_CASHOUT" if is_proof_viable(g, h) else "RAW_TARGET_CASHOUT",
        "viable": is_proof_viable(g, h),
        "lineage": ["v078_f3_g141", f"proof_aware_{suit}"],
        "portfolio_cat": "viable_f4" if is_proof_viable(g, h) else "raw_dead_f4",
    }
    rec.update(_economics(g, h))
    return rec


def _probe_one(f3: dict, target: dict, *, time_s: float, unique: int, stage: str) -> dict:
    cache = ExactHCache()
    suit = target["suit"]

    def future_key(st, g):
        return target_future_key(st, g, suit, cache)

    def viable_fn(st, g):
        return is_proof_viable(int(g), int(cache(st, g)))

    t0 = time.perf_counter()
    result = search_foundation_cashout(
        ordered_digest=f3["ordered_digest"],
        root_g=int(f3["g"]),
        target_suit=suit,
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        cost_ceiling=BRIDGE_CEILING,
        portfolio_limit=F4_PER_TARGET,
        skip_preview=True,
        lower_bound_fn=cache,
        future_cost_key_fn=future_key,
        terminal_viability_fn=viable_fn,
    )
    raw_terms = []
    viable_terms = []
    # reconstruct actions for kernel terminals we keep
    kernel = result.kernel
    for rec in list(result.terminals or []):
        if rec.get("node") is not None and kernel is not None and kernel.nodes:
            rec["actions"] = dump_actions(kernel.reconstruct(int(rec["node"])))
        enriched = _enrich_term(f3, target, rec, cache)
        if enriched is None:
            continue
        raw_terms.append(enriched)
        if enriched["viable"]:
            viable_terms.append(enriched)
    raw_terms.sort(key=lambda r: (int(r["g"]), int(r["assembly_f"])))
    viable_terms.sort(key=lambda r: (int(r["assembly_f"]), int(r["g"])))
    first_raw = min(raw_terms, key=lambda r: (r["g"], r["assembly_f"])) if raw_terms else None
    best_raw_f = min(raw_terms, key=lambda r: (r["assembly_f"], r["g"])) if raw_terms else None
    first_viable = min(viable_terms, key=lambda r: (r["g"], r["assembly_f"])) if viable_terms else None
    best_viable = min(viable_terms, key=lambda r: (r["assembly_f"], r["g"])) if viable_terms else None
    max_slack = None
    for rec in raw_terms:
        sl = rec.get("slack")
        if sl is None:
            continue
        max_slack = sl if max_slack is None else max(max_slack, sl)
    prog = result.progress or {}
    return {
        "suit": suit,
        "stage": stage,
        "operational_rank": target.get("operational_rank"),
        "already_founded": target.get("already_founded"),
        "target_foundations_before": target.get("target_foundations_before"),
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
        "min_cover": prog.get("min_cover"),
        "min_blockers": prog.get("min_blockers"),
        "best_k_access": prog.get("best_k_access"),
        "best_a_access": prog.get("best_a_access"),
        "raw_count": len(raw_terms),
        "viable_count": len(viable_terms),
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
        "economics_cheapest_raw": None if first_raw is None else _economics(first_raw["g"], first_raw["assembly_h"]),
        "economics_cheapest_viable": None if first_viable is None else _economics(first_viable["g"], first_viable["assembly_h"]),
        "raw_terminals": raw_terms[:8],
        "viable_terminals": viable_terms[:F4_PER_TARGET],
    }


def _family_key(probe: dict) -> tuple:
    if int(probe.get("viable_count") or 0) > 0:
        return (
            0,
            int(probe.get("best_viable_f") or 10**9),
            int(probe.get("cheapest_viable_g") or 10**9),
            int(probe.get("min_h_viable") or 10**9),
            -int(probe.get("viable_count") or 0),
        )
    return (
        1,
        int(probe.get("min_cover") if probe.get("min_cover") is not None else 10**9),
        int(probe.get("min_blockers") if probe.get("min_blockers") is not None else 10**9),
        int(probe.get("min_h_raw") if probe.get("min_h_raw") is not None else 10**9),
        -int(probe.get("max_slack") if probe.get("max_slack") is not None else -10**9),
    )


def run_proof_aware_bridge(f3: dict) -> dict:
    inspect = inspect_f3_state(f3["ordered_digest"], g=int(f3["g"]))
    targets = list(inspect["remaining_targets"] or [])
    t0 = time.perf_counter()
    stage_a = []
    for tgt in targets[:4]:
        stage_a.append(
            _probe_one(f3, tgt, time_s=STAGE_A_S, unique=STAGE_A_UNIQUE, stage="A")
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
                _probe_one(f3, tgt, time_s=per, unique=STAGE_B_UNIQUE, stage="B")
            )
    all_viable = []
    all_raw = []
    for pr in stage_a + stage_b:
        all_raw.extend(pr.get("raw_terminals") or [])
        all_viable.extend(pr.get("viable_terminals") or [])
    portfolio = select_f4_portfolio(
        [r for r in all_viable if is_proof_viable(int(r["g"]), int(r["assembly_h"]))],
        hard_max=F4_PORTFOLIO_MAX,
    )
    for rec in portfolio:
        if int(rec["assembly_f"]) > BRIDGE_CEILING:
            raise AssertionError("proof-dead F4 leaked into production portfolio")
    elapsed = time.perf_counter() - t0
    return {
        "inspect": inspect,
        "stage_a": stage_a,
        "stage_b": stage_b,
        "promoted_suits": [p.get("suit") for p in promote],
        "any_viable": bool(portfolio),
        "n_viable": len(portfolio),
        "n_raw": len(all_raw),
        "f4_roots": portfolio,
        "elapsed_s": elapsed,
        "stage_a_s": sum(float(p.get("elapsed_s") or 0) for p in stage_a),
        "stage_b_s": sum(float(p.get("elapsed_s") or 0) for p in stage_b),
        "budget_s": TACTICAL_BUDGET_S,
        "cheapest_raw_g": None if not all_raw else min(int(r["g"]) for r in all_raw),
        "cheapest_viable_g": None if not portfolio else min(int(r["g"]) for r in portfolio),
        "best_viable_f": None if not portfolio else min(int(r["assembly_f"]) for r in portfolio),
        "h_cache_calls": sum(int((p.get("h_cache") or {}).get("calls") or 0) for p in stage_a + stage_b),
        "h_cache_hits": sum(int((p.get("h_cache") or {}).get("hits") or 0) for p in stage_a + stage_b),
        "proof_prunes": sum(int(p.get("proof_prunes") or 0) for p in stage_a + stage_b),
    }


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
