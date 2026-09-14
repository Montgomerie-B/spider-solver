"""v0.84 pre-SD5 F2 quality frontier and post-Deal rollout.

Harvests diverse next-foundation terminals from autonomous g123, applies
the exact final Deal, and evaluates proof-viable post-Deal roots with
frozen v0.76-style stock-empty rollout. Canonical 172 is not read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.f3_quality_frontier import is_known_closed, load_closed_root_table
from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack, search_f4_portfolio
from spider.final_deal_rollout import rollout_key, run_rollout
from spider.foundation_cashout import search_foundation_cashout
from spider.g128_focused_endgame import expected_g123_digest, load_v071_continuation, reconstruct_g123
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.proof_aware_tactical_bridge import ExactHCache, is_proof_viable
from spider.research_actions import (
    apply_action,
    as_actions,
    dump_actions,
    face_down_count,
    is_deal,
    stock_rows,
    tableau_actions,
)
from spider.state_convergence import V073_F2_DIGEST
from spider.structural_analysis import current_tableau_summary
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V083_JSON = ROOT / "docs" / "research" / "f3_bridge_calibration_v0_83.json"

HARVEST_S = 360.0
HARVEST_UNIQUE = 250_000
STAGE_A_S = 10.0
STAGE_A_N = 12
STAGE_B_S = 20.0
STAGE_B_N = 4
SELECT_N = 12
PORTFOLIO_MAX = 24
TOTAL_S = SEARCH_TIME_S
CONTINUATION_RESERVE_S = 300.0
G128_POST = {"pre_g": 128, "post_g": 129, "h": 43, "f": 172, "F3_g": 158, "F3_f": 180}
G187_POST = {"pre_g": 129, "post_g": 130, "h": 41, "f": 171}


def g123_ready_targets(state, g: int = 123) -> List[dict]:
    ranked = rank_ready_suits(state, g=int(g))
    counts: Dict[str, int] = {}
    for seq in state.foundations:
        if seq:
            suit = seq[0].suit
            counts[suit] = counts.get(suit, 0) + 1
    out = []
    for i, rec in enumerate(ranked.get("ranked") or []):
        out.append(
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
    return out


def verify_g123_root(opening=None) -> dict:
    rec = reconstruct_g123(opening)
    expected = {
        "g": 123,
        "foundations": 1,
        "face_down": 2,
        "stock_rows": 1,
    }
    mismatches = {
        k: {"expected": v, "got": rec.get(k)}
        for k, v in expected.items()
        if rec.get(k) != v
    }
    digest_ok = rec.get("ordered_digest") == expected_g123_digest()
    ok = bool(rec.get("ok")) and not mismatches and digest_ok and rec.get("identity_is_ordered")
    rec = dict(rec)
    rec["ok"] = bool(ok)
    rec["mismatches"] = mismatches
    rec["digest_ok"] = digest_ok
    rec["reason"] = None if ok else "g123_recompute_mismatch"
    return rec


def control_pre_f2_digests() -> dict:
    g128 = load_v071_continuation().get("terminal_digest")
    return {"g128": g128, "g187": V073_F2_DIGEST}


def load_f2_closed_table() -> dict:
    table = dict(load_closed_root_table())
    if not V083_JSON.exists():
        return table
    data = json.loads(V083_JSON.read_text(encoding="utf-8"))

    def walk(obj) -> None:
        if isinstance(obj, dict):
            digest = obj.get("ordered_digest")
            ident = obj.get("ident") or obj.get("whole_game_identity")
            if obj.get("closed") or obj.get("closed_tag") == "KNOWN_CLOSED_STATE":
                if digest:
                    st = unpack_state(bytes.fromhex(digest))
                    ident = pack_whole_game_identity(st).hex()
                    g = int(obj.get("g") or 0)
                    prev = table.get(ident)
                    if prev is None or g < int(prev["g"]):
                        table[ident] = {"ident": ident, "ordered_digest": digest, "g": g, "source": "v083"}
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return table


def harvest_f2_target(
    g123: dict,
    target: dict,
    *,
    time_s: float,
    unique: int = HARVEST_UNIQUE,
    ceiling: int = BRIDGE_CEILING,
) -> dict:
    result = search_foundation_cashout(
        ordered_digest=g123["ordered_digest"],
        root_g=int(g123["g"]),
        target_suit=target["suit"],
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=SEARCH_RSS_MB,
        cost_ceiling=int(ceiling),
        portfolio_limit=1,
        skip_preview=True,
    )
    kernel = result.kernel
    prefix = as_actions(g123.get("prefix_actions") or [])
    unique_terms: Dict[str, dict] = {}
    for rec in list(result.terminals or []):
        digest = rec.get("ordered_digest")
        if not digest:
            continue
        prev = unique_terms.get(digest)
        if prev is not None and int(prev["g"]) <= int(rec["g"]):
            continue
        actions = rec.get("actions")
        if not actions and rec.get("node") is not None and kernel is not None and kernel.nodes:
            actions = dump_actions(kernel.reconstruct(int(rec["node"])))
        if not actions:
            continue
        if any(is_deal(a) for a in as_actions(actions)):
            continue
        st = unpack_state(bytes.fromhex(digest))
        s = current_tableau_summary(st)
        n_f = len(st.foundations)
        term = {
            "g": int(rec["g"]),
            "foundations": n_f,
            "foundation_suits": list(s["foundation_suits"]),
            "face_down": face_down_count(st),
            "empty_n": int(s["empty_n"]),
            "legal_tableau": len(tableau_actions(st)),
            "boundaries": int(s.get("visible_runs") or 0),
            "visible_components": int(s.get("visible_runs") or 0),
            "ordered_digest": digest,
            "ident": pack_whole_game_identity(st).hex(),
            "stock_rows": stock_rows(st),
            "can_deal": bool(st.can_deal()),
            "tactical_target": target["suit"],
            "operational_rank": target.get("operational_rank"),
            "delta_g": int(rec["g"]) - int(g123["g"]),
            "class": "F2_TERMINAL" if n_f == 2 else "PREDEAL_DEEPER",
            "tactical_actions": dump_actions(as_actions(actions)),
            "full_actions": dump_actions(prefix + as_actions(actions)),
        }
        unique_terms[digest] = term
    terms = sorted(unique_terms.values(), key=lambda r: (int(r["g"]), r["ordered_digest"]))
    return {
        "suit": target["suit"],
        "operational_rank": target.get("operational_rank"),
        "elapsed_s": result.elapsed_s,
        "unique": result.unique,
        "expanded": result.expanded,
        "generated": result.generated,
        "stop_reason": result.stop_reason,
        "lane_exp": dict(result.lane_exp or {}),
        "n_raw": len(result.terminals or []),
        "n_unique": len(terms),
        "n_f2": sum(1 for r in terms if r["class"] == "F2_TERMINAL"),
        "n_deeper": sum(1 for r in terms if r["class"] == "PREDEAL_DEEPER"),
        "cheapest_g": None if not terms else terms[0]["g"],
        "terminals": terms,
        "lane_names": ("cost", "target_assembly", "target_access"),
    }


def mark_control_f2s(terms: Sequence[dict], controls: Optional[dict] = None) -> List[dict]:
    controls = controls or control_pre_f2_digests()
    out = []
    for rec in terms:
        rec = dict(rec)
        digest = rec.get("ordered_digest")
        if digest == controls.get("g128"):
            rec["control_tag"] = "g128_tactical"
        elif digest == controls.get("g187"):
            rec["control_tag"] = "g187_f2"
        else:
            rec["control_tag"] = None
        out.append(rec)
    return out


def apply_exact_final_deal(pre: dict, *, cache: Optional[ExactHCache] = None) -> dict:
    digest = pre.get("ordered_digest")
    if not digest:
        return {"ok": False, "reason": "missing_digest"}
    state = unpack_state(bytes.fromhex(digest))
    if stock_rows(state) != 1 or not state.can_deal():
        return {"ok": False, "reason": "cannot_deal", "pre_g": pre.get("g")}
    deal_c = apply_action(state, ("deal",))
    g = int(pre["g"]) + int(deal_c)
    h_fn = cache if cache is not None else stock_empty_assembly_h
    h = int(h_fn(state, g))
    f = g + h
    s = current_tableau_summary(state)
    viable = is_proof_viable(g, h, BRIDGE_CEILING)
    return {
        "ok": stock_rows(state) == 0,
        "pre_g": int(pre["g"]),
        "pre_digest": digest,
        "deal_cost": int(deal_c),
        "post_g": g,
        "post_digest": pack_state(state).hex(),
        "ident": pack_whole_game_identity(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "stock_rows": 0,
        "foundations": len(state.foundations),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal": len(tableau_actions(state)),
        "legal_tableau": len(tableau_actions(state)),
        "boundaries": int(s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": f,
        "slack": assembly_slack(BRIDGE_CEILING, f),
        "viable": viable,
        "post_class": "PROOF_VIABLE_POST_DEAL" if viable else "PROOF_DEAD_POST_DEAL",
        "full_actions": dump_actions(as_actions(pre.get("full_actions") or []) + [("deal",)]),
        "tactical_target": pre.get("tactical_target"),
        "operational_rank": pre.get("operational_rank"),
        "control_tag": pre.get("control_tag"),
        "pre_class": pre.get("class"),
        "pre_foundations": pre.get("foundations"),
        "delta_g": pre.get("delta_g"),
    }


def post_deal_pareto(records: Sequence[dict]) -> List[dict]:
    pool = [r for r in records if r.get("viable") and r.get("ok")]
    out = []
    for rec in pool:
        if any(_post_strictly_better(other, rec) for other in pool if other is not rec):
            continue
        out.append(rec)
    return sorted(out, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r["post_digest"]))


def _post_not_worse(a: dict, b: dict) -> bool:
    return (
        int(a["post_g"]) <= int(b["post_g"])
        and int(a["assembly_h"]) <= int(b["assembly_h"])
        and int(a["assembly_f"]) <= int(b["assembly_f"])
        and int(a["slack"]) >= int(b["slack"])
        and int(a["foundations"]) >= int(b["foundations"])
        and int(a["face_down"]) <= int(b["face_down"])
        and int(a["empty_n"]) >= int(b["empty_n"])
        and int(a["legal"]) >= int(b["legal"])
        and int(a["boundaries"]) <= int(b["boundaries"])
    )


def _post_strictly_better(a: dict, b: dict) -> bool:
    if not _post_not_worse(a, b):
        return False
    return (
        int(a["post_g"]) < int(b["post_g"])
        or int(a["assembly_h"]) < int(b["assembly_h"])
        or int(a["assembly_f"]) < int(b["assembly_f"])
        or int(a["slack"]) > int(b["slack"])
        or int(a["foundations"]) > int(b["foundations"])
        or int(a["face_down"]) < int(b["face_down"])
        or int(a["empty_n"]) > int(b["empty_n"])
        or int(a["legal"]) > int(b["legal"])
        or int(a["boundaries"]) < int(b["boundaries"])
    )


def select_rollout_roots(posts: Sequence[dict], *, k: int = SELECT_N) -> List[dict]:
    pool = [r for r in posts if r.get("viable") and r.get("ok")]
    if not pool:
        return []
    pareto = post_deal_pareto(pool)
    picks: List[dict] = []
    seen: Set[str] = set()

    def take(rec: Optional[dict], role: str) -> None:
        if rec is None:
            return
        ident = rec.get("ident") or rec.get("post_digest")
        if not ident or ident in seen:
            return
        seen.add(ident)
        item = dict(rec)
        item["selection_role"] = role
        picks.append(item)

    take(min(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r["post_digest"])), "lowest_f")
    take(min(pool, key=lambda r: (int(r["assembly_h"]), int(r["post_g"]), r["post_digest"])), "lowest_h")
    take(max(pool, key=lambda r: (int(r["slack"]), -int(r["post_g"]), r["post_digest"])), "greatest_slack")
    take(max(pool, key=lambda r: (int(r["foundations"]), -int(r["assembly_f"]), r["post_digest"])), "highest_F")
    take(max(pool, key=lambda r: (int(r["legal"]), -int(r["post_g"]), r["post_digest"])), "highest_mobility")
    take(max(pool, key=lambda r: (int(r["empty_n"]), -int(r["post_g"]), r["post_digest"])), "most_empties")
    take(min(pool, key=lambda r: (int(r["boundaries"]), int(r["post_g"]), r["post_digest"])), "lowest_boundaries")
    take(min(pool, key=lambda r: (int(r["post_g"]), int(r["assembly_f"]), r["post_digest"])), "cheapest_g")
    remaining = [r for r in pareto if (r.get("ident") or r.get("post_digest")) not in seen]
    if remaining:
        fs = sorted(int(r["assembly_f"]) for r in remaining)
        hs = sorted(int(r["assembly_h"]) for r in remaining)
        mf, mh = fs[len(fs) // 2], hs[len(hs) // 2]
        take(
            min(
                remaining,
                key=lambda r: (
                    abs(int(r["assembly_f"]) - mf) + abs(int(r["assembly_h"]) - mh),
                    int(r["post_g"]),
                    r["post_digest"],
                ),
            ),
            "pareto_balanced",
        )
    suits = {tuple(r.get("foundation_suits") or []) for r in picks}
    for rec in sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r["post_digest"])):
        if len(picks) >= int(k):
            break
        key = tuple(rec.get("foundation_suits") or [])
        if key not in suits:
            take(rec, "suit_diversity")
            suits.add(key)
    targets = {r.get("tactical_target") for r in picks}
    for rec in sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r["post_digest"])):
        if len(picks) >= int(k):
            break
        if rec.get("tactical_target") not in targets:
            take(rec, "target_diversity")
            targets.add(rec.get("tactical_target"))
    for rec in sorted(pareto + pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r["post_digest"])):
        if len(picks) >= int(k):
            break
        take(rec, "fill")
    return picks[: int(k)]


def as_rollout_post(post: dict) -> dict:
    rec = dict(post)
    rec["pre_g"] = post["pre_g"]
    rec["pre_digest"] = post["pre_digest"]
    rec["post_g"] = post["post_g"]
    rec["post_digest"] = post["post_digest"]
    rec["tag"] = post.get("selection_role") or post.get("control_tag") or post.get("tactical_target")
    rec["role"] = rec["tag"]
    rec["legal"] = post.get("legal") or post.get("legal_tableau")
    rec["ident"] = post.get("ident") or post.get("whole_game_identity")
    return rec


def select_continuation_portfolio(descendants: Sequence[dict], closed: dict, *, hard_max: int = PORTFOLIO_MAX) -> List[dict]:
    pool = []
    for rec in descendants:
        ident = rec.get("ident") or rec.get("whole_game_identity")
        if not ident or not rec.get("ordered_digest") or not rec.get("full_actions"):
            continue
        g = int(rec["g"])
        h = rec.get("assembly_h")
        if h is None:
            continue
        if not is_proof_viable(g, int(h), BRIDGE_CEILING):
            continue
        if is_known_closed(ident, g, closed):
            rec = dict(rec)
            rec["closed"] = True
            rec["closed_tag"] = "KNOWN_CLOSED_STATE"
            continue
        if int(rec.get("foundations") or 0) < 2:
            continue
        pool.append(dict(rec))
    pool.sort(
        key=lambda r: (
            -int(r.get("foundations") or 0),
            int(r.get("assembly_f") if r.get("assembly_f") is not None else 10**9),
            -int(r.get("slack") or 0),
            int(r.get("assembly_h") if r.get("assembly_h") is not None else 10**9),
            -int(r.get("legal_tableau") or r.get("legal") or 0),
            int(r.get("g") or 0),
            r.get("ordered_digest") or "",
        )
    )
    out = []
    seen: Set[str] = set()
    for rec in pool:
        ident = rec.get("ident")
        if ident in seen:
            continue
        seen.add(ident)
        out.append(rec)
        if len(out) >= int(hard_max):
            break
    return out


def beats_g128_control(sig: dict) -> bool:
    max_f = int(sig.get("max_F") or 0)
    cheap = (sig.get("cheap_F") or {}).get(str(max_f)) or (sig.get("cheap_F") or {}).get(max_f) or {}
    f_at = cheap.get("f")
    t_df = sig.get("time_first_increase")
    if max_f >= 4:
        return True
    if max_f >= 3 and f_at is not None and int(f_at) < 180:
        return True
    if max_f >= 3 and t_df is not None and float(t_df) < 8.0:
        return True
    if sig.get("solved") and sig.get("terminal_g") is not None and int(sig["terminal_g"]) < 187:
        return True
    return False


def choose_f2_frontier_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F2_FRONTIER_CONTRACT_FAILURE", p.get("contract_reason") or "state/rules/accounting/identity/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "F2_FRONTIER_COST_IMPROVED", f"solved at g={best}"
    max_f = int(p.get("max_foundations") or 0)
    if max_f >= 6:
        return "F2_FRONTIER_DEEP_ENDGAME", f"maxF={max_f}"
    if p.get("superior_root"):
        return "F2_FRONTIER_FINDS_SUPERIOR_ROOT", p.get("superior_reason") or "new post-SD5 root beats g128/g187 controls"
    n_new = int(p.get("n_new_f2") or 0)
    if n_new <= 2 and int(p.get("n_unique_pre") or 0) <= 4:
        return "F2_FRONTIER_ONLY_EXISTING_CLASSES", "harvest reproduced g128/g187-class F2s"
    if p.get("search_limited"):
        return "F2_FRONTIER_SEARCH_LIMITED", "promising F2/root remains resource-limited"
    if n_new > 0:
        return "F2_FRONTIER_NEW_F2_NO_FUTURE_GAIN", "new F2 states exist but rollout shows no meaningful downstream improvement"
    return "F2_FRONTIER_ONLY_EXISTING_CLASSES", "no new useful F2 topology"


def next_recommendation(verdict: str) -> str:
    if verdict == "F2_FRONTIER_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "F2_FRONTIER_FINDS_SUPERIOR_ROOT":
        return "Make the new post-SD5 F2/root the next focused endgame control; do not return to the g128 F3 family."
    if verdict == "F2_FRONTIER_DEEP_ENDGAME":
        return "Continue hierarchical search from the live F6+ descendant, excluding exact closed identities."
    if verdict == "F2_FRONTIER_NEW_F2_NO_FUTURE_GAIN":
        return "Allow pre-Deal preparation after F2 before SD5 rather than searching more immediate-Deal F2 topologies."
    if verdict == "F2_FRONTIER_ONLY_EXISTING_CLASSES":
        return "Allow pre-Deal preparation after F2 before SD5 rather than searching more immediate-Deal F2 topologies."
    if verdict == "F2_FRONTIER_SEARCH_LIMITED":
        return "Keep F2 harvest+rollout; do not widen wall time and do not return to the g128 F3 family."
    return "Do not promote; diagnose the contract."
