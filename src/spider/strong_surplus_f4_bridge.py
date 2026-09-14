"""v0.87 hierarchical F4→F5 proof-aware bridge from v0.86 strong-surplus F4s.

Canonical 172 is not read. Search semantics are the frozen v0.80–v0.86 planner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from spider.f2_quality_frontier import load_f2_closed_table
from spider.f3_quality_frontier import enrich_stock_empty_state, is_known_closed
from spider.f3_tactical_bridge import assembly_slack, select_f4_portfolio
from spider.packed_state import unpack_state
from spider.proof_aware_tactical_bridge import is_proof_viable
from spider.structural_analysis import current_tableau_summary, interference_debt
from spider.whole_game_epoch_scheduler import SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V086_JSON = ROOT / "docs" / "research" / "new_family_f3_bridge_v0_86.json"
F3_G = 148
F3_F = 177
STAGE_A_S = 30.0
STAGE_A_UNIQUE = 100_000
STAGE_B_S = 30.0
STAGE_B_N = 4
MAX_F4_ROOTS = 3
PORTFOLIO_MAX = 16
TOTAL_S = SEARCH_TIME_S
CONTINUATION_RESERVE_S = 400.0
F3_CONTROL = {"g": 148, "h": 29, "f": 177, "slack": 9, "f4_f": 181, "bridge_loss": 4}


def structural_telemetry(state) -> dict:
    """Unambiguous tableau structure. Do not call this 'boundaries'."""

    s = current_tableau_summary(state)
    d = interference_debt(state)
    return {
        "visible_runs": int(s["visible_runs"]),
        "visible_components": int(d["visible_components"]),
        "mixed_suit_boundaries": int(d["boundaries_total"]),
        "off_suit_boundaries": int(d["off_suit_boundaries"]),
        "rank_break_boundaries": int(d["rank_break_boundaries"]),
    }


def document_boundaries_split() -> dict:
    """v0.85 'boundaries' was mixed_suit_boundaries; v0.86 'boundaries' was visible_runs."""

    return {
        "v085_boundaries_field": "mixed_suit_boundaries (interference_debt.boundaries_total)",
        "v086_boundaries_field": "visible_runs (current_tableau_summary.visible_runs)",
        "g141_v085_recorded": 28,
        "g141_visible_runs": 36,
        "g148_v085_recorded": 24,
        "g148_visible_runs": 32,
        "same_label_must_not_mix": True,
    }


def _collect_f4s(data: dict) -> List[dict]:
    out = []

    def walk(obj) -> None:
        if isinstance(obj, dict):
            if (
                int(obj.get("foundations") or 0) == 4
                and obj.get("assembly_f") is not None
                and int(obj["assembly_f"]) <= 184
                and obj.get("ordered_digest")
                and int(obj.get("root_g") or F3_G) == F3_G
            ):
                out.append(dict(obj))
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data.get("new_g148") or {})
    walk(data.get("portfolio") or [])
    return out


def load_strong_surplus_f4s() -> List[dict]:
    """Load unique strong-surplus F4s from the v0.86 artefact. No baked digest."""

    data = json.loads(V086_JSON.read_text(encoding="utf-8"))
    best: Dict[str, dict] = {}
    for rec in _collect_f4s(data):
        digest = rec["ordered_digest"]
        prev = best.get(digest)
        if prev is None or int(rec["g"]) < int(prev["g"]):
            rec["source_f3_g"] = F3_G
            rec["source_f3_f"] = F3_F
            best[digest] = rec
    return sorted(best.values(), key=lambda r: (int(r["assembly_f"]), int(r["g"]), r["ordered_digest"]))


def verify_f4_root(rec: dict) -> dict:
    digest = rec.get("ordered_digest")
    if not digest:
        return {"ok": False, "reason": "missing_digest"}
    info = enrich_stock_empty_state(digest, int(rec["g"]))
    struct = structural_telemetry(unpack_state(bytes.fromhex(digest)))
    info.update(struct)
    expected = {
        "g": int(rec["g"]),
        "foundations": 4,
        "assembly_h": int(rec["assembly_h"]),
        "assembly_f": int(rec["assembly_f"]),
        "slack": int(rec.get("slack") if rec.get("slack") is not None else 186 - int(rec["assembly_f"])),
        "stock_rows": 0,
        "can_deal": False,
    }
    mismatches = {
        k: {"expected": v, "got": info.get(k)}
        for k, v in expected.items()
        if info.get(k) != v
    }
    info["ok"] = bool(info.get("viable") and not mismatches and info.get("foundations") == 4)
    info["reason"] = None if info["ok"] else "recompute_mismatch"
    info["mismatches"] = mismatches
    info["source_f3_g"] = rec.get("source_f3_g") or F3_G
    info["tactical_target"] = rec.get("tactical_target")
    info["delta_g"] = rec.get("delta_g")
    info["delta_h"] = rec.get("delta_h")
    info["delta_f"] = rec.get("delta_f")
    info["assembly_payback"] = rec.get("assembly_payback")
    info["n_actions"] = rec.get("n_actions")
    info["full_actions"] = rec.get("full_actions")
    return info


def verify_all_f4_roots() -> dict:
    loaded = load_strong_surplus_f4s()
    verified = [verify_f4_root(r) for r in loaded]
    ok_roots = [r for r in verified if r.get("ok")]
    return {
        "ok": bool(ok_roots),
        "n_loaded": len(loaded),
        "n_ok": len(ok_roots),
        "roots": verified,
        "reason": None if ok_roots else "STRONG_F4_BRIDGE_CONTRACT_FAILURE",
    }


def select_active_f4s(verified: Sequence[dict], *, k: int = MAX_F4_ROOTS) -> List[dict]:
    pool = [r for r in verified if r.get("ok")]
    if len(pool) <= int(k):
        for i, rec in enumerate(pool):
            rec["selection_role"] = ("lowest_f", "lowest_h", "highest_mobility")[min(i, 2)] if len(pool) == 3 else "all"
        return list(pool)
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
    take(max(pool, key=lambda r: (int(r["legal_tableau"]), -int(r["g"]), r["ordered_digest"])), "highest_mobility")
    for rec in sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["g"]), r["ordered_digest"])):
        if len(picks) >= int(k):
            break
        take(rec, "fill")
    return picks[: int(k)]


def f5_quality(f: int) -> str:
    if int(f) <= 184:
        return "STRONG_SURPLUS_F5"
    if int(f) == 185:
        return "SURPLUS_F5"
    if int(f) == 186:
        return "VIABLE_F5"
    return "RAW_F5"


def choose_stage_b_pairs(aggs: Sequence[dict], n_pairs: int = STAGE_B_N) -> List[dict]:
    pairs = []
    for agg in aggs:
        for pr in agg.get("probes") or []:
            pairs.append({"root": agg, "suit": pr.get("suit"), "probe": pr})

    def key(pair: dict) -> tuple:
        pr = pair["probe"]
        if int(pr.get("viable_count") or 0) > 0:
            slack = pr.get("max_viable_slack")
            return (
                0,
                int(pr.get("best_viable_f") or 10**9),
                -int(slack if slack is not None else -10**9),
                int(pr.get("min_h_viable") or 10**9),
                int(pr.get("cheapest_viable_g") or 10**9),
                int(pair["root"].get("root_g") or 0),
            )
        return (
            1,
            int(pr.get("min_f_raw") if pr.get("min_f_raw") is not None else 10**9),
            int(pr.get("min_cover") if pr.get("min_cover") is not None else 10**9),
            int(pair["root"].get("root_g") or 0),
        )

    ordered = sorted(pairs, key=key)
    out = []
    seen_root_suit = set()
    for pair in ordered:
        tag = (pair["root"].get("ident"), pair.get("suit"))
        if tag in seen_root_suit:
            continue
        seen_root_suit.add(tag)
        out.append(pair)
        if len(out) >= int(n_pairs):
            break
    return out


def select_f5_portfolio(aggs: Sequence[dict], closed: dict, *, hard_max: int = PORTFOLIO_MAX) -> List[dict]:
    pool = []
    for agg in aggs:
        for rec in agg.get("viable_terminals") or []:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            item = dict(rec)
            item["ident"] = ident
            item["source_f4_g"] = agg.get("root_g")
            item["closed"] = bool(ident and is_known_closed(ident, int(rec["g"]), closed))
            if item["closed"] or not is_proof_viable(int(rec["g"]), int(rec["assembly_h"])):
                continue
            if int(rec.get("foundations") or 0) >= 6:
                item["class"] = "TACTICAL_DEEPER"
            pool.append(item)
    return select_f4_portfolio(pool, hard_max=int(hard_max))[: int(hard_max)]


def choose_strong_f4_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "STRONG_F4_BRIDGE_CONTRACT_FAILURE", p.get("contract_reason") or "root/proof/identity/ancestry/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "STRONG_F4_COST_IMPROVED", f"solved at g={best}"
    best_f = p.get("best_next_f")
    max_f = int(p.get("max_foundations") or 0)
    if best_f is not None and int(best_f) <= 184:
        return "STRONG_F4_FINDS_STRONG_SURPLUS_F5", f"F5/F6 f={best_f}"
    if max_f >= 6:
        return "STRONG_F4_DEEP_ENDGAME", f"maxF={max_f}"
    if best_f is not None and int(best_f) == 185:
        return "STRONG_F4_FINDS_SURPLUS_F5", "best F5 f=185"
    if best_f is not None and int(best_f) == 186:
        return "STRONG_F4_ZERO_SLACK_F5", "best F5 f=186"
    if p.get("screening_time_limited") or p.get("stop_reason") in ("time limit", "unique limit", "rss abort"):
        return "STRONG_F4_SEARCH_LIMITED", "promising F4/F5 lineage remains resource-limited"
    return "STRONG_F4_NO_VIABLE_F5", "no proof-viable next foundation from the tested F4s"


def next_recommendation(verdict: str) -> str:
    if verdict == "STRONG_F4_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "STRONG_F4_FINDS_STRONG_SURPLUS_F5":
        return "Repeat hierarchical decomposition from the strongest live F5."
    if verdict == "STRONG_F4_FINDS_SURPLUS_F5":
        return "Keep the surplus F5 as a live hierarchical root; do not widen wall time."
    if verdict == "STRONG_F4_DEEP_ENDGAME":
        return "Continue from the live F6+ descendant, excluding exact closed identities."
    if verdict == "STRONG_F4_ZERO_SLACK_F5":
        return (
            "Those exact f=186 F5 roots are exhausted. "
            "Return to rows=1 and test pre-Deal preparation after F2 before SD5."
        )
    if verdict == "STRONG_F4_SEARCH_LIMITED":
        return "Keep the live F4/F5 roots; do not widen wall time."
    if verdict == "STRONG_F4_NO_VIABLE_F5":
        return "Do not spend more time downstream; test pre-Deal preparation after F2 before SD5."
    return "Do not promote; diagnose the contract."
