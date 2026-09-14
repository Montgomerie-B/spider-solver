"""Integrated strategic/tactical cash-out with maturity-aware root selection.

Strategic search is the frozen v0.69/v0.68 lane set (COST, REVEAL,
CONSTRUCTION, READINESS, HORIZON, ECONOMY, COMPLETION at stock-empty).
The v0.71 tactical planner is unchanged. v0.73 only changes which
rows=1 harvest roots receive probes: state-derived cash-out maturity
plus one autonomous-incumbent control slot.

No suit literals. No incumbent suffix. No canonical reads for search.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

from spider.assembly_lower_bound import completion_key, stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.autonomous_cost import checkpoints_from_trace
from spider.deal_preview import compact_preview, preview_next_deal
from spider.engine import SpiderState
from spider.final_deal_transition import TRANSITION_HARVEST_CATS, TransitionTracker
from spider.foundation_cashout import (
    search_foundation_cashout,
    select_tactical_target,
)
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    load_autonomous_192,
)
from spider.operational_policy import operational_lane_keys, search_operational_optimisation
from spider.operational_viability import rank_ready_suits
from spider.packed_state import unpack_state
from spider.research_actions import as_actions, dump_actions, stock_rows, tableau_actions
from spider.structural_analysis import INF, _n, current_tableau_summary
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    AUGMENT_FRACTION,
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
)

ROWS1_AUGMENT_FRACTION = AUGMENT_FRACTION
TACTICAL_ROOT_LIMIT = 8
TACTICAL_TERMINAL_LIMIT = 8
TACTICAL_PER_ROOT_UNIQUE = 20_000
TACTICAL_PORTFOLIO_CAP = 64
STRATEGIC_LANES = COMPLETION_LANES
ROOT_CAT_ORDER = (
    "incumbent",
    "readiness",
    "cheap_viable",
    "cheap",
    "cheap_fd",
    "economy",
    "construction",
    "pareto",
    "post_deal_mobility",
    "post_deal_consolidation",
    "post_deal_operational",
    "post_deal_reception",
    "post_deal_pareto",
    "deal_now",
)


def strategic_lane_keys(state: SpiderState, g: int):
    """v0.69/v0.68 lanes. No alternate-rank readiness participation."""

    keys = operational_lane_keys(state, g)
    if stock_rows(state) != 0:
        keys["completion"] = None
        return keys
    keys["completion"] = completion_key(state, g)
    return keys


def _ident(rec: dict) -> str:
    return str(rec.get("ident") or rec.get("whole_game_identity") or rec.get("ordered_digest") or "")


def _signature(rec: dict) -> tuple:
    preview = rec.get("preview") or rec.get("deal_preview") or {}
    return (
        int(rec.get("g") or 0),
        int(rec.get("face_down") or rec.get("fd") or 0),
        int(rec.get("empty_n") or rec.get("empties") or 0),
        int(rec.get("legal_tableau") or rec.get("legal_mobility") or 0),
        _n(rec.get("cover")),
        int(rec.get("foundations") or 0),
        int(rec.get("boundaries_total") or preview.get("boundaries") or 0),
        int(preview.get("rank_ok") or 0),
        int(preview.get("same_suit") or 0),
        int(preview.get("visible_components") or rec.get("visible_components") or 0),
    )


def _is_control_root(rec: dict) -> bool:
    return bool(rec.get("incumbent_control") or rec.get("portfolio_cat") == "incumbent")


def analyse_tactical_root(rec: dict, *, cost_ceiling: Optional[int] = None) -> dict:
    """Reconstruct the actual state. Cached n_ready/cover/op_key are not eligibility truth."""

    digest = rec.get("ordered_digest")
    ident = _ident(rec)
    g = int(rec.get("g") or 0)
    base = {
        "ok": False,
        "rec": rec,
        "ident": ident,
        "g": g,
        "portfolio_cat": rec.get("portfolio_cat"),
        "incumbent_control": _is_control_root(rec),
        "from_incumbent_ckpt": bool(rec.get("from_incumbent_ckpt")),
        "cached_n_ready": rec.get("n_ready") if rec.get("n_ready") is not None else rec.get("n_ready_ranked"),
        "cached_cover": rec.get("cover"),
    }
    if not digest:
        base["reason"] = "missing_digest"
        return base
    try:
        state = unpack_state(bytes.fromhex(digest))
    except Exception:
        base["reason"] = "reconstruct_failed"
        return base
    if stock_rows(state) != 1:
        base["reason"] = "not_rows1"
        base["stock_rows"] = stock_rows(state)
        return base
    if cost_ceiling is not None and g > int(cost_ceiling):
        base["reason"] = "over_ceiling"
        return base
    ranked = rank_ready_suits(state, g=g)
    if int(ranked.get("n_ready") or 0) < 1 or ranked.get("best") is None:
        base["reason"] = "no_ready_suit"
        base["n_ready"] = int(ranked.get("n_ready") or 0)
        return base
    best = ranked["best"]
    s = current_tableau_summary(state)
    legal = len(tableau_actions(state))
    analysis = {
        **base,
        "ok": True,
        "reason": None,
        "stock_rows": 1,
        "foundations": int(s["foundations"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_mobility": legal,
        "target_suit": best["suit"],
        "n_ready": int(ranked["n_ready"]),
        "ready_suits": list(ranked.get("ready_suits") or []),
        "cover": best.get("cover"),
        "inaccessible_joins": int(best.get("inaccessible_joins") or 0),
        "relevant_blockers": int(best.get("relevant_blockers") or 0),
        "max_blocker_depth": int(best.get("max_blocker_depth") or 0),
        "k_min_blockers": best.get("k_min_blockers"),
        "a_min_blockers": best.get("a_min_blockers"),
        "gap": best.get("gap"),
        "legal_merge_edges": int(best.get("legal_merge_edges") or 0),
        "buried_components": int(best.get("buried_components") or 0),
        "exposed_components": int(best.get("exposed_components") or 0),
        "movable_exposed": int(best.get("movable_exposed") or 0),
        "boundaries_total": int(best.get("boundaries_total") or s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
    }
    analysis["maturity_key"] = tactical_maturity_key(analysis)
    analysis["pareto_vec"] = tactical_pareto_vec(analysis)
    return analysis


def tactical_maturity_key(a: dict) -> tuple:
    """Lexicographic cash-out maturity. Lower is better. g is last, never primary.

    1. target cover
    2. inaccessible target joins
    3. K access burden
    4. A access burden
    5. target gap
    6. more legal target merge edges
    7. buried target components
    8. relevant blockers
    9. global fd
    10. greater legal mobility
    11. g
    """

    return (
        _n(a.get("cover")),
        int(a.get("inaccessible_joins") or 0),
        int(a.get("k_min_blockers") if a.get("k_min_blockers") is not None else INF),
        int(a.get("a_min_blockers") if a.get("a_min_blockers") is not None else INF),
        _n(a.get("gap")),
        -int(a.get("legal_merge_edges") or 0),
        int(a.get("buried_components") or 0),
        int(a.get("relevant_blockers") or 0),
        int(a.get("face_down") or 0),
        -int(a.get("legal_mobility") or 0),
        int(a.get("g") or 0),
    )


def tactical_pareto_vec(a: dict) -> tuple:
    return (
        int(a.get("g") or 0),
        _n(a.get("cover")),
        int(a.get("inaccessible_joins") or 0),
        int(a.get("k_min_blockers") if a.get("k_min_blockers") is not None else INF),
        int(a.get("a_min_blockers") if a.get("a_min_blockers") is not None else INF),
        int(a.get("relevant_blockers") or 0),
        int(a.get("face_down") or 0),
        -int(a.get("legal_merge_edges") or 0),
        -int(a.get("legal_mobility") or 0),
    )


def _pareto_dominates(a: dict, b: dict) -> bool:
    va, vb = a["pareto_vec"], b["pareto_vec"]
    return all(x <= y for x, y in zip(va, vb)) and any(x < y for x, y in zip(va, vb))


def tactical_maturity_pareto(rows: Sequence[dict]) -> List[dict]:
    out = []
    for rec in rows:
        if any(_pareto_dominates(o, rec) for o in rows if o is not rec):
            continue
        out.append(rec)
    out.sort(key=lambda a: (a["maturity_key"], a["ident"]))
    return out


def select_mature_tactical_roots(
    candidates: Sequence[dict],
    *,
    limit: int = TACTICAL_ROOT_LIMIT,
    cost_ceiling: Optional[int] = None,
) -> List[dict]:
    """At most eight maturity-first roots, plus one incumbent/control slot."""

    analyses: List[dict] = []
    for rec in candidates:
        if rec.get("full_actions") is None and rec.get("node") is None:
            continue
        a = analyse_tactical_root(rec, cost_ceiling=cost_ceiling)
        if a.get("ok"):
            analyses.append(a)
    by_id: Dict[str, dict] = {}
    for a in analyses:
        prev = by_id.get(a["ident"])
        if prev is None or a["maturity_key"] < prev["maturity_key"]:
            by_id[a["ident"]] = a
    analyses = list(by_id.values())
    kept: List[dict] = []
    seen = set()

    def take(a: Optional[dict]) -> bool:
        if a is None or a["ident"] in seen:
            return False
        seen.add(a["ident"])
        kept.append(a)
        return True

    controls = [a for a in analyses if a.get("incumbent_control")]
    controls.sort(key=lambda a: (a["maturity_key"], a["g"], a["ident"]))
    control_used = take(controls[0]) if controls else False
    rest = [a for a in analyses if a["ident"] not in seen]
    rest.sort(key=lambda a: (a["maturity_key"], a["g"], a["ident"]))

    def pick(rows: Sequence[dict], keyfn) -> Optional[dict]:
        if not rows:
            return None
        return min(rows, key=keyfn)

    take(pick(rest, lambda a: (a["maturity_key"], a["ident"])))
    take(pick(rest, lambda a: (_n(a.get("cover")), a["g"], a["ident"])))
    take(
        pick(
            rest,
            lambda a: (
                int(a.get("k_min_blockers") if a.get("k_min_blockers") is not None else INF),
                int(a.get("a_min_blockers") if a.get("a_min_blockers") is not None else INF),
                a["g"],
                a["ident"],
            ),
        )
    )
    take(pick(rest, lambda a: (int(a.get("relevant_blockers") or 0), a["g"], a["ident"])))
    mobile = [a for a in rest if a.get("cover") is not None]
    take(pick(mobile, lambda a: (-int(a.get("legal_mobility") or 0), a["maturity_key"], a["ident"])))
    top_half = rest[: max(1, len(rest) // 2)] if rest else []
    take(pick(top_half, lambda a: (a["g"], a["ident"])))
    for a in tactical_maturity_pareto(rest):
        if len(kept) >= int(limit):
            break
        take(a)
    for a in rest:
        if len(kept) >= int(limit):
            break
        take(a)
    out: List[dict] = []
    for i, a in enumerate(kept[: int(limit)]):
        rec = dict(a["rec"])
        rec["_analysis"] = {k: v for k, v in a.items() if k != "rec"}
        rec["maturity_key"] = list(a["maturity_key"])
        rec["maturity_rank"] = i
        rec["control_slot"] = bool(control_used and i == 0 and a.get("incumbent_control"))
        rec["n_ready"] = a["n_ready"]
        rec["target_suit"] = a["target_suit"]
        rec["state_cover"] = a.get("cover")
        out.append(rec)
    return out


def select_tactical_probe_roots(
    candidates: Sequence[dict],
    *,
    limit: int = TACTICAL_ROOT_LIMIT,
    cost_ceiling: Optional[int] = None,
) -> List[dict]:
    """v0.72 category-diverse selector. Kept for regression comparison."""

    ready: List[dict] = []
    for rec in candidates:
        if rec.get("stock_rows") is not None and int(rec["stock_rows"]) != 1:
            continue
        n_ready = rec.get("n_ready")
        if n_ready is None:
            n_ready = rec.get("n_ready_ranked")
        if int(n_ready or 0) < 1:
            continue
        if cost_ceiling is not None and int(rec.get("g") or 10**9) > int(cost_ceiling):
            continue
        if rec.get("full_actions") is None and rec.get("node") is None:
            continue
        ready.append(rec)
    by_cat: Dict[str, List[dict]] = {}
    for rec in ready:
        cat = str(rec.get("portfolio_cat") or "cheap")
        by_cat.setdefault(cat, []).append(rec)
    for cat, rows in by_cat.items():
        rows.sort(key=lambda r: (int(r.get("g") or 10**9), _ident(r)))
    cats = [c for c in ROOT_CAT_ORDER if by_cat.get(c)]
    cats.extend(sorted(c for c in by_cat if c not in ROOT_CAT_ORDER))
    kept: List[dict] = []
    seen = set()
    while len(kept) < int(limit):
        progressed = False
        for cat in cats:
            rows = by_cat.get(cat) or []
            while rows:
                rec = rows.pop(0)
                ident = _ident(rec)
                if ident in seen:
                    continue
                seen.add(ident)
                kept.append(rec)
                progressed = True
                break
            if len(kept) >= int(limit):
                break
        if not progressed:
            break
    return kept[: int(limit)]


def _is_tactical(rec: dict) -> bool:
    return rec.get("portfolio_cat") == "tactical_cashout" or "tactical_cashout" in (
        rec.get("lineage") or []
    )


def cap_tactical_representation(rows: Sequence[dict], *, cap: int = TACTICAL_PORTFOLIO_CAP) -> List[dict]:
    """Keep ordinary roots in harvest order; admit at most ``cap`` tactical states."""

    ordinary: List[dict] = []
    tactical: List[dict] = []
    seen = set()
    for rec in rows:
        ident = _ident(rec)
        if ident in seen:
            continue
        seen.add(ident)
        if _is_tactical(rec):
            tactical.append(rec)
        else:
            ordinary.append(rec)
    tactical.sort(
        key=lambda r: (
            int(r.get("post_assembly_f") if r.get("post_assembly_f") is not None else 10**9),
            int(r.get("g") or 10**9),
            int((r.get("preview") or r.get("deal_preview") or {}).get("boundaries") or 99),
            -int((r.get("preview") or r.get("deal_preview") or {}).get("legal_tableau") or 0),
            _ident(r),
        )
    )
    return ordinary + tactical[: int(cap)]


def _terminal_attached(root: dict, term: dict, target_suit: str) -> Optional[dict]:
    actions = term.get("actions")
    if not actions:
        return None
    prefix = as_actions(root.get("full_actions") or [])
    path = as_actions(actions)
    full = prefix + path
    digest = term.get("ordered_digest")
    ident = term.get("whole_game_identity") or term.get("ident")
    if not digest or not ident:
        return None
    rec = {
        "g": int(term["g"]),
        "ordered_digest": digest,
        "ident": ident,
        "whole_game_identity": ident,
        "full_actions": dump_actions(full),
        "stock_rows": int(term.get("stock_rows") if term.get("stock_rows") is not None else 1),
        "foundations": int(term.get("foundations") or 0),
        "foundation_suits": list(term.get("foundation_suits") or []),
        "face_down": int(term.get("fd") or term.get("face_down") or 0),
        "empty_n": int(term.get("empties") or term.get("empty_n") or 0),
        "legal_tableau": int(term.get("legal_mobility") or term.get("legal_tableau") or 0),
        "bonds": int(term.get("bonds") or 0),
        "n_ready": 0,
        "cover": term.get("cover"),
        "boundaries_total": term.get("boundaries"),
        "visible_components": term.get("visible_components"),
        "portfolio_cat": "tactical_cashout",
        "lineage": list(root.get("lineage") or []) + ["tactical_cashout"],
        "tactical_target": target_suit,
        "tactical_delta_g": term.get("delta_g"),
        "tactical_n_actions": len(path),
        "root_g": int(root.get("g") or 0),
        "root_ident": _ident(root),
        "root_portfolio_cat": root.get("portfolio_cat"),
        "from_incumbent_ckpt": bool(root.get("from_incumbent_ckpt") or root.get("incumbent_control")),
        "control_slot": bool(root.get("control_slot")),
        "maturity_rank": root.get("maturity_rank"),
        "node": None,
    }
    return rec


def _enrich_deal_preview(rec: dict) -> None:
    digest = rec.get("ordered_digest")
    if not digest:
        return
    st = unpack_state(bytes.fromhex(digest))
    preview = preview_next_deal(st, pre_g=int(rec["g"]), detail="full")
    rec["preview"] = preview
    rec["deal_preview"] = compact_preview(preview)
    if not preview.get("ok") or not preview.get("post_digest"):
        return
    post = unpack_state(bytes.fromhex(preview["post_digest"]))
    h = int(stock_empty_assembly_h(post, int(preview.get("post_g") or 0)))
    rec["post_assembly_h"] = h
    rec["post_assembly_f"] = int(preview.get("post_g") or rec["g"]) + h


def rows1_cashout_augment(rows: int, roots: Sequence[dict], budget_s: float, context: dict) -> dict:
    """Scheduler hook. No-op except at stock_rows == 1."""

    empty = {
        "attached": [],
        "n_probes": 0,
        "n_found": 0,
        "unique": 0,
        "expanded": 0,
        "generated": 0,
        "duplicate_skips": 0,
        "stale_skips": 0,
        "elapsed_s": 0.0,
        "lane_exp": {},
        "probes": [],
    }
    if int(rows) != 1 or float(budget_s) <= 0:
        return empty
    ceiling = int(context.get("epoch_ceil") if context.get("epoch_ceil") is not None else CANDIDATE_CEILING)
    n_ready_roots = sum(
        1 for rec in roots if analyse_tactical_root(rec, cost_ceiling=ceiling).get("ok")
    )
    probes = select_mature_tactical_roots(roots, limit=TACTICAL_ROOT_LIMIT, cost_ceiling=ceiling)
    if not probes:
        empty["n_ready_roots"] = n_ready_roots
        empty["n_selected"] = 0
        empty["control_slot_used"] = False
        return empty
    started = time.perf_counter()
    unique_budget = int(context.get("unique_budget") or TACTICAL_PER_ROOT_UNIQUE * len(probes))
    rss = float(context.get("rss_abort_mb") or SEARCH_RSS_MB)
    attached: List[dict] = []
    lane_exp: Dict[str, int] = {}
    stats = {
        "unique": 0,
        "expanded": 0,
        "generated": 0,
        "duplicate_skips": 0,
        "stale_skips": 0,
        "n_found": 0,
    }
    probe_rows = []
    remaining_s = float(budget_s)
    remaining_u = max(1, unique_budget)
    weights = []
    for rec in probes:
        rank = int(rec.get("maturity_rank") or 7)
        if rec.get("control_slot") or rank <= 2:
            weights.append(3)
        else:
            weights.append(1)
    for i, root in enumerate(probes):
        left = probes[i:]
        left_w = sum(weights[i:]) or 1
        wall = remaining_s - (time.perf_counter() - started)
        if wall <= 0.02 or remaining_u <= 0:
            break
        share_s = max(0.05, wall * (weights[i] / float(left_w)))
        share_u = min(TACTICAL_PER_ROOT_UNIQUE, max(32, remaining_u // max(1, len(left))))
        digest = root.get("ordered_digest")
        if not digest:
            continue
        try:
            state = unpack_state(bytes.fromhex(digest))
        except Exception:
            continue
        if stock_rows(state) != 1:
            continue
        try:
            target = select_tactical_target(state, int(root["g"]))
        except ValueError:
            continue
        t0 = time.perf_counter()
        result = search_foundation_cashout(
            ordered_digest=digest,
            root_g=int(root["g"]),
            target_suit=target["suit"],
            max_unique=share_u,
            time_limit_s=share_s,
            rss_abort_mb=rss,
            cost_ceiling=ceiling,
            portfolio_limit=TACTICAL_TERMINAL_LIMIT,
            skip_preview=True,
        )
        used = time.perf_counter() - t0
        remaining_u = max(0, remaining_u - int(result.unique or 0))
        stats["unique"] += int(result.unique or 0)
        stats["expanded"] += int(result.expanded or 0)
        stats["generated"] += int(result.generated or 0)
        stats["duplicate_skips"] += int(result.duplicate_skips or 0)
        stats["stale_skips"] += int(result.stale_skips or 0)
        for name, n in (result.lane_exp or {}).items():
            lane_exp[name] = lane_exp.get(name, 0) + int(n)
        n_term = 0
        if result.found:
            stats["n_found"] += 1
            portfolio = result.portfolio or []
            for term in portfolio:
                rec = _terminal_attached(root, term, target["suit"])
                if rec is None:
                    continue
                attached.append(rec)
                n_term += 1
        probe_rows.append(
            {
                "root_g": int(root["g"]),
                "root_ident": _ident(root),
                "target_suit": target["suit"],
                "n_ready": target.get("n_ready"),
                "maturity_key": list(root.get("maturity_key") or []),
                "maturity_rank": root.get("maturity_rank"),
                "control_slot": bool(root.get("control_slot")),
                "cover": root.get("state_cover"),
                "found": bool(result.found),
                "first_g": result.first_g,
                "cheapest_g": result.cheapest_g,
                "delta_g": result.delta_g,
                "n_terminals": n_term,
                "unique": result.unique,
                "expanded": result.expanded,
                "elapsed_s": result.elapsed_s,
                "share_s": share_s,
                "stop_reason": result.stop_reason,
            }
        )
        remaining_s = float(budget_s) - (time.perf_counter() - started)
        _ = used
    raw_n = len(attached)
    for rec in attached:
        try:
            _enrich_deal_preview(rec)
        except Exception:
            continue
    attached = cap_tactical_representation(attached, cap=TACTICAL_PORTFOLIO_CAP)
    extra_track = context.get("extra_track")
    min_root_g = int(context.get("min_root_g") or 0)
    if extra_track is not None:
        for rec in attached:
            extra_track({}, rec, min_root_g, {})
    return {
        "attached": attached,
        "n_probes": len(probe_rows),
        "n_selected": len(probes),
        "n_ready_roots": n_ready_roots,
        "control_slot_used": any(bool(r.get("control_slot")) for r in probes),
        "n_found": stats["n_found"],
        "n_terminals_raw": raw_n,
        "n_terminals": len(attached),
        "unique": stats["unique"],
        "expanded": stats["expanded"],
        "generated": stats["generated"],
        "duplicate_skips": stats["duplicate_skips"],
        "stale_skips": stats["stale_skips"],
        "elapsed_s": time.perf_counter() - started,
        "lane_exp": lane_exp,
        "probes": probe_rows,
    }


def enrich_integrated_tactical(state, rec: dict) -> None:
    enrich_assembly(state, rec)
    g = int(rec.get("g") or 0)
    h = int(rec.get("assembly_h") or 0)
    rec["assembly_slack"] = CANDIDATE_CEILING - (g + h)
    ranked = rank_ready_suits(state, g=g)
    rec["ready_ranked_suits"] = [v.get("suit") for v in ranked.get("ranked") or []]
    rec["n_ready_ranked"] = ranked.get("n_ready")


def search_integrated_tactical(
    *,
    opening: Optional[SpiderState] = None,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
    use_checkpoints: bool = True,
    continuation_table=None,
):
    opening = opening or opening_state()
    trace = load_autonomous_192(opening)
    if int(trace["g"]) != AUTONOMOUS_INCUMBENT_MW:
        raise ValueError("autonomous 192 incumbent failed to replay")
    tracker = TransitionTracker()
    ck = checkpoints_from_trace(trace) if use_checkpoints else {}
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace=trace,
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows=ck,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
        harvest_cats=TRANSITION_HARVEST_CATS,
        extra_track=tracker,
        enrich_fn=enrich_integrated_tactical,
        on_harvest=tracker.on_harvest,
        finalize_track=tracker.finalize,
        lane_names=STRATEGIC_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=rows1_cashout_augment,
        augment_fraction=ROWS1_AUGMENT_FRACTION,
        augment_when=lambda rows, _roots: int(rows) == 1,
        continuation_table=continuation_table,
    )
    result.transition_tracker = tracker
    result.n_previewed = tracker.n_previewed
    result.transition_selected = tracker.selected
    result.transition_cats = tracker.selected_cats
    result.incumbent_g = AUTONOMOUS_INCUMBENT_MW
    result.candidate_ceiling = getattr(result, "candidate_ceiling", None) or CANDIDATE_CEILING
    return result


def choose_integrated_tactical_verdict(p: dict) -> Tuple[str, str]:
    if p.get("incumbent_fail") or p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return (
            "TACTICAL_INTEGRATION_CONTRACT_FAILURE",
            p.get("contract_reason") or "replay, identity or accounting failed",
        )
    inc = int(p.get("incumbent_g") or AUTONOMOUS_INCUMBENT_MW)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "TACTICAL_INTEGRATION_COST_IMPROVED", f"solved at g={best}"
    tac = p.get("tactical") or {}
    n_term = int(tac.get("n_terminals") or 0)
    n_found = int(tac.get("n_found") or 0)
    f2 = p.get("best_presd5_f2") or {}
    rows1_f2 = (
        f2.get("g") is not None
        and int(f2.get("stock_rows") or f2.get("rows") or -1) == 1
        and int(f2.get("F") or f2.get("foundations") or 0) >= 2
    )
    tactical_f2 = rows1_f2 and (
        f2.get("portfolio_cat") == "tactical_cashout" or bool(f2.get("tactical_target"))
    )
    r1 = next((ep for ep in (p.get("epochs") or []) if int(ep.get("stock_rows") or -1) == 1), {})
    r1_exp = int(r1.get("expanded") or 0)
    if r1_exp < 80 and n_found == 0 and int(tac.get("unique") or 0) > max(1, r1_exp) * 4:
        return (
            "TACTICAL_INTEGRATION_OVERHEAD_FAILURE",
            "tactical augmentation consumed rows=1 capacity without useful cash-outs",
        )
    if tactical_f2 or (rows1_f2 and n_term > 0):
        return (
            "TACTICAL_INTEGRATION_REACHES_PRESD5_F2",
            "integrated search produced a pre-SD5 F2 through tactical augmentation",
        )
    if n_found > 0 and int(p.get("max_foundations") or 0) < 2:
        return (
            "TACTICAL_INTEGRATION_NO_USEFUL_CASHOUT",
            "probes cashed out but terminals did not survive into a useful whole-game F2",
        )
    if n_term > 0 or n_found > 0:
        return (
            "TACTICAL_INTEGRATION_IMPROVES_TRANSITION",
            "tactical terminals entered the pre-Deal set without a surviving pre-SD5 F2 record",
        )
    called = bool((r1.get("augment") or {}).get("called"))
    if called:
        return "TACTICAL_INTEGRATION_NO_GAIN", "tactical probes added no meaningful additional states"
    return "TACTICAL_INTEGRATION_NO_GAIN", "tactical augmentation did not run or found nothing"


def choose_maturity_tactical_verdict(p: dict) -> Tuple[str, str]:
    if p.get("incumbent_fail") or p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return (
            "MATURITY_TACTICAL_CONTRACT_FAILURE",
            p.get("contract_reason") or "replay, identity or accounting failed",
        )
    inc = int(p.get("incumbent_g") or AUTONOMOUS_INCUMBENT_MW)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "MATURITY_TACTICAL_COST_IMPROVED", f"solved at g={best}"
    tac = p.get("tactical") or {}
    n_term = int(tac.get("n_terminals") or 0)
    n_found = int(tac.get("n_found") or 0)
    f2 = p.get("best_presd5_f2") or {}
    rows1_f2 = (
        f2.get("g") is not None
        and int(f2.get("stock_rows") or f2.get("rows") or -1) == 1
        and int(f2.get("F") or f2.get("foundations") or 0) >= 2
    )
    control = bool(tac.get("control_slot_used") or (p.get("audit") or {}).get("control_selected"))
    if rows1_f2 and (f2.get("portfolio_cat") == "tactical_cashout" or f2.get("tactical_target")):
        return "MATURITY_TACTICAL_REDISCOVERS_F2", "integrated probes produced a pre-SD5 F2"
    if n_found > 0:
        futures = [r.get("post_assembly_f") for r in (p.get("tactical_terminals") or []) if r.get("post_assembly_f") is not None]
        if futures and min(int(x) for x in futures) <= 191:
            return "MATURITY_TACTICAL_IMPROVES_FUTURE", "cash-out terminals improve post-Deal f"
        return "MATURITY_TACTICAL_CASHOUT_POOR_FUTURE", "foundations cashed but post-Deal f/topology is poor"
    if control and n_found == 0:
        return (
            "MATURITY_TACTICAL_ROOT_SELECTION_FIXED_PLANNER_FAILS",
            "mature/control roots were probed but bounded cash-out still failed",
        )
    if n_term > 0:
        return "MATURITY_TACTICAL_IMPROVES_FUTURE", "tactical terminals entered the pre-Deal set"
    return "MATURITY_TACTICAL_NO_GAIN", "no meaningful improvement despite root-selection changes"
