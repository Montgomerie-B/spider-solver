"""v0.66 final-Deal transition-aware portfolio harvest.

Rows=1 harvest may inspect the exact post-Deal clone. Intra-epoch lanes
and post-stock search remain the frozen v0.63/v0.65 policy. No fitted
transition scalar. No canonical reads for search.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

from spider.deal_preview import compact_preview, preview_next_deal
from spider.engine import SpiderState
from spider.healthy_f2 import (
    CANDIDATE_CEILING,
    F2_FD,
    F2_G,
    F2_N,
    F2_ROWS,
    INCUMBENT_G,
    parse_stored_actions,
    verify_f2_prefix,
)
from spider.operational_policy import (
    OP_HARVEST_CATS,
    enrich_operational,
    search_operational_optimisation,
)
from spider.packed_state import unpack_state
from spider.research_actions import dump_actions, tableau_actions
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    _n,
)

LINEAGE_TAG = "v065_f2_g130"
V065_JSON = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "healthy_f2_cost_to_go_v0_65.json"
)
V065_F3 = 179
V065_F4 = 186
V065_F5 = 194
V065_F6 = 197

TRANSITION_CATS = (
    "post_deal_mobility",
    "post_deal_consolidation",
    "post_deal_operational",
    "post_deal_reception",
    "post_deal_pareto",
)
TRANSITION_HARVEST_CATS = OP_HARVEST_CATS + TRANSITION_CATS
TRANSITION_SHARE_MAX = 0.34


def load_v065_f2_actions() -> list:
    if not V065_JSON.exists():
        return []
    data = json.loads(V065_JSON.read_text(encoding="utf-8"))
    return parse_stored_actions(data.get("f2_prefix_actions") or [])


def load_v065_f2_digest() -> str:
    if not V065_JSON.exists():
        return ""
    data = json.loads(V065_JSON.read_text(encoding="utf-8"))
    return str(data.get("f2_digest") or "")


def verify_v065_f2(opening: SpiderState, actions: Sequence) -> dict:
    snap = verify_f2_prefix(opening, actions)
    expected = load_v065_f2_digest()
    snap["digest_match"] = bool(expected) and snap.get("ordered_digest") == expected
    snap["replay_ok"] = bool(snap.get("replay_ok")) and snap["digest_match"]
    return snap


def reconstruct_v065_f2(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    actions = load_v065_f2_actions()
    if not actions:
        return {
            "ok": False,
            "reason": "FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE",
            "debug": {"f2": "missing prefix"},
        }
    snap = verify_v065_f2(opening, actions)
    if not snap.get("replay_ok"):
        return {
            "ok": False,
            "reason": "FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE",
            "snap": snap,
        }
    root = {
        "g": F2_G,
        "ordered_digest": snap["ordered_digest"],
        "whole_game_identity": snap["whole_game_identity"],
        "ident": snap["whole_game_identity"],
        "full_actions": dump_actions(actions),
        "stock_rows": F2_ROWS,
        "foundations": F2_N,
        "face_down": F2_FD,
        "lineage": [LINEAGE_TAG],
        "portfolio_cat": "f2_root",
    }
    return {"ok": True, "actions": actions, "root": root, "snap": snap}


def enrich_transition(state: SpiderState, rec: dict) -> None:
    enrich_operational(state, rec)
    rec["legal_tableau"] = len(tableau_actions(state))
    if int(rec.get("stock_rows") or 0) != 1:
        return
    if not state.can_deal():
        return
    rec["preview"] = preview_next_deal(state, pre_g=int(rec.get("g") or 0), detail="harvest")


def _post_vec(rec: dict, *, include_op: bool) -> tuple:
    p = rec.get("preview") or {}
    vec = [
        int(p.get("post_g") or rec.get("g") or 0),
        -int(p.get("foundations") or 0),
        int(p.get("face_down") or 0),
        -int(p.get("legal_tableau") or 0),
        int(p.get("boundaries") or 0),
        int(p.get("visible_components") or 0),
    ]
    if include_op and p.get("op_defined") and p.get("op_key"):
        vec.extend(int(x) for x in p["op_key"])
    return tuple(vec)


def _dominates(a: dict, b: dict, *, include_op: bool) -> bool:
    va, vb = _post_vec(a, include_op=include_op), _post_vec(b, include_op=include_op)
    return all(x <= y for x, y in zip(va, vb)) and any(x < y for x, y in zip(va, vb))


def pareto_preview(rows: Sequence[dict]) -> list:
    """Full all-pairs Pareto. Reference implementation for tests."""

    defined = [r for r in rows if (r.get("preview") or {}).get("op_defined")]
    plain = [r for r in rows if r not in defined]
    out = []
    for grp, use_op in ((defined, True), (plain, False)):
        for rec in grp:
            if any(_dominates(o, rec, include_op=use_op) for o in grp if o is not rec):
                continue
            out.append(rec)
    return out


class IncrementalPareto:
    """Exact incremental nondominated set. Same dominance as ``pareto_preview``.

    Operationally-defined and plain records are separate fronts. Adding a
    record compares only against its own front.
    """

    def __init__(self) -> None:
        self.defined: list = []
        self.plain: list = []
        self.n_add = 0
        self.n_compared = 0
        self.seconds = 0.0

    def add(self, rec: dict) -> bool:
        self.n_add += 1
        op = bool((rec.get("preview") or {}).get("op_defined"))
        front = self.defined if op else self.plain
        t0 = time.perf_counter()
        for o in front:
            self.n_compared += 1
            if _dominates(o, rec, include_op=op):
                self.seconds += time.perf_counter() - t0
                return False
        kept = []
        for o in front:
            self.n_compared += 1
            if _dominates(rec, o, include_op=op):
                continue
            kept.append(o)
        kept.append(rec)
        if op:
            self.defined = kept
        else:
            self.plain = kept
        self.seconds += time.perf_counter() - t0
        return True

    def members(self) -> list:
        return list(self.defined) + list(self.plain)

    def ident_set(self) -> set:
        out = set()
        for rec in self.members():
            out.add(rec.get("ident") or rec.get("whole_game_identity") or rec.get("ordered_digest"))
        return out


def frontier_row(rec: dict) -> dict:
    p = rec.get("preview") or {}
    pre_g = int(rec.get("g") or 0)
    return {
        "ident": rec.get("ident") or rec.get("whole_game_identity"),
        "portfolio_cat": rec.get("portfolio_cat"),
        "pre": {
            "g": pre_g,
            "F": rec.get("foundations"),
            "fd": rec.get("face_down"),
            "legal": rec.get("legal_tableau") or p.get("pre_legal"),
            "empty": rec.get("empty_n"),
            "components": rec.get("visible_components") or rec.get("bonds"),
            "boundaries": rec.get("boundaries_total"),
            "best_suit": rec.get("best_ready_suit") or rec.get("best_suit"),
        },
        "post": compact_preview(p),
        "prep_delta_g": pre_g - F2_G,
        "legal_delta": None
        if p.get("legal_tableau") is None or p.get("pre_legal") is None
        else int(p["legal_tableau"]) - int(p["pre_legal"]),
        "boundary_delta": None
        if p.get("boundaries") is None or rec.get("boundaries_total") is None
        else int(p["boundaries"]) - int(rec["boundaries_total"]),
        "component_delta": None
        if p.get("visible_components") is None
        else int(p["visible_components"]) - int(rec.get("visible_components") or 0),
    }


def _insert_transition_categories(tops, rec, preview) -> None:
    """Frozen v0.66 ranking vectors. Not Pareto."""

    g = int(rec["g"])
    digest = rec.get("ordered_digest") or ""
    legal = int(preview.get("legal_tableau") or 0)
    bounds = int(preview.get("boundaries") or 0)
    comps = int(preview.get("visible_components") or 0)
    layers = int(preview.get("component_layers") or 0)
    fd = int(preview.get("face_down") or 0)
    if "post_deal_mobility" in tops:
        band = legal // 4
        tops["post_deal_mobility"].add((-band, g, -legal, digest), rec)
    if "post_deal_consolidation" in tops:
        tops["post_deal_consolidation"].add(
            (bounds // 4, comps // 4, layers // 2, fd, g, digest), rec
        )
    if preview.get("op_defined") and preview.get("op_key") and "post_deal_operational" in tops:
        tops["post_deal_operational"].add(tuple(preview["op_key"]) + (g, digest), rec)
    if "post_deal_reception" in tops:
        same = int(preview.get("same_suit") or 0)
        rank_ok = int(preview.get("rank_ok") or 0)
        mixed = int(preview.get("mixed") or 0)
        tops["post_deal_reception"].add((-(same + rank_ok), mixed, g, digest), rec)


def _materialise_pareto_top(tops, members) -> None:
    if "post_deal_pareto" not in tops:
        return
    for item in members:
        pd = (item.get("preview") or {}).get("post_digest") or item.get("ordered_digest") or ""
        tops["post_deal_pareto"].add((_n((item.get("preview") or {}).get("post_g")), pd), item)


class TransitionTrackerLegacy:
    """v0.68 bookkeeping: rebuilds full Pareto on every rows=1 visit.

    Kept as the measured reference. Not used by production search.
    Truncates the seen pool at 240 via a full Pareto slice of 120, so its
    Pareto set is not the exact nondominated set of all records.
    """

    def __init__(self) -> None:
        self.n_previewed = 0
        self.selected: list = []
        self.selected_cats: dict = {}
        self.pool: list = []
        self.seen_pool: set = set()
        self.displaced = 0
        self.pareto_calls = 0
        self.pareto_s = 0.0
        self.cat_s = 0.0
        self.n_pool_truncations = 0

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        preview = rec.get("preview") or {}
        if not preview.get("ok"):
            return
        if int(rec.get("stock_rows") or 0) != 1:
            return
        self.n_previewed += 1
        t_cat = time.perf_counter()
        _insert_transition_categories(tops, rec, preview)
        self.cat_s += time.perf_counter() - t_cat
        ident = rec.get("ident") or rec.get("ordered_digest") or ""
        t_p = time.perf_counter()
        if ident not in self.seen_pool:
            self.seen_pool.add(ident)
            self.pool.append(rec)
            if len(self.pool) > 240:
                self.n_pool_truncations += 1
                self.pareto_calls += 1
                self.pool = pareto_preview(self.pool)[:120] or self.pool[-120:]
                self.seen_pool = {r.get("ident") or r.get("ordered_digest") for r in self.pool}
        if "post_deal_pareto" in tops:
            self.pareto_calls += 1
            members = pareto_preview(self.pool)[:40]
            _materialise_pareto_top(tops, members)
        self.pareto_s += time.perf_counter() - t_p

    def finalize(self, tops, roots, min_root_g, rows=None) -> None:
        return

    def on_harvest(self, rows, picked, cat_counts, attached) -> None:
        if int(rows) != 1:
            return
        self.selected_cats = dict(cat_counts or {})
        self.selected = [frontier_row(rec) for rec in (attached or picked or [])]


class TransitionTracker:
    """v0.69 harvest bookkeeping: incremental exact Pareto, materialised once."""

    def __init__(self) -> None:
        self.n_previewed = 0
        self.selected: list = []
        self.selected_cats: dict = {}
        self.pool: list = []
        self.seen_pool: set = set()
        self.displaced = 0
        self.front = IncrementalPareto()
        self.pareto_calls = 0
        self.pareto_s = 0.0
        self.cat_s = 0.0
        self.finalize_s = 0.0
        self.n_ckpt_desc = 0
        self.f2_rows1: list = []
        self.ckpt_f2_rows1: list = []

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        preview = rec.get("preview") or {}
        if not preview.get("ok"):
            return
        if int(rec.get("stock_rows") or 0) != 1:
            return
        self.n_previewed += 1
        t_cat = time.perf_counter()
        _insert_transition_categories(tops, rec, preview)
        self.cat_s += time.perf_counter() - t_cat
        ident = rec.get("ident") or rec.get("ordered_digest") or ""
        if ident not in self.seen_pool:
            self.seen_pool.add(ident)
            self.pool.append(rec)
            self.front.add(rec)
        self.pareto_calls = self.front.n_add
        self.pareto_s = self.front.seconds
        if rec.get("from_incumbent_ckpt"):
            self.n_ckpt_desc += 1
        if int(rec.get("foundations") or 0) >= 2:
            snap = {
                "g": rec.get("g"),
                "fd": rec.get("face_down"),
                "F": rec.get("foundations"),
                "suits": rec.get("foundation_suits"),
                "legal": rec.get("legal_tableau"),
                "boundaries": rec.get("boundaries_total") or preview.get("boundaries"),
                "from_incumbent_ckpt": bool(rec.get("from_incumbent_ckpt")),
                "ident": ident,
                "preview": {
                    "rank_ok": preview.get("rank_ok"),
                    "same_suit": preview.get("same_suit"),
                    "mixed": preview.get("mixed"),
                    "legal_tableau": preview.get("legal_tableau"),
                },
            }
            self.f2_rows1.append(snap)
            if snap["from_incumbent_ckpt"]:
                self.ckpt_f2_rows1.append(snap)

    def finalize(self, tops, roots, min_root_g, rows=None) -> None:
        if rows is not None and int(rows) != 1:
            return
        t0 = time.perf_counter()
        _materialise_pareto_top(tops, self.front.members())
        self.finalize_s += time.perf_counter() - t0

    def on_harvest(self, rows, picked, cat_counts, attached) -> None:
        if int(rows) != 1:
            return
        self.selected_cats = dict(cat_counts or {})
        rows_out = []
        for rec in attached or picked or []:
            preview = rec.get("preview")
            digest = rec.get("ordered_digest")
            if digest and (not preview or not preview.get("ok") or preview.get("post") is None):
                try:
                    st = unpack_state(bytes.fromhex(digest))
                except Exception:
                    st = None
                if st is not None:
                    rec = dict(rec)
                    rec["preview"] = preview_next_deal(st, pre_g=int(rec.get("g") or 0), detail="full")
            rows_out.append(frontier_row(rec))
        self.selected = rows_out

    def stats(self) -> dict:
        return {
            "n_previewed": self.n_previewed,
            "pareto_calls": self.pareto_calls,
            "pareto_compared": self.front.n_compared,
            "pareto_s": self.pareto_s,
            "cat_s": self.cat_s,
            "finalize_s": self.finalize_s,
            "front_n": len(self.front.members()),
            "pool_n": len(self.pool),
            "n_ckpt_desc": self.n_ckpt_desc,
            "n_f2_rows1": len(self.f2_rows1),
            "n_ckpt_f2_rows1": len(self.ckpt_f2_rows1),
        }


def search_transition_continuation(
    *,
    opening: SpiderState,
    recon: dict,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
):
    tracker = TransitionTracker()
    result = search_operational_optimisation(
        opening=opening,
        initial_roots=[dict(recon["root"])],
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
        harvest_cats=TRANSITION_HARVEST_CATS,
        extra_track=tracker,
        enrich_fn=enrich_transition,
        on_harvest=tracker.on_harvest,
        finalize_track=tracker.finalize,
    )
    result.transition_tracker = tracker
    result.n_previewed = tracker.n_previewed
    result.transition_selected = tracker.selected
    result.transition_cats = tracker.selected_cats
    return result


def transition_share(counts: dict, width: int = PORTFOLIO_WIDTH) -> float:
    n = sum(int(counts.get(cat) or 0) for cat in TRANSITION_CATS)
    return 0.0 if width <= 0 else n / float(width)


def choose_transition_verdict(p: dict) -> Tuple[str, str]:
    if p.get("provenance_fail"):
        return (
            "FINAL_DEAL_TRANSITION_PROVENANCE_FAILURE",
            "exact F2 path/state could not be verified",
        )
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "FINAL_DEAL_TRANSITION_CONTRACT_FAILURE", "replay, identity or preview contract failed"
    inc = int(p.get("incumbent_g") or INCUMBENT_G)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "FINAL_DEAL_TRANSITION_COST_IMPROVED", f"solved at g={best}"
    f3 = ((p.get("foundations") or {}).get("cheap") or {}).get("3") or {}
    f4 = ((p.get("foundations") or {}).get("cheap") or {}).get("4") or {}
    f3g = f3.get("g")
    f4g = f4.get("g")
    useful = bool(p.get("useful_transition"))
    worse = bool(p.get("signal_invalid"))
    coverage = p.get("limit_mode") == "coverage"
    if worse:
        return (
            "FINAL_DEAL_TRANSITION_SIGNAL_INVALID",
            "preview-selected states converted worse than v0.65",
        )
    if useful and (
        (f3g is not None and int(f3g) < V065_F3)
        or (f4g is not None and int(f4g) < V065_F4)
        or bool(p.get("structure_improved"))
    ):
        return (
            "FINAL_DEAL_TRANSITION_IMPROVES_CONVERSION",
            "transition-aware roots improved F3/F4 or post-SD5 structure",
        )
    if coverage and useful:
        return (
            "FINAL_DEAL_TRANSITION_COVERAGE_LIMITED",
            "promising post-SD5 states remained when the envelope expired",
        )
    if not useful:
        return (
            "FINAL_DEAL_TRANSITION_NO_USEFUL_STATE",
            "rows=1 search found no economically better post-SD5 topology",
        )
    return (
        "FINAL_DEAL_TRANSITION_IMPROVES_CONVERSION",
        "transition quality improved without a cheaper terminal",
    )
