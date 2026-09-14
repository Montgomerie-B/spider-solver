"""v0.78 focused stock-empty search from the autonomous g128 tactical F2.

Does not change whole-game scheduling, rollout integration, or tactical
root selection. Canonical 172 is not read. Continuation-table suffixes
are not used during search.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.autonomous_continuations import build_autonomous_continuation_table
from spider.foundation_cashout import replay_to_stock_rows
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import (
    apply_action,
    as_actions,
    dump_actions,
    face_down_count,
    is_deal,
    stock_rows,
    tableau_actions,
)
from spider.state_convergence import V073_F2_DIGEST, V074_MOVES, foundation_progression
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, SEARCH_UNIQUE

ROOT = Path(__file__).resolve().parents[2]
CONT71 = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71_continuation.json"
V071_JSON = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71.json"
V076_JSON = ROOT / "docs" / "research" / "final_deal_bounded_rollout_v0_76.json"

FOCUSED_CEILING = 186
POST_SD5_G = 129
SNAPSHOT_S = (10.0, 30.0, 60.0, 120.0, 300.0)
V074_FOCUSED = {
    "root_post_g": 130,
    "root_h": 41,
    "root_f": 171,
    "terminal": 187,
    "F3": {"g": 156, "h": 27, "f": 183},
    "F4": {"g": 175, "h": 13, "f": 188},
    "F5": {"g": 180, "h": 9, "f": 189},
    "F6": {"g": 183, "h": 4, "f": 187},
    "F7": {"g": 186, "h": 1, "f": 187},
    "F8": {"g": 187, "h": 0, "f": 187},
}


def load_v071_continuation() -> dict:
    return json.loads(CONT71.read_text(encoding="utf-8"))


def expected_g123_digest() -> str:
    data = json.loads(V071_JSON.read_text(encoding="utf-8"))
    rec = data.get("tactical_root") or (data.get("path_trace") or {}).get("root") or {}
    digest = rec.get("ordered_digest")
    if not digest:
        raise KeyError("v0.71 g123 ordered_digest missing")
    return digest


def expected_v076_post_digest() -> Optional[str]:
    if not V076_JSON.exists():
        return None
    data = json.loads(V076_JSON.read_text(encoding="utf-8"))
    blobs = []
    for key in ("signatures", "roots", "selected", "ranking", "static_preview"):
        val = data.get(key)
        if isinstance(val, list):
            blobs.extend(val)
        elif isinstance(val, dict):
            blobs.extend(val.values() if val and isinstance(next(iter(val.values()), None), dict) else [])
    if isinstance(data.get("per_root"), dict):
        blobs.extend(data["per_root"].values())
    for rec in blobs:
        if not isinstance(rec, dict):
            continue
        if rec.get("role") == "tactical_f2_g128" and rec.get("post_digest"):
            return rec["post_digest"]
    planner = ((json.loads(V071_JSON.read_text(encoding="utf-8")).get("deal_preview_compare") or {}).get("planner") or {})
    return planner.get("post_digest")


def reconstruct_g123(opening=None) -> dict:
    """Replay the 187 incumbent to the rows=1 g=123 checkpoint."""

    opening = opening or opening_state()
    actions = parse_moves_file(V074_MOVES)
    ck = replay_to_stock_rows(opening, actions, target_rows=1)
    expected = expected_g123_digest()
    ok = (
        int(ck["g"]) == 123
        and int(ck["foundations"]) == 1
        and int(ck["face_down"]) == 2
        and int(ck["stock_rows"]) == 1
        and ck["ordered_digest"] == expected
    )
    ck["ok"] = ok
    ck["expected_digest"] = expected
    ck["digest_match"] = ck["ordered_digest"] == expected
    if not ok:
        ck["reason"] = "g123_digest_or_telemetry_mismatch"
    return ck


def reconstruct_g128(opening=None, g123: Optional[dict] = None) -> dict:
    """Apply stored v0.71 tactical actions. No search, no human moves."""

    opening = opening or opening_state()
    g123 = g123 or reconstruct_g123(opening)
    if not g123.get("ok"):
        return {"ok": False, "reason": "g123_failed", "g123": g123}
    cont = load_v071_continuation()
    tac = as_actions(cont.get("tactical_actions") or [])
    if len(tac) != 5 or any(is_deal(a) for a in tac):
        return {"ok": False, "reason": "tactical_actions_not_five_tableau", "n": len(tac)}
    prefix = as_actions(g123["prefix_actions"]) + list(tac)
    end = opening.clone()
    try:
        g = replay_actions(end, list(prefix))
    except Exception as exc:
        return {"ok": False, "reason": f"tactical_replay_illegal:{exc}"}
    digest = pack_state(end).hex()
    s = current_tableau_summary(end)
    ok = (
        int(g) == 128
        and digest == cont["terminal_digest"]
        and digest != V073_F2_DIGEST
        and stock_rows(end) == 1
        and len(end.foundations) == 2
        and int(s["face_down"]) == 2
        and not any(is_deal(a) for a in tac)
    )
    return {
        "ok": ok,
        "reason": None if ok else "g128_replay_mismatch",
        "g": int(g),
        "stock_rows": stock_rows(end),
        "foundations": len(end.foundations),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(end)),
        "ordered_digest": digest,
        "whole_game_identity": pack_whole_game_identity(end).hex(),
        "expected_digest": cont["terminal_digest"],
        "target_suit": cont.get("target_suit"),
        "tactical_actions": dump_actions(tac),
        "full_actions": dump_actions(prefix),
        "n_tactical": len(tac),
        "delta_g": int(g) - 123,
        "same_as_187_f2": digest == V073_F2_DIGEST,
    }


def apply_g128_deal(opening=None, g128: Optional[dict] = None) -> dict:
    """Exact engine Deal from the verified g128 F2. Absolute g is not reset."""

    opening = opening or opening_state()
    g128 = g128 or reconstruct_g128(opening)
    if not g128.get("ok"):
        return {"ok": False, "reason": "g128_failed", "g128": g128}
    state = opening.clone()
    g = replay_actions(state, as_actions(g128["full_actions"]))
    if stock_rows(state) != 1 or not state.can_deal():
        return {"ok": False, "reason": "cannot_deal", "g": g}
    pre_digest = pack_state(state).hex()
    deal_c = apply_action(state, ("deal",))
    g += int(deal_c)
    s = current_tableau_summary(state)
    h = int(stock_empty_assembly_h(state, g))
    hist = expected_v076_post_digest()
    post_digest = pack_state(state).hex()
    ident = pack_whole_game_identity(state).hex()
    ok = (
        int(deal_c) == 1
        and int(g) == POST_SD5_G
        and stock_rows(state) == 0
        and len(state.foundations) == 2
        and int(s["face_down"]) == 2
        and (hist is None or post_digest == hist)
    )
    return {
        "ok": ok,
        "reason": None if ok else "post_sd5_mismatch",
        "pre_g": 128,
        "pre_digest": pre_digest,
        "deal_cost": int(deal_c),
        "g": int(g),
        "post_g": int(g),
        "ordered_digest": post_digest,
        "whole_game_identity": ident,
        "stock_rows": stock_rows(state),
        "foundations": int(s["foundations"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(state)),
        "legal_mobility": len(tableau_actions(state)),
        "boundaries_total": int(s.get("visible_runs") or 0),
        "visible_components": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": int(g) + h,
        "full_actions": dump_actions(as_actions(g128["full_actions"]) + [("deal",)]),
        "v076_post_digest": hist,
        "v076_digest_match": None if hist is None else post_digest == hist,
        "v076_digest_available": hist is not None,
    }


def reconstruct_g128_root(opening=None) -> dict:
    """Full autonomous prefix: opening → g123 → g128 → SD5 g129."""

    opening = opening or opening_state()
    g123 = reconstruct_g123(opening)
    if not g123.get("ok"):
        return {"ok": False, "verdict": "G128_FOCUSED_ROOT_CONTRACT_FAILURE", "g123": g123}
    g128 = reconstruct_g128(opening, g123)
    if not g128.get("ok"):
        return {"ok": False, "verdict": "G128_FOCUSED_CONTRACT_FAILURE", "g123": g123, "g128": g128}
    post = apply_g128_deal(opening, g128)
    if not post.get("ok"):
        return {
            "ok": False,
            "verdict": "G128_FOCUSED_CONTRACT_FAILURE",
            "g123": g123,
            "g128": g128,
            "post": post,
        }
    return {"ok": True, "g123": g123, "g128": g128, "post": post}


class FocusedSnapshotTracker:
    """Time-series frontier capture. Does not seed search or change policy."""

    def __init__(self, start_F: int = 2, start_g: int = 129) -> None:
        self.t0 = time.perf_counter()
        self.start_F = int(start_F)
        self.start_g = int(start_g)
        self.max_F = int(start_F)
        self.cheap_F: Dict[int, dict] = {}
        self.min_h: Optional[int] = None
        self.min_f: Optional[int] = None
        self.best_mobility: Optional[int] = None
        self.min_boundaries: Optional[int] = None
        self.time_first_increase: Optional[float] = None
        self.g_first_increase: Optional[int] = None
        self.snapshots: List[dict] = []
        self.terminal_snap: Optional[dict] = None
        self._next_i = 0
        self.n_seen = 0

    def _update(self, rec: dict) -> None:
        n = int(rec.get("foundations") or 0)
        g = int(rec.get("g") or 0)
        h = rec.get("assembly_h")
        f = rec.get("assembly_f")
        if f is None and h is not None:
            f = g + int(h)
        legal = rec.get("legal_tableau") or rec.get("legal_mobility")
        b = rec.get("boundaries_total")
        elapsed = time.perf_counter() - self.t0
        self.n_seen += 1
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
                "face_down": rec.get("face_down"),
                "empty_n": rec.get("empty_n"),
                "foundations": n,
                "ordered_digest": rec.get("ordered_digest"),
            }
        if n > self.start_F and self.time_first_increase is None:
            self.time_first_increase = elapsed
            self.g_first_increase = g
        if h is not None:
            self.min_h = int(h) if self.min_h is None else min(self.min_h, int(h))
        if f is not None:
            self.min_f = int(f) if self.min_f is None else min(self.min_f, int(f))
        if legal is not None:
            self.best_mobility = (
                int(legal) if self.best_mobility is None else max(self.best_mobility, int(legal))
            )
        if b is not None:
            self.min_boundaries = (
                int(b) if self.min_boundaries is None else min(self.min_boundaries, int(b))
            )

    def _capture(self, out, label: str) -> dict:
        elapsed = time.perf_counter() - self.t0
        return {
            "label": label,
            "elapsed_s": elapsed,
            "max_F": self.max_F,
            "cheap_F": {str(k): dict(v) for k, v in sorted(self.cheap_F.items())},
            "min_h": self.min_h,
            "min_f": self.min_f,
            "best_mobility": self.best_mobility,
            "min_boundaries": self.min_boundaries,
            "unique": getattr(out, "unique", None),
            "expanded": getattr(out, "expanded", None),
            "generated": getattr(out, "generated", None),
            "proof_prunes": getattr(out, "lower_bound_prunes", None),
            "solved": bool(getattr(out, "solved", False)),
            "solution_g": getattr(out, "solution_g", None),
        }

    def extra_track(self, tops, rec, min_root_g, class_best) -> None:
        self._update(rec)

    def abort_when(self, out, rec) -> bool:
        self._update(rec)
        elapsed = time.perf_counter() - self.t0
        while self._next_i < len(SNAPSHOT_S) and elapsed >= SNAPSHOT_S[self._next_i]:
            mark = SNAPSHOT_S[self._next_i]
            self.snapshots.append(self._capture(out, f"t{int(mark)}"))
            self._next_i += 1
        if rec.get("solved") and self.terminal_snap is None:
            self.terminal_snap = self._capture(out, "terminal")
        return False

    def finalize(self, out) -> None:
        self.snapshots.append(self._capture(out, "end"))


def search_g128_focused(
    *,
    opening=None,
    post: dict,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
):
    """Fresh stock-empty continuation from the g128 post-SD5 root. No suffixes."""

    opening = opening or opening_state()
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
        "portfolio_cat": "g128_focused_root",
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
    }
    tracker = FocusedSnapshotTracker(start_F=int(post["foundations"]), start_g=int(post["g"]))
    tracker.cheap_F[int(post["foundations"])] = {
        "g": int(post["g"]),
        "h": post.get("assembly_h"),
        "f": post.get("assembly_f"),
        "elapsed_s": 0.0,
        "legal": post.get("legal_tableau"),
        "boundaries": post.get("boundaries_total"),
        "face_down": post.get("face_down"),
        "empty_n": post.get("empty_n"),
        "foundations": int(post["foundations"]),
        "ordered_digest": post["ordered_digest"],
    }
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": AUTONOMOUS_INCUMBENT_MW},
        cost_ceiling=FOCUSED_CEILING,
        incumbent_by_rows={},
        initial_roots=[root],
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        harvest_cats=OP_HARVEST_CATS,
        enrich_fn=enrich_assembly,
        lane_names=COMPLETION_LANES,
        keys_fn=strategic_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
        epoch_augment_fn=None,
        continuation_table=None,
        extra_track=tracker.extra_track,
        abort_when=tracker.abort_when,
    )
    tracker.finalize(result)
    result.snapshot_tracker = tracker
    return result


def continuation_impact(opening, actions: Sequence, total_g: int) -> dict:
    """Index the new route against the existing table. Search does not use it."""

    table = build_autonomous_continuation_table(opening, ceiling=FOCUSED_CEILING)
    state = opening.clone()
    g = 0
    n_states = 0
    would_add = 0
    would_improve = 0
    equal = 0
    worse = 0

    def consider() -> None:
        nonlocal n_states, would_add, would_improve, equal, worse
        digest = pack_state(state).hex()
        remaining = int(total_g) - int(g)
        n_states += 1
        prev = table.get(digest)
        if prev is None:
            would_add += 1
        elif remaining < prev.remaining_cost:
            would_improve += 1
        elif remaining == prev.remaining_cost:
            equal += 1
        else:
            worse += 1

    consider()
    for action in actions:
        from spider.research_actions import step_cost

        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        consider()
    return {
        "existing_entries": len(table.entries),
        "route_states": n_states,
        "would_add": would_add,
        "would_improve": would_improve,
        "equal_remaining": equal,
        "worse_remaining": worse,
        "used_during_search": False,
    }


def choose_g128_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "G128_FOCUSED_CONTRACT_FAILURE", p.get("contract_reason") or "prefix/root/replay/accounting/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    max_f = int(p.get("max_foundations") or 0)
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "G128_FOCUSED_COST_IMPROVED", f"solved at g={best}"
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) >= inc:
        return "G128_FOCUSED_SOLVES_NO_GAIN", f"solved at g={best} not below {inc}"
    snap30 = None
    for s in p.get("snapshots") or []:
        if s.get("label") == "t30":
            snap30 = s
    f3 = ((p.get("frontier") or {}) or {})
    cheap3 = None
    for rec in p.get("frontier_list") or []:
        if int(rec.get("F") or 0) == 3:
            cheap3 = rec
    if max_f >= 4:
        return "G128_FOCUSED_DEEPER_NO_TERMINAL", f"reached F{max_f} without a terminal"
    v076_f3 = 158
    if cheap3 and int(cheap3.get("g") or 10**9) > v076_f3 + 20 and max_f <= 3:
        return "G128_FOCUSED_ROLLOUT_OVERSTATED", "short-horizon F3 superiority did not survive concentrated search"
    if max_f >= 3 and not p.get("solved"):
        return "G128_FOCUSED_SEARCH_LIMITED", "F3+ frontier still live at 900s; terminal unresolved"
    _ = snap30
    _ = f3
    return "G128_FOCUSED_SEARCH_LIMITED", "concentrated search did not resolve terminal value"


def choose_rollout_assessment(p: dict) -> tuple:
    max_f = int(p.get("max_foundations") or 0)
    best = p.get("solution_g")
    cheap3 = next((r for r in (p.get("frontier_list") or []) if int(r.get("F") or 0) == 3), None)
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < 187:
        return "SHORT_ROLLOUT_PREDICTED_BETTER_ENDGAME", "g128 produced a complete route below 187"
    if p.get("solved") and p.get("replay_ok") and best is not None:
        return "SHORT_ROLLOUT_PREDICTED_SIMILAR_ENDGAME", f"g128 completed at g={best}"
    if max_f >= 6 or (
        cheap3 is not None and int(cheap3.get("g") or 10**9) <= 156 and max_f >= 4
    ):
        return "SHORT_ROLLOUT_PREDICTED_BETTER_ENDGAME", "long-run frontier stronger than the 187 focused control"
    if cheap3 is not None and int(cheap3.get("g") or 0) > 172 + 10 and max_f <= 3:
        return "SHORT_ROLLOUT_OVERSTATED_QUALITY", "30s F3 edge disappeared over long search"
    if max_f >= 3:
        return "LONG_SEARCH_STILL_INCONCLUSIVE", "no terminal; F3+ reached but conversion unresolved"
    return "SHORT_ROLLOUT_OVERSTATED_QUALITY", "did not convert beyond the short-horizon window"
