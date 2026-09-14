"""v0.85 focused stock-empty search from the v0.84 superior g128 F2.

One exact post-SD5 root. Frozen global policy. Canonical 172 is not read.
Closed-state skip is omitted so the campaign matches v0.74/v0.78 TT semantics.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.f2_quality_frontier import G128_POST, G187_POST, control_pre_f2_digests
from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack
from spider.g128_focused_endgame import reconstruct_g123, reconstruct_g128, reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW
from spider.metrics import replay_actions
from spider.operational_policy import OP_HARVEST_CATS, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import apply_action, as_actions, dump_actions, is_deal, step_cost, stock_rows, tableau_actions
from spider.state_convergence import V073_F2_DIGEST
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, SEARCH_UNIQUE

ROOT = Path(__file__).resolve().parents[2]
V084_JSON = ROOT / "docs" / "research" / "f2_quality_frontier_v0_84.json"
FOCUSED_CEILING = BRIDGE_CEILING
FOCUSED_UNIQUE = 800_000
SNAPSHOT_S = (5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
CLOSED_GUARD = False
V078_OLD = {
    "post_g": 129,
    "h": 43,
    "f": 172,
    "first_F3_g": 158,
    "first_F3_f": 180,
    "cheapest_F3_g": 141,
    "cheapest_F3_f": 174,
    "max_F": 3,
}
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


def load_superior_f2_candidate() -> dict:
    """Resolve the unique v0.84 lowest_f post-Deal root from the artefact."""

    data = json.loads(V084_JSON.read_text(encoding="utf-8"))
    hits = []
    for rec in data.get("selected") or []:
        if rec.get("selection_role") != "lowest_f":
            continue
        if (
            int(rec.get("pre_g") or 0) == 128
            and int(rec.get("post_g") or 0) == 129
            and int(rec.get("foundations") or 0) == 2
            and int(rec.get("face_down") or 0) == 2
            and int(rec.get("assembly_h") or 0) == 42
            and int(rec.get("assembly_f") or 0) == 171
            and int(rec.get("slack") or 0) == 15
            and int(rec.get("legal") or 0) == 5
            and int(rec.get("boundaries") or 0) == 46
            and rec.get("tactical_target") == "d"
            and rec.get("control_tag") in (None, "null")
        ):
            hits.append(dict(rec))
    if len(hits) != 1:
        return {
            "ok": False,
            "reason": "SUPERIOR_F2_ROOT_CONTRACT_FAILURE",
            "n_hits": len(hits),
        }
    rec = hits[0]
    controls = control_pre_f2_digests()
    if rec.get("pre_digest") == controls.get("g128"):
        return {"ok": False, "reason": "matches_v071_pre_digest", "record": rec}
    if rec.get("pre_digest") == V073_F2_DIGEST:
        return {"ok": False, "reason": "matches_187_pre_digest", "record": rec}
    actions = None
    for sig in list(data.get("stage_a") or []) + list(data.get("stage_b") or []):
        cheap = (sig.get("cheap_F") or {}).get("2") or (sig.get("cheap_F") or {}).get(2) or {}
        if cheap.get("ordered_digest") == rec.get("post_digest") and cheap.get("full_actions"):
            actions = cheap["full_actions"]
            break
    rec["full_actions"] = actions
    rec["ok"] = True
    rec["reason"] = None
    rec["has_ancestry"] = bool(actions)
    rec["source"] = "docs/research/f2_quality_frontier_v0_84.json"
    return rec


def reconstruct_superior_f2_root(opening=None) -> dict:
    opening = opening or opening_state()
    cand = load_superior_f2_candidate()
    if not cand.get("ok"):
        return {"ok": False, "verdict": "SUPERIOR_F2_CONTRACT_FAILURE", "candidate": cand}
    if not cand.get("full_actions"):
        return {"ok": False, "verdict": "SUPERIOR_F2_CONTRACT_FAILURE", "reason": "missing_stored_ancestry", "candidate": cand}
    g123 = reconstruct_g123(opening)
    if not g123.get("ok"):
        return {"ok": False, "verdict": "SUPERIOR_F2_CONTRACT_FAILURE", "g123": g123, "candidate": cand}
    acts = as_actions(cand["full_actions"])
    end = opening.clone()
    try:
        g = replay_actions(end, list(acts))
    except Exception as exc:
        return {"ok": False, "verdict": "SUPERIOR_F2_CONTRACT_FAILURE", "reason": f"prefix_illegal:{exc}"}
    n_deal = sum(1 for a in acts if is_deal(a))
    post_digest = pack_state(end).hex()
    ident = pack_whole_game_identity(end).hex()
    h = int(stock_empty_assembly_h(end, int(g)))
    s = current_tableau_summary(end)
    pre = opening.clone()
    pg = 0
    last_deal_i = max(i for i, a in enumerate(acts) if is_deal(a))
    for a in acts[:last_deal_i]:
        c = 1 if is_deal(a) else step_cost(pre, a)
        apply_action(pre, a)
        pg += int(c)
    pre_digest = pack_state(pre).hex()
    ok = (
        int(g) == 129
        and n_deal == 5
        and stock_rows(end) == 0
        and len(end.foundations) == 2
        and int(s["face_down"]) == 2
        and post_digest == cand["post_digest"]
        and pre_digest == cand["pre_digest"]
        and int(pg) == 128
        and h == 42
        and int(g) + h == 171
        and assembly_slack(186, 171) == 15
    )
    return {
        "ok": bool(ok),
        "verdict": None if ok else "SUPERIOR_F2_CONTRACT_FAILURE",
        "reason": None if ok else "prefix_replay_mismatch",
        "g123": {k: g123.get(k) for k in ("ok", "g", "foundations", "ordered_digest") if k in g123},
        "candidate": {k: cand.get(k) for k in cand if k != "full_actions"},
        "pre_g": 128,
        "pre_digest": pre_digest,
        "g": 129,
        "post_g": 129,
        "ordered_digest": post_digest,
        "whole_game_identity": ident,
        "stock_rows": 0,
        "foundations": 2,
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(end)),
        "boundaries_total": int(s.get("visible_runs") or 0),
        "assembly_h": h,
        "assembly_f": int(g) + h,
        "slack": assembly_slack(186, int(g) + h),
        "n_deal": n_deal,
        "full_actions": dump_actions(acts),
        "autonomy": [
            "opening→g123 is machine incumbent ancestry",
            "g123→g128 produced by generic v0.84 foundation cash-out",
            "target came from fresh operational readiness ranking",
            "final Deal is the real engine Deal",
            "no canonical or human moves contributed",
        ],
    }


def compare_root_identities(opening, post: dict) -> dict:
    old = reconstruct_g128_root(opening)
    from spider.final_deal_rollout import apply_sd5, control_pre_sd5

    ctrl = control_pre_sd5(opening)["ctrl_187"]
    p187 = apply_sd5(opening, ctrl)
    return {
        "new": {
            "g": post.get("g"),
            "h": post.get("assembly_h"),
            "f": post.get("assembly_f"),
            "ordered_digest": post.get("ordered_digest"),
            "ident": post.get("whole_game_identity"),
            "legal": post.get("legal_tableau"),
            "boundaries": post.get("boundaries_total"),
        },
        "old_g128": {
            "ok": old.get("ok"),
            "g": (old.get("post") or {}).get("g"),
            "h": (old.get("post") or {}).get("assembly_h"),
            "f": (old.get("post") or {}).get("assembly_f"),
            "ordered_digest": (old.get("post") or {}).get("ordered_digest"),
            "ident": (old.get("post") or {}).get("whole_game_identity"),
            "legal": (old.get("post") or {}).get("legal_tableau"),
            "pre_digest": (old.get("g128") or {}).get("ordered_digest"),
        },
        "autonomous_187": {
            "ok": p187.get("ok"),
            "g": p187.get("post_g"),
            "h": p187.get("assembly_h"),
            "f": p187.get("assembly_f"),
            "ordered_digest": p187.get("post_digest"),
            "ident": p187.get("whole_game_identity"),
            "legal": p187.get("legal"),
        },
        "new_vs_old_digest": post.get("ordered_digest") != (old.get("post") or {}).get("ordered_digest"),
        "new_vs_old_ident": post.get("whole_game_identity") != (old.get("post") or {}).get("whole_game_identity"),
        "new_vs_187_digest": post.get("ordered_digest") != p187.get("post_digest"),
        "new_vs_187_ident": post.get("whole_game_identity") != p187.get("whole_game_identity"),
        "pre_vs_v071": post.get("pre_digest") != (old.get("g128") or {}).get("ordered_digest"),
        "pre_vs_187_f2": post.get("pre_digest") != V073_F2_DIGEST,
    }


class SuperiorSnapshotTracker:
    def __init__(self, start_F: int = 2, start_g: int = 129) -> None:
        self.t0 = time.perf_counter()
        self.start_F = int(start_F)
        self.start_g = int(start_g)
        self.max_F = int(start_F)
        self.cheap_F: Dict[int, dict] = {}
        self.first_F: Dict[int, dict] = {}
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

    def _snap_rec(self, rec: dict, elapsed: float) -> dict:
        n = int(rec.get("foundations") or 0)
        g = int(rec.get("g") or 0)
        h = rec.get("assembly_h")
        f = rec.get("assembly_f")
        if f is None and h is not None:
            f = g + int(h)
        return {
            "g": g,
            "h": h,
            "f": f,
            "slack": None if f is None else assembly_slack(FOCUSED_CEILING, int(f)),
            "elapsed_s": elapsed,
            "legal": rec.get("legal_tableau") or rec.get("legal_mobility"),
            "boundaries": rec.get("boundaries_total"),
            "face_down": rec.get("face_down"),
            "empty_n": rec.get("empty_n"),
            "foundations": n,
            "ordered_digest": rec.get("ordered_digest"),
            "full_actions": rec.get("full_actions"),
        }

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
        blob = self._snap_rec(rec, elapsed)
        prev = self.cheap_F.get(n)
        if prev is None or g < int(prev["g"]):
            self.cheap_F[n] = blob
        if n not in self.first_F:
            self.first_F[n] = blob
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

    def _capture(self, out, label: str) -> dict:
        elapsed = time.perf_counter() - self.t0
        return {
            "label": label,
            "elapsed_s": elapsed,
            "max_F": self.max_F,
            "cheap_F": {str(k): {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in sorted(self.cheap_F.items())},
            "first_F": {str(k): {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in sorted(self.first_F.items())},
            "min_h": self.min_h,
            "min_f": self.min_f,
            "best_mobility": self.best_mobility,
            "min_boundaries": self.min_boundaries,
            "unique": getattr(out, "unique", None),
            "expanded": getattr(out, "expanded", None),
            "generated": getattr(out, "generated", None),
            "proof_prunes": getattr(out, "lower_bound_prunes", None),
            "proof_calls": getattr(out, "lower_bound_calls", None),
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


def search_superior_f2_focused(
    *,
    opening=None,
    post: dict,
    max_unique: int = FOCUSED_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
):
    """One-root stock-empty continuation. No suffixes. No tactical layer."""

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
        "lineage": ["v084_superior_f2"],
        "portfolio_cat": "superior_f2_focused_root",
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
    }
    tracker = SuperiorSnapshotTracker(start_F=int(post["foundations"]), start_g=int(post["g"]))
    tracker.cheap_F[int(post["foundations"])] = {
        "g": int(post["g"]),
        "h": post.get("assembly_h"),
        "f": post.get("assembly_f"),
        "slack": post.get("slack"),
        "elapsed_s": 0.0,
        "legal": post.get("legal_tableau"),
        "boundaries": post.get("boundaries_total"),
        "face_down": post.get("face_down"),
        "empty_n": post.get("empty_n"),
        "foundations": int(post["foundations"]),
        "ordered_digest": post["ordered_digest"],
        "full_actions": post.get("full_actions"),
    }
    tracker.first_F[int(post["foundations"])] = dict(tracker.cheap_F[int(post["foundations"])])
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace={"g": AUTONOMOUS_INCUMBENT_MW},
        cost_ceiling=FOCUSED_CEILING,
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


def choose_superior_f2_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "SUPERIOR_F2_CONTRACT_FAILURE", p.get("contract_reason") or "root/provenance/rules/accounting/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "SUPERIOR_F2_COST_IMPROVED", f"solved at g={best}"
    max_f = int(p.get("max_foundations") or 0)
    cheap3 = ((p.get("cheap_F") or {}).get("3") or {})
    first3 = ((p.get("first_F") or {}).get("3") or {})
    old_f3 = V078_OLD["first_F3_f"]
    if max_f >= 4:
        return "SUPERIOR_F2_DEEP_ENDGAME", f"maxF={max_f}"
    if max_f == 3:
        f3f = cheap3.get("f")
        f3g = cheap3.get("g")
        t3 = p.get("time_first_increase")
        better_f3 = (
            (f3f is not None and int(f3f) < int(old_f3))
            or (f3g is not None and int(f3g) < int(V078_OLD["first_F3_g"]))
            or (t3 is not None and float(t3) < 8.0)
        )
        if better_f3:
            return "SUPERIOR_F2_STRONG_F3_STALL", f"F3 g={f3g} f={f3f} t={t3}"
        if p.get("stop_reason") == "time limit":
            return "SUPERIOR_F2_SEARCH_LIMITED", "F3 frontier unresolved at 900s"
        return "SUPERIOR_F2_ROLLOUT_OVERSTATED", "short-rollout F3 advantage did not produce F4+"
    if max_f <= 2 and p.get("stop_reason") == "time limit":
        return "SUPERIOR_F2_ROLLOUT_OVERSTATED", "did not even hold the 10s F3 signal"
    if p.get("stop_reason") in ("time limit", "unique limit", "rss abort"):
        return "SUPERIOR_F2_SEARCH_LIMITED", "promising frontier remains unresolved at 900s"
    return "SUPERIOR_F2_MATCHES_187_CLASS", "long-run conversion comparable to 187-class"


def next_recommendation(verdict: str) -> str:
    if verdict == "SUPERIOR_F2_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "SUPERIOR_F2_DEEP_ENDGAME":
        return "Continue hierarchical analysis from the strongest live later-foundation state of this exact root."
    if verdict == "SUPERIOR_F2_STRONG_F3_STALL":
        return "Analyse this new F3 quality/bridge in isolation; do not mix it with the exhausted old g128 F3 family."
    if verdict == "SUPERIOR_F2_MATCHES_187_CLASS":
        return "Return to rows=1 and test pre-Deal preparation after F2 before SD5."
    if verdict == "SUPERIOR_F2_ROLLOUT_OVERSTATED":
        return "Return to rows=1 and test pre-Deal preparation after F2 before SD5."
    if verdict == "SUPERIOR_F2_SEARCH_LIMITED":
        return "Keep this exact post-SD5 root as the focused control; do not widen wall time."
    return "Do not promote; diagnose the contract."
