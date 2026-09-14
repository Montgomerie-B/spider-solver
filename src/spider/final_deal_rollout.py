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
STAGE_A_S = 10.0
STAGE_B_S = 10.0
STAGE_A_N = 8
STAGE_B_N = 4
ROLLOUT_RESERVE_S = 120.0
STAGE_UNIQUE = 15_000
ROWS0_TARGET = 32
ROWS0_MAX = 64


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
    kept: List[dict] = field(default_factory=list)

    def _keep_best(self, rec, n, g, h, f, legal, b) -> None:
        snap = {
            "g": g,
            "foundations": n,
            "ordered_digest": rec.get("ordered_digest"),
            "full_actions": rec.get("full_actions"),
            "ident": rec.get("ident") or rec.get("whole_game_identity"),
            "face_down": rec.get("face_down"),
            "assembly_h": h,
            "assembly_f": f,
            "legal_tableau": legal,
            "boundaries_total": b,
        }
        self.kept.append(snap)
        if len(self.kept) > 64:
            self.kept = self.kept[-64:]

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
                "ordered_digest": rec.get("ordered_digest"),
                "full_actions": rec.get("full_actions"),
                "ident": rec.get("ident") or rec.get("whole_game_identity"),
                "foundations": n,
                "face_down": rec.get("face_down"),
                "assembly_h": h,
                "assembly_f": f,
            }
        if rec.get("full_actions"):
            self._keep_best(rec, n, g, h, f, legal, b)
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


def _post_as_root(post: dict, *, cat: str = "rollout_root") -> dict:
    return {
        "g": int(post["post_g"]),
        "ordered_digest": post["post_digest"],
        "ident": post.get("whole_game_identity") or post.get("ident"),
        "whole_game_identity": post.get("whole_game_identity") or post.get("ident"),
        "full_actions": post["full_actions"],
        "stock_rows": 0,
        "foundations": post["foundations"],
        "face_down": post["face_down"],
        "lineage": list(post.get("lineage") or []) + ["final_deal_rollout"],
        "portfolio_cat": cat,
        "parent_root": post.get("post_digest"),
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
        "legal_tableau": post.get("legal"),
        "pre_g": post.get("pre_g"),
        "pre_digest": post.get("pre_digest"),
        "role": post.get("role") or post.get("tag"),
    }


def _rec_as_root(rec: dict, *, parent: str, cat: str = "rollout_descendant") -> Optional[dict]:
    if not rec.get("full_actions") or not rec.get("ordered_digest"):
        return None
    ident = rec.get("ident") or rec.get("whole_game_identity")
    if not ident:
        return None
    return {
        "g": int(rec["g"]),
        "ordered_digest": rec["ordered_digest"],
        "ident": ident,
        "whole_game_identity": ident,
        "full_actions": rec["full_actions"],
        "stock_rows": 0,
        "foundations": int(rec.get("foundations") or 0),
        "face_down": rec.get("face_down"),
        "lineage": list(rec.get("lineage") or []) + ["rollout_descendant"],
        "portfolio_cat": cat,
        "parent_root": parent,
        "assembly_h": rec.get("assembly_h") or rec.get("h"),
        "assembly_f": rec.get("assembly_f") or rec.get("f"),
        "legal_tableau": rec.get("legal_tableau") or rec.get("legal"),
    }


def verify_root_ancestry(opening, rec: dict) -> bool:
    try:
        end = opening.clone()
        g = replay_actions(end, as_actions(rec["full_actions"]))
    except Exception:
        return False
    return g == int(rec["g"]) and pack_state(end).hex() == rec["ordered_digest"] and stock_rows(end) == 0


def collect_descendants(opening, post: dict, res, tracker: RolloutTracker) -> List[dict]:
    parent = post["post_digest"]
    pool = [_post_as_root(post)]
    for rec in (res.foundations_cheap or {}).values():
        root = _rec_as_root(rec, parent=parent)
        if root:
            pool.append(root)
    for rec in tracker.kept:
        root = _rec_as_root(rec, parent=parent)
        if root:
            pool.append(root)
    if res.solved and res.solution_actions:
        end = opening.clone()
        try:
            g = replay_actions(end, list(res.solution_actions))
        except Exception:
            g = None
        if g is not None and end.is_solved():
            pool.append(
                {
                    "g": int(g),
                    "ordered_digest": pack_state(end).hex(),
                    "ident": pack_whole_game_identity(end).hex(),
                    "whole_game_identity": pack_whole_game_identity(end).hex(),
                    "full_actions": dump_actions(res.solution_actions),
                    "stock_rows": 0,
                    "foundations": 8,
                    "face_down": 0,
                    "lineage": ["rollout_terminal"],
                    "portfolio_cat": "rollout_terminal",
                    "parent_root": parent,
                }
            )
    kept = []
    seen = set()
    for rec in pool:
        if not verify_root_ancestry(opening, rec):
            continue
        ident = rec["ident"]
        prev = next((k for k in kept if k["ident"] == ident), None)
        if prev is None:
            kept.append(rec)
            seen.add(ident)
        elif int(rec["g"]) < int(prev["g"]):
            kept.remove(prev)
            kept.append(rec)
    return kept


def run_rollout(
    opening,
    post: dict,
    *,
    time_s: float = ROLLOUT_TIME_S,
    unique: int = ROLLOUT_UNIQUE,
    extra_roots: Optional[Sequence[dict]] = None,
) -> dict:
    """Stock-empty search from one post-SD5 state. No suffixes. No continuation table."""

    tracker = RolloutTracker(start_F=int(post["foundations"]), start_g=int(post["post_g"]))
    root = _post_as_root(post)
    roots = [root]
    for extra in extra_roots or []:
        if extra.get("ordered_digest") and extra.get("full_actions"):
            roots.append(dict(extra))
    t0 = time.perf_counter()
    res = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": 187},
        cost_ceiling=ROLLOUT_CEILING,
        incumbent_by_rows={},
        initial_roots=roots,
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
    descendants = collect_descendants(opening, post, res, tracker)
    sig["descendants"] = descendants
    sig["n_descendants"] = len(descendants)
    return sig


def _attached_as_pre(rec: dict) -> Optional[dict]:
    if int(rec.get("stock_rows") or -1) != 1:
        return None
    if rec.get("full_actions") is None or rec.get("ordered_digest") is None:
        return None
    return {
        "ok": True,
        "tag": rec.get("portfolio_cat") or rec.get("role") or "harvest",
        "pre_g": int(rec["g"]),
        "pre_digest": rec["ordered_digest"],
        "pre_identity": rec.get("ident") or rec.get("whole_game_identity"),
        "stock_rows": 1,
        "foundations": int(rec.get("foundations") or 0),
        "face_down": rec.get("face_down"),
        "full_actions": rec["full_actions"],
        "can_deal": True,
        "portfolio_cat": rec.get("portfolio_cat"),
        "from_incumbent_ckpt": bool(rec.get("from_incumbent_ckpt") or rec.get("incumbent_control")),
        "control_slot": bool(rec.get("control_slot")),
        "tactical_target": rec.get("tactical_target"),
        "categories": list(rec.get("categories") or []),
        "preview": rec.get("preview") or rec.get("deal_preview") or {},
        "assembly_h": rec.get("assembly_h"),
        "assembly_f": rec.get("assembly_f"),
        "legal_tableau": rec.get("legal_tableau"),
    }


def select_attached_rollout_candidates(attached: Sequence[dict], *, n: int = STAGE_A_N, ceiling: int = ROLLOUT_CEILING) -> List[dict]:
    """Diversity prefilter of rows=1 harvest roots. Not cheapest-g."""

    pool = []
    seen = set()
    for rec in attached:
        pre = _attached_as_pre(rec)
        if not pre or int(pre["pre_g"]) > int(ceiling):
            continue
        if pre["pre_digest"] in seen:
            continue
        seen.add(pre["pre_digest"])
        pool.append(pre)
    slots = [
        ("tactical_cashout", lambda r: r.get("portfolio_cat") == "tactical_cashout" or r.get("tactical_target")),
        ("incumbent", lambda r: r.get("from_incumbent_ckpt") or r.get("control_slot") or r.get("portfolio_cat") == "incumbent"),
        ("post_deal_operational", lambda r: r.get("portfolio_cat") == "post_deal_operational" or "post_deal_operational" in (r.get("categories") or [])),
        ("post_deal_consolidation", lambda r: r.get("portfolio_cat") == "post_deal_consolidation"),
        ("post_deal_mobility", lambda r: r.get("portfolio_cat") == "post_deal_mobility"),
        ("post_deal_reception", lambda r: r.get("portfolio_cat") == "post_deal_reception"),
        ("post_deal_pareto", lambda r: r.get("portfolio_cat") == "post_deal_pareto"),
        ("cheap", lambda r: r.get("portfolio_cat") in ("cheap", "deal_now", "cheap_viable")),
    ]
    selected = []
    used = set()
    for name, pred in slots:
        cands = [p for p in pool if p["pre_digest"] not in used and pred(p)]
        if not cands:
            continue
        pick = min(cands, key=lambda p: (int(p.get("assembly_f") or INF), -int(p.get("legal_tableau") or 0), p["pre_digest"]))
        pick = dict(pick)
        pick["role"] = name
        selected.append(pick)
        used.add(pick["pre_digest"])
        if len(selected) >= n:
            return selected
    rest = [p for p in pool if p["pre_digest"] not in used]
    rest.sort(key=lambda p: (int(p.get("assembly_f") or INF), -int(p.get("legal_tableau") or 0), p["pre_digest"]))
    for p in rest:
        if len(selected) >= n:
            break
        q = dict(p)
        q["role"] = q.get("portfolio_cat") or "fill"
        selected.append(q)
        used.add(q["pre_digest"])
    return selected[:n]


def _portfolio_sort_key(rec: dict) -> tuple:
    f = rec.get("assembly_f")
    if f is None:
        h = rec.get("assembly_h")
        f = INF if h is None else int(rec["g"]) + int(h)
    return (-int(rec.get("foundations") or 0), int(f), int(rec["g"]), rec.get("ordered_digest") or "")


def build_rows0_portfolio(
    *,
    original_posts: Sequence[dict],
    stage_b: Sequence[dict],
    incumbent_post: Optional[dict] = None,
    target: int = ROWS0_TARGET,
    hard_max: int = ROWS0_MAX,
) -> List[dict]:
    pool = []
    for sig in stage_b:
        pool.extend(sig.get("descendants") or [])
    for post in original_posts:
        pool.append(_post_as_root(post, cat="post_deal_control"))
    if incumbent_post is not None:
        pool.append(_post_as_root(incumbent_post, cat="incumbent_post_deal"))
    dedup = {}
    for rec in pool:
        ident = rec.get("ident")
        if not ident:
            continue
        prev = dedup.get(ident)
        if prev is None or int(rec["g"]) < int(prev["g"]):
            dedup[ident] = rec
    ranked = sorted(dedup.values(), key=_portfolio_sort_key)
    must = []
    seen = set()

    def _take(rec):
        if rec and rec.get("ident") not in seen:
            must.append(rec)
            seen.add(rec["ident"])

    for sig in stage_b[:4]:
        d = sig.get("post_digest")
        orig = next((r for r in ranked if r.get("ordered_digest") == d), None)
        _take(orig)
        desc = next(
            (r for r in ranked if r.get("parent_root") == d and r.get("ordered_digest") != d),
            None,
        )
        _take(desc)
    if incumbent_post is not None:
        _take(next((r for r in ranked if r.get("ordered_digest") == incumbent_post.get("post_digest")), None))
    for post in original_posts:
        _take(next((r for r in ranked if r.get("ordered_digest") == post.get("post_digest")), None))
    out = list(must)
    for rec in ranked:
        if rec["ident"] in seen:
            continue
        out.append(rec)
        seen.add(rec["ident"])
        if len(out) >= int(target):
            break
    return out[: int(hard_max)]


def guided_final_deal_transition(attached: Sequence[dict], budget_s: float, context: dict) -> dict:
    """Rows=1 harvest → staged rollout → narrowed rows=0 roots. No canonical."""

    opening = context["opening"]
    ceiling = int(context.get("live_ceiling") or context.get("cost_ceiling") or ROLLOUT_CEILING)
    prefilter_n = sum(1 for r in attached if int(r.get("stock_rows") or -1) == 1)
    selected_pre = select_attached_rollout_candidates(attached, n=STAGE_A_N, ceiling=ceiling)
    posts = []
    for pre in selected_pre:
        post = apply_sd5(opening, pre)
        if not post.get("ok"):
            continue
        post["role"] = pre.get("role") or pre.get("tag")
        post["portfolio_cat"] = pre.get("portfolio_cat")
        post["from_incumbent_ckpt"] = pre.get("from_incumbent_ckpt")
        post["tactical_target"] = pre.get("tactical_target")
        posts.append(post)
    n_a = max(1, len(posts))
    time_a = min(STAGE_A_S, float(budget_s) / float(n_a)) if n_a else 0.0
    unique_left = int(context.get("remaining_unique") or STAGE_UNIQUE * n_a)
    unique_a = max(1000, min(STAGE_UNIQUE, unique_left // max(1, n_a)))
    stage_a = []
    t0 = time.perf_counter()
    tot_u = tot_e = tot_g = 0
    best_sol = None
    for post in posts:
        sig = run_rollout(opening, post, time_s=time_a, unique=unique_a)
        tot_u += int(sig.get("unique") or 0)
        tot_e += int(sig.get("expanded") or 0)
        tot_g += int(sig.get("generated") or 0)
        stage_a.append(sig)
        if sig.get("solved") and sig.get("terminal_g") is not None:
            if best_sol is None or int(sig["terminal_g"]) < int(best_sol["terminal_g"]):
                best_sol = sig
    stage_a_ranked = sorted(stage_a, key=lambda s: tuple(s.get("rollout_key") or rollout_key(s)))
    remain_b = max(0.0, float(budget_s) - (time.perf_counter() - t0))
    promoted = stage_a_ranked[:STAGE_B_N]
    n_b = len(promoted)
    time_b = min(STAGE_B_S, remain_b / float(n_b)) if n_b and remain_b >= 1.0 else 0.0
    stage_b = []
    if time_b > 0:
        unique_b = max(1000, min(STAGE_UNIQUE, unique_a))
        for sig_a in promoted:
            post = next((p for p in posts if p.get("post_digest") == sig_a.get("post_digest")), None)
            if post is None:
                stage_b.append(dict(sig_a, stage="B_missing_post"))
                continue
            extra = [d for d in (sig_a.get("descendants") or []) if d.get("ordered_digest") != post["post_digest"]]
            sig = run_rollout(opening, post, time_s=time_b, unique=unique_b, extra_roots=extra)
            tot_u += int(sig.get("unique") or 0)
            tot_e += int(sig.get("expanded") or 0)
            tot_g += int(sig.get("generated") or 0)
            sig["stage"] = "B"
            sig["stage_a_max_F"] = sig_a.get("max_F")
            stage_b.append(sig)
            if sig.get("solved") and sig.get("terminal_g") is not None:
                if best_sol is None or int(sig["terminal_g"]) < int(best_sol["terminal_g"]):
                    best_sol = sig
    else:
        stage_b = [dict(s, stage="B_skipped") for s in promoted]
    stage_b_ranked = sorted(stage_b, key=lambda s: tuple(s.get("rollout_key") or rollout_key(s)))
    incumbent_post = next((p for p in posts if p.get("from_incumbent_ckpt") or p.get("role") == "incumbent"), None)
    roots = build_rows0_portfolio(
        original_posts=posts,
        stage_b=stage_b_ranked or stage_a_ranked,
        incumbent_post=incumbent_post,
    )
    elapsed = time.perf_counter() - t0
    report = {
        "prefilter_n": prefilter_n,
        "n_selected": len(posts),
        "selected": [
            {
                "role": p.get("role"),
                "pre_g": p.get("pre_g"),
                "post_g": p.get("post_g"),
                "F": p.get("foundations"),
                "fd": p.get("face_down"),
                "h": p.get("assembly_h"),
                "f": p.get("assembly_f"),
                "legal": p.get("legal"),
                "tactical_target": p.get("tactical_target"),
                "from_incumbent_ckpt": p.get("from_incumbent_ckpt"),
            }
            for p in posts
        ],
        "stage_a": [_slim_rollout(s) for s in stage_a_ranked],
        "stage_b": [_slim_rollout(s) for s in stage_b_ranked],
        "ranking_a": [s.get("role") for s in stage_a_ranked],
        "ranking_b": [s.get("role") for s in stage_b_ranked],
        "n_roots0": len(roots),
        "root_F": [int(r.get("foundations") or 0) for r in roots],
        "elapsed_s": elapsed,
        "stage_a_s": time_a * n_a,
        "stage_b_s": time_b * n_b,
        "budget_s": float(budget_s),
    }
    return {
        "roots": roots,
        "unique": tot_u,
        "expanded": tot_e,
        "generated": tot_g,
        "elapsed_s": elapsed,
        "report": report,
        "solution_g": None if best_sol is None else best_sol.get("terminal_g"),
        "solution_actions": None if best_sol is None else best_sol.get("solution_actions"),
        "replay_ok": bool(best_sol and best_sol.get("replay_ok")),
    }


def _slim_cheap_f(cheap) -> dict:
    out = {}
    for k, rec in (cheap or {}).items():
        if not isinstance(rec, dict):
            out[str(k)] = rec
            continue
        out[str(k)] = {
            kk: rec.get(kk)
            for kk in (
                "g",
                "h",
                "f",
                "elapsed_s",
                "legal",
                "boundaries",
                "foundations",
                "face_down",
                "ordered_digest",
                "ident",
            )
            if rec.get(kk) is not None
        }
    return out


def _slim_rollout(sig: dict) -> dict:
    return {
        "role": sig.get("role"),
        "pre_g": sig.get("pre_g"),
        "post_g": sig.get("post_g"),
        "post_digest": sig.get("post_digest"),
        "start_F": sig.get("start_F"),
        "start_h": sig.get("start_h"),
        "start_f": sig.get("start_f"),
        "elapsed_s": sig.get("elapsed_s"),
        "unique": sig.get("unique"),
        "expanded": sig.get("expanded"),
        "max_F": sig.get("max_F"),
        "cheap_F": _slim_cheap_f(sig.get("cheap_F")),
        "min_h": sig.get("min_h"),
        "min_f": sig.get("min_f"),
        "best_mobility": sig.get("best_mobility"),
        "time_first_increase": sig.get("time_first_increase"),
        "g_first_increase": sig.get("g_first_increase"),
        "cost_first_increase": sig.get("cost_first_increase"),
        "solved": sig.get("solved"),
        "terminal_g": sig.get("terminal_g"),
        "n_descendants": sig.get("n_descendants"),
        "rollout_key": sig.get("rollout_key"),
        "stage": sig.get("stage"),
    }


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


def choose_guided_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("incumbent_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "ROLLOUT_GUIDED_CONTRACT_FAILURE", p.get("contract_reason") or "rules/accounting/ancestry/replay failure"
    elapsed = float(p.get("elapsed_s") or 0.0)
    roll_s = float(((p.get("rollout") or {}).get("elapsed_s")) or 0.0)
    if elapsed > 200 and roll_s > 0.28 * elapsed:
        return "ROLLOUT_GUIDED_OVERHEAD_FAILURE", f"rollout used {roll_s:.0f}s of {elapsed:.0f}s"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "ROLLOUT_GUIDED_COST_IMPROVED", f"solved at g={best}"
    max_f = int(p.get("max_foundations") or 0)
    rows0_f = int((p.get("rows0") or {}).get("max_foundations") or 0)
    stage_max = 0
    for s in ((p.get("rollout") or {}).get("stage_a") or []) + ((p.get("rollout") or {}).get("stage_b") or []):
        stage_max = max(stage_max, int(s.get("max_F") or 0))
    integrated_f = max(max_f, rows0_f)
    if integrated_f >= 3:
        return "ROLLOUT_GUIDED_REACHES_DEEP_ENDGAME", f"integrated search reached F{integrated_f}"
    if stage_max >= 3:
        return "ROLLOUT_GUIDED_SELECTS_STRONG_ROOT_NO_CONVERSION", "rollout found F3+ but main rows=0 did not convert further"
    n_sel = int((p.get("rollout") or {}).get("n_selected") or 0)
    if n_sel == 0 and int((p.get("rollout") or {}).get("prefilter_n") or 0) > 0:
        return "ROLLOUT_GUIDED_SIGNAL_LOST_INTEGRATION", "rollout candidates were not produced from autonomous harvest"
    return "ROLLOUT_GUIDED_SIGNAL_LOST_INTEGRATION", "pilot signal did not survive integrated candidate generation"
