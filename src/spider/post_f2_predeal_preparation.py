"""v0.88 post-F2 tableau preparation before the final Deal.

Two autonomous F2 roots. Tableau-only prep (no Deal in search), then exact
engine SD5 evaluation. Canonical 172 is not read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from spider.autonomous_cost import COST_LANES
from spider.f2_quality_frontier import apply_exact_final_deal, as_rollout_post, beats_g128_control
from spider.f3_quality_frontier import is_known_closed
from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack
from spider.final_deal_rollout import control_pre_sd5, rollout_key, run_rollout
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import operational_lane_keys
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.proof_aware_tactical_bridge import ExactHCache, is_proof_viable
from spider.research_actions import as_actions, dump_actions, is_deal, stock_rows, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.superior_f2_focused_endgame import reconstruct_superior_f2_root
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V084_JSON = ROOT / "docs" / "research" / "f2_quality_frontier_v0_84.json"
V087_JSON = ROOT / "docs" / "research" / "strong_surplus_f4_bridge_v0_87.json"
PREP_S = 150.0
PREP_UNIQUE = 200_000
MAX_DG = 15
ARCHIVE_EVAL = 80
SELECT_N = 12
STAGE_A_S = 10.0
STAGE_B_S = 20.0
STAGE_B_N = 4
PORTFOLIO_MAX = 24
TOTAL_S = SEARCH_TIME_S
CONTINUATION_RESERVE_S = 400.0
PREP_LANES = ("cost", "reveal", "construction", "readiness", "horizon", "economy")


def prep_cost_band(dg: int) -> str:
    d = int(dg)
    if d <= 0:
        return "0"
    if d <= 2:
        return "1-2"
    if d <= 5:
        return "3-5"
    if d <= 9:
        return "6-9"
    return "10-15"


def load_v084_lowest_f_pre() -> dict:
    data = json.loads(V084_JSON.read_text(encoding="utf-8"))
    hits = [r for r in data.get("selected") or [] if r.get("selection_role") == "lowest_f" and int(r.get("pre_g") or 0) == 128]
    if len(hits) != 1:
        raise KeyError(f"v0.84 lowest_f pre-F2 not unique: {len(hits)}")
    rec = dict(hits[0])
    rec["name"] = "NEW_G128_F2"
    return rec


def load_v084_g187_f2_pre() -> dict:
    data = json.loads(V084_JSON.read_text(encoding="utf-8"))
    hits = []
    seen = set()
    for rec in list(data.get("selected") or []) + list(data.get("pre_frontier") or []):
        if rec.get("control_tag") != "g187_f2":
            continue
        d = rec.get("pre_digest") or rec.get("ordered_digest")
        if not d or d in seen:
            continue
        seen.add(d)
        hits.append(dict(rec))
    if not hits:
        raise KeyError("v0.84 g187_f2 missing")
    rec = hits[0]
    rec["name"] = "INCUMBENT_G129_F2"
    rec["pre_digest"] = rec.get("pre_digest") or rec.get("ordered_digest")
    return rec


def _pre_from_actions(opening, acts) -> dict:
    last = max(i for i, a in enumerate(acts) if is_deal(a))
    prefix = acts[:last]
    end = opening.clone()
    g = replay_actions(end, list(prefix))
    s = current_tableau_summary(end)
    tel = structural_telemetry(end)
    ranked = rank_ready_suits(end, g=int(g))
    return {
        "ok": stock_rows(end) == 1 and end.can_deal() and len(end.foundations) == 2,
        "name": "NEW_G128_F2",
        "g": int(g),
        "ordered_digest": pack_state(end).hex(),
        "ident": pack_whole_game_identity(end).hex(),
        "stock_rows": stock_rows(end),
        "foundations": len(end.foundations),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(end)),
        "visible_runs": tel["visible_runs"],
        "visible_components": tel["visible_components"],
        "mixed_suit_boundaries": tel["mixed_suit_boundaries"],
        "can_deal": bool(end.can_deal()),
        "n_ready": int(ranked.get("n_ready") or 0),
        "full_actions": dump_actions(prefix),
        "n_deal": sum(1 for a in prefix if is_deal(a)),
    }


def reconstruct_root_a(opening=None) -> dict:
    opening = opening or opening_state()
    art = load_v084_lowest_f_pre()
    sup = reconstruct_superior_f2_root(opening)
    if not sup.get("ok"):
        return {"ok": False, "reason": "superior_f2_prefix_failed", "raw": sup}
    rec = _pre_from_actions(opening, as_actions(sup["full_actions"]))
    rec["name"] = "NEW_G128_F2"
    rec["ok"] = bool(
        rec.get("ok")
        and rec["g"] == 128
        and rec["foundations"] == 2
        and rec["face_down"] == 2
        and rec["stock_rows"] == 1
        and rec["ordered_digest"] == art["pre_digest"]
        and rec["n_deal"] == 4
    )
    rec["reason"] = None if rec["ok"] else "root_a_mismatch"
    rec["artefact_pre_digest"] = art["pre_digest"]
    return rec


def reconstruct_root_b(opening=None) -> dict:
    opening = opening or opening_state()
    art = load_v084_g187_f2_pre()
    ctrl = control_pre_sd5(opening)["ctrl_187"]
    if not ctrl.get("ok"):
        return {"ok": False, "reason": "ctrl_187_failed", "raw": ctrl}
    st = unpack_state(bytes.fromhex(ctrl["pre_digest"]))
    s = current_tableau_summary(st)
    tel = structural_telemetry(st)
    ranked = rank_ready_suits(st, g=int(ctrl["pre_g"]))
    rec = {
        "ok": (
            int(ctrl["pre_g"]) == 129
            and len(st.foundations) == 2
            and int(s["face_down"]) == 2
            and stock_rows(st) == 1
            and st.can_deal()
            and ctrl["pre_digest"] == art["pre_digest"]
        ),
        "name": "INCUMBENT_G129_F2",
        "g": int(ctrl["pre_g"]),
        "ordered_digest": ctrl["pre_digest"],
        "ident": pack_whole_game_identity(st).hex(),
        "stock_rows": 1,
        "foundations": 2,
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(st)),
        "visible_runs": tel["visible_runs"],
        "visible_components": tel["visible_components"],
        "mixed_suit_boundaries": tel["mixed_suit_boundaries"],
        "can_deal": True,
        "n_ready": int(ranked.get("n_ready") or 0),
        "full_actions": ctrl["full_actions"],
        "n_deal": sum(1 for a in as_actions(ctrl["full_actions"]) if is_deal(a)),
        "artefact_pre_digest": art["pre_digest"],
        "reason": None,
    }
    if not rec["ok"]:
        rec["reason"] = "root_b_mismatch"
    return rec


def immediate_deal_control(f2: dict, *, cache: Optional[ExactHCache] = None) -> dict:
    post = apply_exact_final_deal(
        {"g": f2["g"], "ordered_digest": f2["ordered_digest"], "full_actions": f2.get("full_actions") or []},
        cache=cache,
    )
    if post.get("ok"):
        st = unpack_state(bytes.fromhex(post["post_digest"]))
        tel = structural_telemetry(st)
        post.update(tel)
        post["source"] = f2.get("name")
        post["prep_delta_g"] = 0
        post["prep_band"] = "0"
        post["selection_role"] = "immediate_deal"
    return post


def harvest_preparation(
    opening,
    f2: dict,
    *,
    time_s: float,
    unique: int = PREP_UNIQUE,
    max_dg: int = MAX_DG,
    materialize_paths: bool = True,
) -> dict:
    root_g = int(f2["g"])
    archive: Dict[str, dict] = {}
    prefix = as_actions(f2.get("full_actions") or [])

    def on_progress(kr, state, g, node_i):
        if int(g) - root_g > int(max_dg):
            return
        if stock_rows(state) != 1 or not state.can_deal():
            return
        digest = pack_state(state).hex()
        prev = archive.get(digest)
        if prev is not None and int(prev["g"]) <= int(g):
            return
        s = current_tableau_summary(state)
        archive[digest] = {
            "g": int(g),
            "node": int(node_i),
            "foundations": len(state.foundations),
            "empty_n": int(s["empty_n"]),
            "legal_tableau": len(tableau_actions(state)),
            "visible_runs": int(s["visible_runs"]),
            "face_down": int(s["face_down"]),
        }

    root = {
        "g": root_g,
        "ordered_digest": f2["ordered_digest"],
        "symmetry_digest": f2.get("ident") or f2["ordered_digest"],
    }
    on_progress(None, unpack_state(bytes.fromhex(f2["ordered_digest"])), root_g, 0)
    kr = run_search(
        [root],
        limits=SearchLimits(
            max_unique=int(unique),
            time_limit_s=float(time_s),
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=int(root_g + max_dg),
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=PREP_LANES,
        lane_keys_fn=operational_lane_keys,
        is_terminal=lambda st: False,
        actions_fn=tableau_actions,
        on_progress=on_progress,
        lower_bound_fn=None,
    )
    cands = []
    for digest, rec in archive.items():
        dg = int(rec["g"]) - root_g
        item = {
            "source": f2.get("name"),
            "g": rec["g"],
            "prep_delta_g": dg,
            "prep_band": prep_cost_band(dg),
            "foundations": rec["foundations"],
            "empty_n": rec["empty_n"],
            "legal_tableau": rec["legal_tableau"],
            "visible_runs": rec["visible_runs"],
            "face_down": rec["face_down"],
            "ordered_digest": digest,
            "stock_rows": 1,
            "can_deal": True,
            "node": rec["node"],
        }
        if materialize_paths:
            path = []
            if rec["node"] and kr.nodes:
                path = kr.reconstruct(int(rec["node"]))
            if any(is_deal(a) for a in path):
                continue
            item["n_actions"] = len(path)
            item["full_actions"] = dump_actions(prefix + path)
        cands.append(item)
    cands.sort(key=lambda r: (int(r["g"]), r["ordered_digest"]))
    n_f3 = sum(1 for r in cands if int(r["foundations"]) >= 3)
    return {
        "source": f2.get("name"),
        "elapsed_s": kr.elapsed_s,
        "unique": kr.unique,
        "expanded": kr.expanded,
        "generated": kr.generated,
        "stop_reason": kr.stop_reason,
        "lane_exp": dict(kr.lane_exp or {}),
        "n_archive": len(cands),
        "n_predeal_f3": n_f3,
        "candidates": cands,
        "peak_rss_mb": kr.peak_rss_mb,
        "kernel": None if materialize_paths else kr,
        "prefix": dump_actions(prefix),
    }


def select_predeal_for_eval(cands: Sequence[dict], *, k: int = ARCHIVE_EVAL) -> List[dict]:
    pool = list(cands)
    if len(pool) <= int(k):
        return pool
    picks: List[dict] = []
    seen: Set[str] = set()

    def take(rec, role):
        if rec is None:
            return
        d = rec["ordered_digest"]
        if d in seen:
            return
        seen.add(d)
        item = dict(rec)
        item["eval_role"] = role
        picks.append(item)

    take(min(pool, key=lambda r: (int(r["g"]), r["ordered_digest"])), "cheapest")
    take(max(pool, key=lambda r: (int(r["foundations"]), -int(r["g"]))), "highest_F")
    take(max(pool, key=lambda r: (int(r["legal_tableau"]), -int(r["g"]))), "highest_mobility")
    take(max(pool, key=lambda r: (int(r["empty_n"]), -int(r["g"]))), "most_empties")
    take(min(pool, key=lambda r: (int(r["visible_runs"]), int(r["g"]))), "fewest_runs")
    for band in ("0", "1-2", "3-5", "6-9", "10-15"):
        banded = [r for r in pool if r["prep_band"] == band]
        if banded:
            take(min(banded, key=lambda r: (int(r["g"]), r["ordered_digest"])), f"band_{band}")
    for rec in sorted(pool, key=lambda r: (-int(r["foundations"]), int(r["g"]), r["ordered_digest"])):
        if len(picks) >= int(k):
            break
        take(rec, "fill")
    return picks[: int(k)]


def evaluate_prepared(pre: dict, control: dict, *, cache: Optional[ExactHCache] = None) -> dict:
    post = apply_exact_final_deal(pre, cache=cache)
    if not post.get("ok"):
        return post
    st = unpack_state(bytes.fromhex(post["post_digest"]))
    tel = structural_telemetry(st)
    post.update(tel)
    dg = int(pre.get("prep_delta_g") or 0)
    dh = int(post["assembly_h"]) - int(control["assembly_h"])
    df = int(post["assembly_f"]) - int(control["assembly_f"])
    post["source"] = pre.get("source")
    post["prep_delta_g"] = dg
    post["prep_band"] = pre.get("prep_band") or prep_cost_band(dg)
    post["prep_n_actions"] = pre.get("n_actions")
    post["pre_g"] = pre.get("g")
    post["post_delta_h"] = dh
    post["post_delta_f"] = df
    post["prep_payback"] = None if dg <= 0 else (-float(dh) / float(dg))
    post["legal_delta"] = int(post["legal"]) - int(control.get("legal") or 0)
    post["mixed_delta"] = int(tel["mixed_suit_boundaries"]) - int(control.get("mixed_suit_boundaries") or 0)
    return post


def select_prep_rollout_roots(posts: Sequence[dict], controls: Sequence[dict], *, k: int = SELECT_N) -> List[dict]:
    pool = [r for r in posts if r.get("viable") and r.get("ok")]
    picks: List[dict] = []
    seen: Set[str] = set()

    def take(rec, role):
        if rec is None:
            return
        ident = rec.get("ident") or rec.get("post_digest")
        if not ident or ident in seen:
            return
        seen.add(ident)
        item = dict(rec)
        item["selection_role"] = role
        picks.append(item)

    for c in controls:
        take(c, "immediate_deal")
    if not pool:
        return picks[: int(k)]
    take(min(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]))), "lowest_f")
    take(min(pool, key=lambda r: (int(r["assembly_h"]), int(r["post_g"]))), "lowest_h")
    take(max(pool, key=lambda r: (int(r["slack"]), -int(r["post_g"]))), "greatest_slack")
    take(max(pool, key=lambda r: (int(r["legal"]), -int(r["post_g"]))), "highest_mobility")
    take(max(pool, key=lambda r: (int(r["empty_n"]), -int(r["post_g"]))), "most_empties")
    take(min(pool, key=lambda r: (int(r["mixed_suit_boundaries"]), int(r["post_g"]))), "lowest_mixed")
    take(max(pool, key=lambda r: (int(r["foundations"]), -int(r["assembly_f"]))), "highest_F")
    for band in ("0", "1-2", "3-5", "6-9", "10-15"):
        banded = [r for r in pool if r.get("prep_band") == band]
        if banded:
            take(min(banded, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]))), f"band_{band}")
    for src in ("NEW_G128_F2", "INCUMBENT_G129_F2"):
        srcs = [r for r in pool if r.get("source") == src]
        if srcs:
            take(min(srcs, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]))), f"src_{src}")
    for rec in sorted(pool, key=lambda r: (int(r["assembly_f"]), int(r["post_g"]), r["post_digest"])):
        if len(picks) >= int(k):
            break
        take(rec, "fill")
    return picks[: int(k)]


def load_prep_closed_table() -> dict:
    from spider.f2_quality_frontier import load_f2_closed_table

    table = dict(load_f2_closed_table())
    if V087_JSON.exists():
        data = json.loads(V087_JSON.read_text(encoding="utf-8"))
        for rec in data.get("portfolio") or []:
            ident = rec.get("ident")
            digest = rec.get("ordered_digest")
            if not ident and digest:
                st = unpack_state(bytes.fromhex(digest))
                ident = pack_whole_game_identity(st).hex()
            if not ident:
                continue
            g = int(rec.get("g") or 0)
            prev = table.get(ident)
            if prev is None or g < int(prev["g"]):
                table[ident] = {"ident": ident, "ordered_digest": digest, "g": g, "source": "v087"}
    return table


def choose_prep_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "POST_F2_PREP_CONTRACT_FAILURE", p.get("contract_reason") or "root/rules/accounting/identity/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "POST_F2_PREP_COST_IMPROVED", f"solved at g={best}"
    max_f = int(p.get("max_foundations") or 0)
    if max_f >= 6:
        return "POST_F2_PREP_DEEP_ENDGAME", f"maxF={max_f}"
    if p.get("superior_prep"):
        return "POST_F2_PREP_FINDS_SUPERIOR_ROOT", p.get("superior_reason") or "prepared root beats immediate-Deal controls"
    if p.get("productive"):
        return "POST_F2_PREP_PRODUCTIVE_NO_TERMINAL", "preparation improves downstream economics without a complete result"
    if p.get("search_limited"):
        return "POST_F2_PREP_SEARCH_LIMITED", "promising prepared lineage remains resource-limited"
    return "POST_F2_PREP_NO_GAIN", "preparation candidates do not improve downstream future relative to immediate Deal"


def next_recommendation(verdict: str) -> str:
    if verdict == "POST_F2_PREP_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "POST_F2_PREP_FINDS_SUPERIOR_ROOT":
        return "Make the prepared post-SD5 state the next focused endgame control."
    if verdict == "POST_F2_PREP_DEEP_ENDGAME":
        return "Continue hierarchical search from the live F6+ prepared descendant."
    if verdict == "POST_F2_PREP_PRODUCTIVE_NO_TERMINAL":
        return "Continue from the best prepared live root; do not resume closed v0.87 F5s."
    if verdict == "POST_F2_PREP_SEARCH_LIMITED":
        return "Keep prepared-root evaluation; do not widen wall time."
    if verdict == "POST_F2_PREP_NO_GAIN":
        return "Improve the rows=1 F2-producing trajectory rather than mining more post-F2 arrangements."
    return "Do not promote; diagnose the contract."
