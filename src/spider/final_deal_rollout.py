"""v0.76 bounded stock-empty rollout of final-Deal roots.

Pilot only. Does not change whole-game harvest, scheduler, or lanes.
Canonical 172 is not used for corpus, selection, search, or ranking.
The continuation table may reconstruct machine rows=1 roots; it must not
supply suffixes, upper bounds, or move ordering inside a rollout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.autonomous_continuations import (
    AUTONOMOUS_SOURCES,
    ContinuationTable,
    build_autonomous_continuation_table,
)
from spider.deal_preview import preview_next_deal
from spider.foundation_cashout import (
    replay_to_stock_rows,
    search_foundation_cashout,
    select_tactical_target,
)
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import (
    apply_action,
    as_actions,
    dump_actions,
    face_down_count,
    is_deal,
    step_cost,
    stock_rows,
    tableau_actions,
)
from spider.state_convergence import V073_F2_DIGEST
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB

ROOT = Path(__file__).resolve().parents[2]
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
CONT71 = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71_continuation.json"

ROLLOUT_TIME_S = 30.0
ROLLOUT_UNIQUE = 50_000
ROLLOUT_RSS_MB = SEARCH_RSS_MB
ROLLOUT_CEILING = 186
PILOT_N = 8
INF = 10**9


def pre_sd5_from_actions(opening, actions: Sequence[Action]) -> dict:
    """State immediately before the last legal Deal (SD5)."""

    state = opening.clone()
    g = 0
    prefix: List[Action] = []
    last = None
    for action in actions:
        if is_deal(action) and stock_rows(state) == 1 and state.can_deal():
            last = _pre_snapshot(state, g, prefix, tag="control")
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        prefix.append(action)
    if last is None:
        return {"ok": False, "reason": "no_rows1_deal"}
    last["ok"] = True
    return last


def _pre_snapshot(state, g: int, prefix: Sequence[Action], *, tag: str) -> dict:
    return {
        "ok": True,
        "tag": tag,
        "pre_g": int(g),
        "pre_digest": pack_state(state).hex(),
        "pre_identity": pack_whole_game_identity(state).hex(),
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "face_down": face_down_count(state),
        "full_actions": dump_actions(list(prefix)),
        "can_deal": bool(state.can_deal()),
    }


def apply_sd5(opening, pre: dict) -> dict:
    """Exact engine Deal from a rows=1 snapshot. Absolute g is not reset."""

    if int(pre.get("stock_rows") or -1) != 1 or not pre.get("can_deal", True):
        return {"ok": False, "reason": "not_rows1"}
    state = unpack_state(bytes.fromhex(pre["pre_digest"]))
    if stock_rows(state) != 1 or not state.can_deal():
        return {"ok": False, "reason": "cannot_deal"}
    preview = preview_next_deal(state, pre_g=int(pre["pre_g"]), detail="full")
    deal_c = apply_action(state, ("deal",))
    g = int(pre["pre_g"]) + int(deal_c)
    s = current_tableau_summary(state)
    h = int(stock_empty_assembly_h(state, g))
    post = {
        "ok": stock_rows(state) == 0,
        "tag": pre.get("tag"),
        "pre_g": int(pre["pre_g"]),
        "pre_digest": pre["pre_digest"],
        "deal_cost": int(deal_c),
        "post_g": g,
        "post_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "stock_rows": 0,
        "foundations": int(s["foundations"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal": len(tableau_actions(state)),
        "bonds": int(s["same_suit_bonds"]),
        "merges": int(s["merge_edges"]),
        "boundaries": int(preview.get("boundaries") or s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
        "component_layers": int(preview.get("component_layers") or 0),
        "rank_ok": int(preview.get("rank_ok") or 0),
        "same_suit": int(preview.get("same_suit") or 0),
        "assembly_h": h,
        "assembly_f": g + h,
        "op_key": preview.get("op_key"),
        "n_ready": preview.get("n_ready"),
        "full_actions": dump_actions(as_actions(pre.get("full_actions") or []) + [("deal",)]),
        "preview": {
            "legal_tableau": preview.get("legal_tableau"),
            "boundaries": preview.get("boundaries"),
            "rank_ok": preview.get("rank_ok"),
            "same_suit": preview.get("same_suit"),
            "mixed": preview.get("mixed"),
        },
    }
    return post


def reconstruct_tactical_f2(opening) -> dict:
    """Machine g=128 F2 that is digest-different from the 187 F2."""

    actions = parse_moves_file(V074)
    ck = replay_to_stock_rows(opening, actions, target_rows=1)
    if CONT71.exists():
        import json

        data = json.loads(CONT71.read_text(encoding="utf-8"))
        prefix = as_actions(ck["prefix_actions"]) + as_actions(data.get("tactical_actions") or [])
        end = opening.clone()
        g = replay_actions(end, list(prefix))
        digest = pack_state(end).hex()
        if (
            digest == data.get("terminal_digest")
            and digest != V073_F2_DIGEST
            and int(g) == 128
            and stock_rows(end) == 1
        ):
            snap = _pre_snapshot(end, g, prefix, tag="tactical_f2_g128")
            snap["ok"] = True
            snap["tactical_g"] = 128
            snap["tactical_target"] = data.get("target_suit")
            return snap
    state = unpack_state(bytes.fromhex(ck["ordered_digest"]))
    target = select_tactical_target(state, int(ck["g"]))
    result = search_foundation_cashout(
        ordered_digest=ck["ordered_digest"],
        root_g=int(ck["g"]),
        target_suit=target["suit"],
        max_unique=20_000,
        time_limit_s=8.0,
        rss_abort_mb=ROLLOUT_RSS_MB,
        cost_ceiling=191,
        portfolio_limit=16,
        skip_preview=True,
    )
    match = None
    for term in list(result.portfolio or []) + list(result.terminals or []):
        digest = term.get("ordered_digest")
        if digest and digest != V073_F2_DIGEST and int(term.get("g") or 0) <= 128:
            if match is None or int(term["g"]) < int(match["g"]):
                match = term
    if match is None:
        return {"ok": False, "reason": "tactical_f2_not_found"}
    prefix = as_actions(ck["prefix_actions"]) + as_actions(match["actions"])
    end = opening.clone()
    g = replay_actions(end, list(prefix))
    if pack_state(end).hex() != match["ordered_digest"] or stock_rows(end) != 1:
        return {"ok": False, "reason": "tactical_replay_mismatch"}
    snap = _pre_snapshot(end, g, prefix, tag="tactical_f2_g128")
    snap["ok"] = True
    snap["tactical_g"] = int(match["g"])
    snap["tactical_target"] = target["suit"]
    return snap


def control_pre_sd5(opening) -> Dict[str, dict]:
    out = {
        "ctrl_187": pre_sd5_from_actions(opening, parse_moves_file(V074)),
        "ctrl_192": pre_sd5_from_actions(opening, parse_moves_file(V067)),
        "ctrl_198": pre_sd5_from_actions(opening, parse_moves_file(V059)),
    }
    for name, rec in out.items():
        rec["tag"] = name
    return out


def corpus_from_table(opening, table: ContinuationTable) -> List[dict]:
    """rows=1 machine states from the continuation table. No suffixes kept."""

    out = []
    seen = set()
    source_actions = {}
    for name, path, _g in AUTONOMOUS_SOURCES:
        source_actions[name] = parse_moves_file(path)
    for digest, ent in table.entries.items():
        if int(ent.stock_rows) != 1:
            continue
        if digest in seen:
            continue
        seen.add(digest)
        state = unpack_state(bytes.fromhex(digest))
        if stock_rows(state) != 1 or not state.can_deal():
            continue
        src_acts = source_actions.get(ent.source_solution) or []
        prefix = src_acts[: int(ent.suffix_start_index)]
        out.append(
            _pre_snapshot(state, int(ent.source_prefix_g), prefix, tag=f"table:{ent.source_solution}")
        )
    return out


def select_pilot_roots(opening, *, table: Optional[ContinuationTable] = None, n: int = PILOT_N) -> List[dict]:
    table = table or build_autonomous_continuation_table(opening)
    controls = control_pre_sd5(opening)
    tac = reconstruct_tactical_f2(opening)
    mandatory = [controls["ctrl_187"], controls["ctrl_192"], controls["ctrl_198"]]
    if tac.get("ok"):
        mandatory.append(tac)
    selected: List[dict] = []
    seen = set()
    for pre in mandatory:
        if not pre.get("ok"):
            continue
        d = pre["pre_digest"]
        if d in seen:
            continue
        seen.add(d)
        post = apply_sd5(opening, pre)
        if not post.get("ok"):
            continue
        post["role"] = pre.get("tag")
        selected.append(post)
    corpus = corpus_from_table(opening, table)
    posts = []
    for pre in corpus:
        if pre["pre_digest"] in seen:
            continue
        post = apply_sd5(opening, pre)
        if post.get("ok"):
            post["role"] = pre.get("tag")
            posts.append(post)
    fillers = [
        ("low_f", lambda p: (int(p["assembly_f"]), int(p["post_g"]), p["post_digest"])),
        ("mobility", lambda p: (-int(p["legal"]), int(p["post_g"]), p["post_digest"])),
        ("consolidation", lambda p: (-int(p["bonds"]), -int(p["merges"]), int(p["post_g"]), p["post_digest"])),
        ("operational", lambda p: tuple(p.get("op_key") or (INF,)) + (int(p["post_g"]), p["post_digest"])),
        ("reception", lambda p: (-int(p["rank_ok"]), -int(p["same_suit"]), int(p["post_g"]), p["post_digest"])),
    ]
    for name, key in fillers:
        if len(selected) >= n:
            break
        if not posts:
            break
        best = min(posts, key=key)
        best["role"] = f"fill_{name}"
        seen.add(best["pre_digest"])
        selected.append(best)
        posts = [p for p in posts if p["pre_digest"] not in seen]
    if len(selected) < n and posts:
        def pvec(p):
            return (int(p["post_g"]), -int(p["foundations"]), int(p["assembly_h"]), -int(p["legal"]), int(p["boundaries"]))
        rest = sorted(posts, key=lambda p: p["post_digest"])
        pareto = []
        for p in rest:
            if any(all(a <= b for a, b in zip(pvec(q), pvec(p))) and any(a < b for a, b in zip(pvec(q), pvec(p))) for q in pareto):
                continue
            pareto = [
                q
                for q in pareto
                if not (
                    all(a <= b for a, b in zip(pvec(p), pvec(q)))
                    and any(a < b for a, b in zip(pvec(p), pvec(q)))
                )
            ]
            pareto.append(p)
        if pareto:
            pick = sorted(pareto, key=lambda p: p["post_digest"])[0]
            pick["role"] = "fill_pareto"
            selected.append(pick)
    return selected[:n]


@dataclass
class RolloutTracker:
    start_F: int
    start_g: int
    t0: float = field(default_factory=time.perf_counter)
    max_F: int = 0
    cheap_F: Dict[int, dict] = field(default_factory=dict)
    min_h: Optional[int] = None
    min_f: Optional[int] = None
    best_mobility: Optional[int] = None
    min_boundaries: Optional[int] = None
    min_components: Optional[int] = None
    time_first_increase: Optional[float] = None
    g_first_increase: Optional[int] = None

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        n = int(rec.get("foundations") or 0)
        g = int(rec.get("g") or 0)
        h = rec.get("assembly_h")
        f = rec.get("assembly_f")
        if f is None and h is not None:
            f = g + int(h)
        legal = rec.get("legal_tableau")
        b = rec.get("boundaries_total")
        elapsed = time.perf_counter() - self.t0
        if n > self.max_F:
            self.max_F = n
        prev = self.cheap_F.get(n)
        if prev is None or g < int(prev["g"]):
            self.cheap_F[n] = {
                "g": g,
                "h": h,
                "f": f,
                "elapsed_s": elapsed,
                "legal": legal,
                "boundaries": b,
            }
        if n > self.start_F and self.time_first_increase is None:
            self.time_first_increase = elapsed
            self.g_first_increase = g
        if h is not None:
            self.min_h = int(h) if self.min_h is None else min(self.min_h, int(h))
        if f is not None:
            self.min_f = int(f) if self.min_f is None else min(self.min_f, int(f))
        if legal is not None:
            self.best_mobility = int(legal) if self.best_mobility is None else max(self.best_mobility, int(legal))
        if b is not None:
            self.min_boundaries = int(b) if self.min_boundaries is None else min(self.min_boundaries, int(b))
        vis = rec.get("visible_components")
        if vis is not None:
            self.min_components = int(vis) if self.min_components is None else min(self.min_components, int(vis))


def rollout_key(sig: dict) -> tuple:
    """Experimental ranking only. Not admissible. Not a proof bound."""

    solved = 0 if sig.get("solved") else 1
    term = int(sig["terminal_g"]) if sig.get("solved") and sig.get("terminal_g") is not None else INF
    max_f = int(sig.get("max_F") or 0)
    cheap = ((sig.get("cheap_F") or {}).get(str(max_f)) or (sig.get("cheap_F") or {}).get(max_f) or {})
    f_at = cheap.get("f")
    if f_at is None:
        f_at = INF
    g_at = cheap.get("g")
    if g_at is None:
        g_at = INF
    h = sig.get("min_h")
    if h is None:
        h = INF
    mob = sig.get("best_mobility")
    if mob is None:
        mob = -INF
    bounds = sig.get("min_boundaries")
    if bounds is None:
        bounds = INF
    return (
        solved,
        term,
        -max_f,
        int(f_at),
        int(g_at),
        int(h),
        -int(mob),
        int(bounds),
        int(sig.get("post_g") or INF),
    )


def run_rollout(opening, post: dict, *, time_s: float = ROLLOUT_TIME_S, unique: int = ROLLOUT_UNIQUE) -> dict:
    """Stock-empty search from one post-SD5 state. No suffixes. No continuation table."""

    tracker = RolloutTracker(start_F=int(post["foundations"]), start_g=int(post["post_g"]))
    root = {
        "g": int(post["post_g"]),
        "ordered_digest": post["post_digest"],
        "ident": post["whole_game_identity"],
        "whole_game_identity": post["whole_game_identity"],
        "full_actions": post["full_actions"],
        "stock_rows": 0,
        "foundations": post["foundations"],
        "face_down": post["face_down"],
        "lineage": ["final_deal_rollout_v076"],
        "portfolio_cat": "rollout_root",
    }
    t0 = time.perf_counter()
    res = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": 187},
        cost_ceiling=ROLLOUT_CEILING,
        incumbent_by_rows={},
        initial_roots=[root],
        max_unique=int(unique),
        time_limit_s=float(time_s),
        rss_abort_mb=ROLLOUT_RSS_MB,
        harvest_cats=OP_HARVEST_CATS,
        enrich_fn=enrich_assembly,
        lane_names=COMPLETION_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=None,
        continuation_table=None,
        extra_track=tracker,
    )
    cheap = {int(k): v for k, v in tracker.cheap_F.items()}
    sig = {
        "role": post.get("role") or post.get("tag"),
        "pre_g": post["pre_g"],
        "pre_digest": post["pre_digest"],
        "post_g": post["post_g"],
        "post_digest": post["post_digest"],
        "start_F": post["foundations"],
        "start_fd": post["face_down"],
        "start_legal": post["legal"],
        "start_empty": post["empty_n"],
        "start_boundaries": post["boundaries"],
        "start_components": post["visible_components"],
        "start_h": post["assembly_h"],
        "start_f": post["assembly_f"],
        "elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "proof_prunes": res.lower_bound_prunes,
        "lane_exp": dict(res.lane_exp or {}),
        "peak_rss_mb": res.peak_rss_mb,
        "stop_reason": res.stop_reason,
        "max_F": tracker.max_F if tracker.max_F else post["foundations"],
        "cheap_F": {str(k): v for k, v in sorted(cheap.items())},
        "min_h": tracker.min_h,
        "min_f": tracker.min_f,
        "best_mobility": tracker.best_mobility,
        "min_boundaries": tracker.min_boundaries,
        "min_components": tracker.min_components,
        "time_first_increase": tracker.time_first_increase,
        "g_first_increase": tracker.g_first_increase,
        "cost_first_increase": None
        if tracker.g_first_increase is None
        else int(tracker.g_first_increase) - int(post["post_g"]),
        "solved": bool(res.solved and res.replay_ok),
        "terminal_g": res.solution_g if res.solved and res.replay_ok else None,
        "replay_ok": bool(res.replay_ok),
        "wall_s": time.perf_counter() - t0,
    }
    sig["rollout_key"] = list(rollout_key(sig))
    if sig["solved"] and res.solution_actions:
        sig["solution_actions"] = dump_actions(res.solution_actions)
    return sig


def choose_rollout_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("firewall_fail"):
        return "ROLLOUT_CONTRACT_FAILURE", p.get("contract_reason") or "rules/accounting/firewall failure"
    best = p.get("best_complete_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < 187:
        return "ROLLOUT_COST_IMPROVED", f"solved at g={best}"
    ranking = p.get("ranking") or []
    machine = [r for r in ranking if r.get("role") != "canonical"]
    f_progress = any(int(r.get("max_F") or 0) > int(r.get("start_F") or 0) for r in machine)
    if machine and not f_progress and not any(r.get("solved") for r in machine):
        return "ROLLOUT_SIGNAL_TOO_SHALLOW", "no candidate increased F within the equal budget"
    keys = [tuple(r.get("rollout_key") or []) for r in machine]
    spread = bool(keys) and keys[0] != keys[-1]
    static_order = p.get("static_order_roles") or []
    rollout_order = [r.get("role") for r in machine]
    disagree = static_order and rollout_order and static_order != rollout_order
    misleading = bool(p.get("misleading"))
    if misleading:
        return "ROLLOUT_SIGNAL_MISLEADING", "short-rollout ranking conflicts with known downstream results"
    ctrl = (p.get("control_comparison") or {}).get("rollout_order") or []
    sep = "ctrl_187" in ctrl and "ctrl_198" in ctrl and ctrl.index("ctrl_187") < ctrl.index("ctrl_198")
    if spread and f_progress and sep and disagree:
        return "ROLLOUT_SIGNAL_STRONGLY_DISCRIMINATES", "bounded rollout separates final-Deal board quality"
    if spread and disagree:
        return "ROLLOUT_SIGNAL_USEFUL", "rollout ranking differs from one-step preview and separates candidates"
    if spread and not disagree:
        return "ROLLOUT_SIGNAL_STATIC_EQUIVALENT", "rollout order matches one-step static ranking"
    return "ROLLOUT_SIGNAL_TOO_SHALLOW", "equal bounded searches did not differentiate roots"
