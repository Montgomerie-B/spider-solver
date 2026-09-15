"""v0.93 ceiling-187 calibration of the consequence evaluator.

Production ceiling remains 186. This module uses calibration ceiling 187
only to test whether CONTROL_187 is recognisable at its known completion
cost. Canonical 172 is not read. The known 187 route is audit/truth only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.f2_quality_frontier import apply_exact_final_deal
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW
from spider.long_horizon_f2_adjudication import identify_controls, load_v084_population
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import reconstruct_root_b
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

ROOT = Path(__file__).resolve().parents[2]
V074_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
PRODUCTION_CEILING = 186
CALIBRATION_CEILING = 187
FOCUSED_UNIQUE = 800_000
SNAPSHOT_S = (10.0, 30.0, 60.0, 120.0, 150.0, 300.0, 450.0, 600.0, 750.0)
KNOWN_ROUTE_GUIDANCE_USED = False
V092_CEILING186 = {"max_F": 3, "g": 156, "h": 27, "f": 183, "t_s": 150.0}


def resolve_control_187(opening=None) -> dict:
    opening = opening or opening_state()
    pop = load_v084_population()
    ctrls = identify_controls(pop)
    rec = ctrls.get("control_187")
    if not rec:
        return {"ok": False, "reason": "control_187_missing"}
    f2 = reconstruct_root_b(opening)
    if not f2.get("ok"):
        return {"ok": False, "reason": "root_b_failed", "raw": f2}
    post = apply_exact_final_deal(
        {"g": f2["g"], "ordered_digest": f2["ordered_digest"], "full_actions": f2.get("full_actions") or []}
    )
    st = unpack_state(bytes.fromhex(post["post_digest"]))
    tel = structural_telemetry(st)
    s = current_tableau_summary(st)
    h = int(post.get("assembly_h") or 0)
    f = int(post.get("assembly_f") or 0)
    ok = (
        post.get("ok")
        and int(f2["g"]) == 129
        and int(post["post_g"]) == 130
        and len(st.foundations) == 2
        and int(s["face_down"]) == 2
        and stock_rows(st) == 0
        and not st.can_deal()
        and h == 41
        and f == 171
        and post.get("post_digest") == rec.get("post_digest")
        and sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a)) == 5
    )
    post.update(tel)
    post["ok"] = bool(ok)
    post["name"] = "CONTROL_187"
    post["pre_g"] = 129
    post["g"] = 130
    post["ordered_digest"] = post.get("post_digest")
    post["whole_game_identity"] = post.get("ident")
    post["n_deal"] = sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a))
    post["slack_187"] = CALIBRATION_CEILING - f
    post["slack_186"] = PRODUCTION_CEILING - f
    post["foundation_suits"] = list(s["foundation_suits"])
    post["legal"] = len(tableau_actions(st))
    post["reason"] = None if ok else "control_187_mismatch"
    post["known_route_guidance_used"] = KNOWN_ROUTE_GUIDANCE_USED
    return post


def replay_autonomous_187(opening=None) -> dict:
    opening = opening or opening_state()
    if not V074_MOVES.exists():
        return {"ok": False, "reason": "missing_v074_moves"}
    acts = parse_moves_file(V074_MOVES)
    end = opening.clone()
    try:
        g = replay_actions(end, list(acts))
    except Exception as exc:
        return {"ok": False, "reason": f"illegal:{exc}"}
    n_deal = sum(1 for a in acts if is_deal(a))
    ok = (
        g == 187
        and n_deal == 5
        and end.is_solved()
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
        and stock_rows(end) == 0
    )
    return {
        "ok": bool(ok),
        "g": g,
        "n_deal": n_deal,
        "n_actions": len(acts),
        "solved": bool(end.is_solved()),
        "foundations": len(end.foundations),
        "reason": None if ok else "autonomous_187_replay_failed",
        "path": str(V074_MOVES.relative_to(ROOT)).replace("\\", "/"),
    }


def audit_known_187_bound(opening=None, *, ceiling: int = CALIBRATION_CEILING) -> dict:
    """Post-SD5 assembly bound along the known autonomous 187 route. Audit only."""

    opening = opening or opening_state()
    acts = parse_moves_file(V074_MOVES)
    st = opening.clone()
    g = 0
    n_deal = 0
    rows = []
    by_F: Dict[int, dict] = {}
    max_f = None
    max_rec = None
    min_slack = None
    violations = []
    for i, action in enumerate(acts):
        if is_deal(action):
            n_deal += 1
            g += st.deal()
        else:
            src, dst, k = action
            g += st.move(src, dst, k)
        if n_deal < 5 or stock_rows(st) != 0:
            continue
        h = int(stock_empty_assembly_h(st, int(g)))
        f = int(g) + h
        slack = int(ceiling) - f
        nF = len(st.foundations)
        rec = {
            "action_index": i,
            "g": int(g),
            "foundations": nF,
            "assembly_h": h,
            "assembly_f": f,
            "slack_187": slack,
            "ordered_digest": pack_state(st).hex(),
            "ident": pack_whole_game_identity(st).hex(),
        }
        rows.append(rec)
        prev = by_F.get(nF)
        if prev is None:
            by_F[nF] = {"max_f": f, "min_slack": slack, "min_g": int(g), "max_g": int(g), "n": 1}
        else:
            prev["max_f"] = max(int(prev["max_f"]), f)
            prev["min_slack"] = min(int(prev["min_slack"]), slack)
            prev["min_g"] = min(int(prev["min_g"]), int(g))
            prev["max_g"] = max(int(prev["max_g"]), int(g))
            prev["n"] += 1
        if max_f is None or f > int(max_f):
            max_f = f
            max_rec = rec
        if min_slack is None or slack < int(min_slack):
            min_slack = slack
        if f > int(ceiling):
            violations.append(rec)
    return {
        "ok": not violations,
        "n_post_sd5": len(rows),
        "max_f": max_f,
        "min_slack": min_slack,
        "max_f_state": max_rec,
        "by_F": {str(k): v for k, v in sorted(by_F.items())},
        "n_violations": len(violations),
        "first_violation": None if not violations else violations[0],
        "max_violation_over": None if not violations else max(int(r["assembly_f"]) - int(ceiling) for r in violations),
        "idents_by_F": _idents_by_F(rows),
        "known_route_guidance_used": False,
    }


def _idents_by_F(rows: List[dict]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    seen: Dict[str, set] = {}
    for rec in rows:
        k = str(rec["foundations"])
        ident = rec["ident"]
        bucket = seen.setdefault(k, set())
        if ident in bucket:
            continue
        bucket.add(ident)
        out.setdefault(k, []).append(ident)
    return out


def _tel_from_rec(rec: dict) -> dict:
    digest = rec.get("ordered_digest")
    extra = {}
    if digest:
        try:
            extra = structural_telemetry(unpack_state(bytes.fromhex(digest)))
        except Exception:
            extra = {}
    return extra


class CalibrationTracker:
    def __init__(self, start_F: int = 2, start_g: int = 130, *, ceiling: int = CALIBRATION_CEILING) -> None:
        self.t0 = time.perf_counter()
        self.ceiling = int(ceiling)
        self.start_F = int(start_F)
        self.start_g = int(start_g)
        self.max_F = int(start_F)
        self.cheap_F: Dict[int, dict] = {}
        self.first_F: Dict[int, dict] = {}
        self.minf_F: Dict[int, dict] = {}
        self.min_h: Optional[int] = None
        self.min_f: Optional[int] = None
        self.best_mobility: Optional[int] = None
        self.min_visible_runs: Optional[int] = None
        self.min_mixed: Optional[int] = None
        self.time_first_increase: Optional[float] = None
        self.snapshots: List[dict] = []
        self.terminal_snap: Optional[dict] = None
        self._next_i = 0
        self.n_seen = 0
        self.reached_idents: Dict[int, set] = {}

    def _blob(self, rec: dict, elapsed: float) -> dict:
        n = int(rec.get("foundations") or 0)
        g = int(rec.get("g") or 0)
        h = rec.get("assembly_h")
        f = rec.get("assembly_f")
        if f is None and h is not None:
            f = g + int(h)
        tel = _tel_from_rec(rec)
        ident = rec.get("ident") or rec.get("whole_game_identity")
        if rec.get("ordered_digest") and not ident:
            try:
                ident = pack_whole_game_identity(unpack_state(bytes.fromhex(rec["ordered_digest"]))).hex()
            except Exception:
                ident = None
        return {
            "g": g,
            "h": h,
            "f": f,
            "slack_187": None if f is None else int(self.ceiling) - int(f),
            "elapsed_s": elapsed,
            "legal": rec.get("legal_tableau") or rec.get("legal_mobility") or rec.get("legal"),
            "visible_runs": tel.get("visible_runs"),
            "mixed_suit_boundaries": tel.get("mixed_suit_boundaries"),
            "face_down": rec.get("face_down"),
            "empty_n": rec.get("empty_n"),
            "foundations": n,
            "ordered_digest": rec.get("ordered_digest"),
            "ident": ident,
            "full_actions": rec.get("full_actions"),
        }

    def _update(self, rec: dict) -> None:
        n = int(rec.get("foundations") or 0)
        g = int(rec.get("g") or 0)
        h = rec.get("assembly_h")
        f = rec.get("assembly_f")
        if f is None and h is not None:
            f = g + int(h)
        legal = rec.get("legal_tableau") or rec.get("legal_mobility") or rec.get("legal")
        elapsed = time.perf_counter() - self.t0
        self.n_seen += 1
        if n > self.max_F:
            self.max_F = n
        blob = self._blob(rec, elapsed)
        prev = self.cheap_F.get(n)
        if prev is None or g < int(prev["g"]):
            self.cheap_F[n] = blob
        if n not in self.first_F:
            self.first_F[n] = blob
        prev_f = self.minf_F.get(n)
        if blob.get("f") is not None and (prev_f is None or int(blob["f"]) < int(prev_f["f"])):
            self.minf_F[n] = blob
        if n > self.start_F and self.time_first_increase is None:
            self.time_first_increase = elapsed
        if h is not None:
            self.min_h = int(h) if self.min_h is None else min(self.min_h, int(h))
        if f is not None:
            self.min_f = int(f) if self.min_f is None else min(self.min_f, int(f))
        if legal is not None:
            self.best_mobility = int(legal) if self.best_mobility is None else max(self.best_mobility, int(legal))
        vr = blob.get("visible_runs")
        if vr is not None:
            self.min_visible_runs = int(vr) if self.min_visible_runs is None else min(self.min_visible_runs, int(vr))
        mx = blob.get("mixed_suit_boundaries")
        if mx is not None:
            self.min_mixed = int(mx) if self.min_mixed is None else min(self.min_mixed, int(mx))
        if blob.get("ident"):
            self.reached_idents.setdefault(n, set()).add(blob["ident"])

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

    def _capture(self, out, label: str) -> dict:
        elapsed = time.perf_counter() - self.t0
        return {
            "label": label,
            "elapsed_s": elapsed,
            "max_F": self.max_F,
            "cheap_F": {str(k): {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in sorted(self.cheap_F.items())},
            "first_F": {str(k): {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in sorted(self.first_F.items())},
            "minf_F": {str(k): {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in sorted(self.minf_F.items())},
            "min_h": self.min_h,
            "min_f": self.min_f,
            "best_mobility": self.best_mobility,
            "min_visible_runs": self.min_visible_runs,
            "min_mixed_suit_boundaries": self.min_mixed,
            "unique": getattr(out, "unique", None),
            "expanded": getattr(out, "expanded", None),
            "generated": getattr(out, "generated", None),
            "proof_prunes": getattr(out, "lower_bound_prunes", None),
            "proof_calls": getattr(out, "lower_bound_calls", None),
            "lane_exp": dict(getattr(out, "lane_exp", None) or {}),
            "solved": bool(getattr(out, "solved", False)),
            "solution_g": getattr(out, "solution_g", None),
            "counters_authoritative": False,
        }

    def finalize(self, out) -> None:
        end = self._capture(out, "end")
        end["counters_authoritative"] = True
        self.snapshots.append(end)


def search_control_187_ceiling187(
    *,
    opening=None,
    post: dict,
    max_unique: int = FOCUSED_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = CALIBRATION_CEILING,
):
    """Independent frozen search. Does not read the known 187 route."""

    if KNOWN_ROUTE_GUIDANCE_USED:
        raise RuntimeError("known route guidance must stay false")
    opening = opening or opening_state()
    root = {
        "g": int(post["g"]),
        "ordered_digest": post["ordered_digest"],
        "ident": post.get("whole_game_identity") or post.get("ident"),
        "whole_game_identity": post.get("whole_game_identity") or post.get("ident"),
        "full_actions": post.get("full_actions") or [],
        "stock_rows": 0,
        "foundations": int(post.get("foundations") or 2),
        "face_down": int(post.get("face_down") or 2),
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
        "lineage": ["CONTROL_187_calibration"],
        "portfolio_cat": "calibration_187",
    }
    tracker = CalibrationTracker(start_F=2, start_g=int(post["g"]), ceiling=int(cost_ceiling))
    start = {
        "g": int(post["g"]),
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
        "foundations": 2,
        "ordered_digest": post.get("ordered_digest"),
        "ident": post.get("whole_game_identity"),
        "legal_tableau": post.get("legal"),
        "face_down": post.get("face_down"),
        "empty_n": post.get("empty_n"),
        "full_actions": post.get("full_actions"),
    }
    tracker._update(start)
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": AUTONOMOUS_INCUMBENT_MW},
        cost_ceiling=int(cost_ceiling),
        incumbent_by_rows={},
        initial_roots=[root],
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=float(rss_abort_mb),
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


def retrospective_route_hits(tracker: CalibrationTracker, audit: dict) -> dict:
    known = audit.get("idents_by_F") or {}
    out = {}
    for n in range(3, 9):
        k = str(n)
        known_set = set(known.get(k) or [])
        reached = set(tracker.reached_idents.get(n) or [])
        cheap = tracker.cheap_F.get(n) or {}
        first = tracker.first_F.get(n) or {}
        hit_exact = bool(known_set & reached)
        other = n in tracker.cheap_F or n in tracker.first_F
        if hit_exact:
            status = "exact_known_route_state"
        elif other:
            status = "other_state_same_F"
        else:
            status = "neither"
        out[k] = {
            "status": status,
            "n_known": len(known_set),
            "n_reached": len(reached),
            "n_exact": len(known_set & reached),
            "cheap_ident": cheap.get("ident"),
            "first_ident": first.get("ident"),
        }
    return out


def choose_calibration_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and p.get("g_le_186") and not p.get("replay_ok")):
        return "CALIBRATION_187_CONTRACT_FAILURE", p.get("contract_reason") or "root/replay/accounting/firewall/search-contract failure"
    if p.get("bound_failure"):
        return "CALIBRATION_187_BOUND_FAILURE", p.get("bound_reason") or "known 187 route has post-SD5 g+h>187"
    if p.get("known_route_guidance_used"):
        return "CALIBRATION_187_CONTRACT_FAILURE", "known route leaked into search guidance"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) <= 186:
        return "CALIBRATION_187_COST_IMPROVED", f"solved at g={best}"
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) == 187:
        return "CALIBRATION_187_REDISCOVERED", f"independently rediscovered g=187 at t={p.get('time_to_terminal')}"
    max_f = int(p.get("max_foundations") or 0)
    if max_f >= 6:
        return "CALIBRATION_187_DEEP_RECOGNITION", f"maxF={max_f} under ceiling 187 without terminal"
    return "CALIBRATION_187_DEPTH_LIMITED", "known route passes bound audit, but independent ceiling-187 search remains insufficient after 900s"


def next_recommendation(verdict: str) -> str:
    if verdict == "CALIBRATION_187_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "CALIBRATION_187_REDISCOVERED":
        return "The evaluator is fundamentally correct but expensive. Make correct deep recognition cheaper using v0.93 timing data."
    if verdict == "CALIBRATION_187_DEEP_RECOGNITION":
        return "Use the earliest empirically reliable deep milestone as the next evaluator target."
    if verdict == "CALIBRATION_187_DEPTH_LIMITED":
        return "Optimise evaluator/search efficiency before generating more candidates."
    if verdict == "CALIBRATION_187_BOUND_FAILURE":
        return "Stop search development and repair the bound/accounting issue first."
    return "Do not promote; diagnose the contract."
