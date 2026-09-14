"""v0.90 focused stock-empty search from the v0.89 f172 mobility root.

One exact post-SD5 root. Frozen global policy. Canonical 172 is not read.
Closed-state skip is omitted so the campaign matches v0.74/v0.85 TT semantics.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.exhaustive_post_f2_prep import attach_full_actions
from spider.f3_quality_frontier import is_known_closed
from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack
from spider.g128_focused_endgame import reconstruct_g123
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW
from spider.metrics import replay_actions
from spider.operational_policy import OP_HARVEST_CATS, operational_lane_keys, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import (
    MAX_DG,
    PREP_LANES,
    PREP_S,
    PREP_UNIQUE,
    harvest_preparation,
    immediate_deal_control,
    load_prep_closed_table,
    reconstruct_root_a,
    reconstruct_root_b,
)
from spider.proof_aware_tactical_bridge import is_proof_viable
from spider.research_actions import apply_action, as_actions, dump_actions, is_deal, step_cost, stock_rows, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, SEARCH_UNIQUE

ROOT = Path(__file__).resolve().parents[2]
V089_JSON = ROOT / "docs" / "research" / "exhaustive_post_f2_prep_v0_89.json"
FOCUSED_CEILING = BRIDGE_CEILING
FOCUSED_UNIQUE = 800_000
SNAPSHOT_S = (5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
CLOSED_GUARD = False
V090_F3_SUMMARY_FORMATTING_FIX = True
V085_ROOT_A = {
    "post_g": 129,
    "h": 42,
    "f": 171,
    "legal": 5,
    "first_F3_g": 148,
    "first_F3_h": 29,
    "first_F3_f": 177,
    "first_F3_t": 5.3,
    "cheapest_F3_g": 141,
    "cheapest_F3_h": 33,
    "cheapest_F3_f": 174,
    "max_F": 3,
}
V074_FOCUSED = {
    "root_post_g": 130,
    "root_h": 41,
    "root_f": 171,
    "legal": 5,
    "terminal": 187,
    "F3": {"g": 156, "h": 27, "f": 183},
    "F4": {"g": 175, "h": 13, "f": 188},
    "F5": {"g": 180, "h": 9, "f": 189},
    "F6": {"g": 183, "h": 4, "f": 187},
    "F7": {"g": 186, "h": 1, "f": 187},
    "F8": {"g": 187, "h": 0, "f": 187},
}


def format_v090_f3_summary(first: dict, cheap: dict) -> dict:
    """Keep first-F3 economics/time separate from cheapest-g F3. Do not cross-wire."""

    def one(rec: dict) -> dict:
        rec = rec or {}
        return {
            "g": rec.get("g"),
            "h": rec.get("h") or rec.get("assembly_h"),
            "f": rec.get("f") or rec.get("assembly_f"),
            "elapsed_s": rec.get("elapsed_s"),
        }

    first_s = one(first)
    cheap_s = one(cheap)
    cross = (
        first_s.get("g") is not None
        and cheap_s.get("g") is not None
        and int(first_s["g"]) != int(cheap_s["g"])
        and first_s.get("elapsed_s") is not None
        and cheap_s.get("elapsed_s") is not None
        and first_s["elapsed_s"] == cheap_s["elapsed_s"]
    )
    return {
        "first_F3": first_s,
        "cheap_F3": cheap_s,
        "cross_wired": bool(cross),
        "fix": "V090_F3_SUMMARY_FORMATTING_FIX",
    }


def load_f172_mobility_candidate() -> dict:
    """Resolve the unique v0.89 f172_mobility post-Deal root from the artefact."""

    data = json.loads(V089_JSON.read_text(encoding="utf-8"))
    hits = [dict(r) for r in (data.get("selected") or []) if r.get("selection_role") == "f172_mobility"]
    if len(hits) != 1:
        return {"ok": False, "reason": "F172_MOBILITY_CONTRACT_FAILURE", "n_hits": len(hits)}
    rec = hits[0]
    ok = (
        rec.get("source") == "NEW_G128_F2"
        and int(rec.get("prep_delta_g") or -1) == 2
        and int(rec.get("post_g") or 0) == 131
        and int(rec.get("assembly_h") or 0) == 41
        and int(rec.get("assembly_f") or 0) == 172
        and int(rec.get("slack") or 0) == 14
        and int(rec.get("legal") or 0) == 10
        and int(rec.get("foundations") or 0) == 2
        and int(rec.get("face_down") or 0) == 2
        and rec.get("viable") is True
        and rec.get("post_digest")
        and rec.get("pre_digest")
        and rec.get("ident")
    )
    rec["ok"] = bool(ok)
    rec["reason"] = None if ok else "field_mismatch"
    rec["source_artefact"] = "docs/research/exhaustive_post_f2_prep_v0_89.json"
    return rec


def inspect_f172_post(digest: str, g: int = 131) -> dict:
    st = unpack_state(bytes.fromhex(digest))
    s = current_tableau_summary(st)
    tel = structural_telemetry(st)
    h = int(stock_empty_assembly_h(st, int(g)))
    f = int(g) + h
    return {
        "ok": (
            stock_rows(st) == 0
            and not st.can_deal()
            and len(st.foundations) == 2
            and int(s["face_down"]) == 2
            and h == 41
            and f == 172
            and len(tableau_actions(st)) == 10
            and int(g) == 131
        ),
        "g": int(g),
        "foundations": len(st.foundations),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal": len(tableau_actions(st)),
        "visible_runs": tel["visible_runs"],
        "visible_components": tel["visible_components"],
        "mixed_suit_boundaries": tel["mixed_suit_boundaries"],
        "assembly_h": h,
        "assembly_f": f,
        "slack": assembly_slack(FOCUSED_CEILING, f),
        "ordered_digest": pack_state(st).hex(),
        "ident": pack_whole_game_identity(st).hex(),
        "stock_rows": stock_rows(st),
        "can_deal": bool(st.can_deal()),
    }


def recover_predeal_path(opening, f2: dict, pre_digest: str, pre_g: int) -> dict:
    """Same frozen tableau-only prep search, stopped once the selected pre-Deal digest is hit."""

    prefix = as_actions(f2.get("full_actions") or [])
    found: Dict[str, int] = {}
    done = {"hit": False}

    def actions(st):
        if done["hit"]:
            return []
        return tableau_actions(st)

    def on_progress(kr, state, g, node_i):
        if pack_state(state).hex() != pre_digest:
            return
        if int(g) > int(pre_g):
            return
        prev = found.get("g")
        if prev is not None and int(prev) <= int(g):
            return
        found["node"] = int(node_i)
        found["g"] = int(g)
        if int(g) == int(pre_g):
            done["hit"] = True

    root = {
        "g": int(f2["g"]),
        "ordered_digest": f2["ordered_digest"],
        "symmetry_digest": f2.get("ident") or f2["ordered_digest"],
    }
    on_progress(None, unpack_state(bytes.fromhex(f2["ordered_digest"])), int(f2["g"]), 0)
    kr = run_search(
        [root],
        limits=SearchLimits(
            max_unique=int(PREP_UNIQUE),
            time_limit_s=float(PREP_S),
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=int(pre_g),
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=PREP_LANES,
        lane_keys_fn=operational_lane_keys,
        is_terminal=lambda st: pack_state(st).hex() == pre_digest,
        actions_fn=actions,
        on_progress=on_progress,
        lower_bound_fn=None,
    )
    if "node" not in found:
        return {"ok": False, "reason": "predeal_digest_not_reached", "stop_reason": kr.stop_reason, "unique": kr.unique}
    path = []
    if found["node"] and kr.nodes:
        path = kr.reconstruct(int(found["node"]))
    if any(is_deal(a) for a in path):
        return {"ok": False, "reason": "prep_path_contains_deal"}
    acts = prefix + path
    return {
        "ok": True,
        "full_actions": dump_actions(acts),
        "prep_actions": dump_actions(path),
        "n_prep": len(path),
        "found_g": found["g"],
        "stop_reason": kr.stop_reason,
        "unique": kr.unique,
        "elapsed_s": kr.elapsed_s,
    }


def reconstruct_f172_mobility_root(opening=None) -> dict:
    opening = opening or opening_state()
    cand = load_f172_mobility_candidate()
    if not cand.get("ok"):
        return {"ok": False, "verdict": "F172_MOBILITY_CONTRACT_FAILURE", "candidate": cand, "reason": cand.get("reason")}
    inspected = inspect_f172_post(cand["post_digest"], g=131)
    if not inspected.get("ok"):
        return {"ok": False, "verdict": "F172_MOBILITY_CONTRACT_FAILURE", "reason": "telemetry_mismatch", "inspected": inspected}
    if inspected["ordered_digest"] != cand["post_digest"] or inspected["ident"] != cand["ident"]:
        return {"ok": False, "verdict": "F172_MOBILITY_CONTRACT_FAILURE", "reason": "digest_ident_mismatch", "inspected": inspected}
    g123 = reconstruct_g123(opening)
    if not g123.get("ok"):
        return {"ok": False, "verdict": "F172_MOBILITY_CONTRACT_FAILURE", "reason": "g123_failed", "g123": g123}
    f2 = reconstruct_root_a(opening)
    if not f2.get("ok"):
        return {"ok": False, "verdict": "F172_MOBILITY_CONTRACT_FAILURE", "reason": "root_a_failed", "f2": f2}
    recovered = recover_predeal_path(opening, f2, cand["pre_digest"], int(cand["pre_g"]))
    if not recovered.get("ok"):
        ha = harvest_preparation(opening, f2, time_s=PREP_S, unique=PREP_UNIQUE, max_dg=MAX_DG, materialize_paths=False)
        rec = {
            "source": f2.get("name"),
            "node": None,
            "full_actions": None,
        }
        for item in ha.get("candidates") or []:
            if item.get("ordered_digest") == cand["pre_digest"] and int(item.get("g") or 0) == int(cand["pre_g"]):
                rec = item
                break
        if rec.get("node") is None:
            return {
                "ok": False,
                "verdict": "F172_MOBILITY_CONTRACT_FAILURE",
                "reason": recovered.get("reason") or "harvest_missed_predeal",
                "recovered": recovered,
            }
        attached = attach_full_actions(
            {
                "source": "NEW_G128_F2",
                "node": rec["node"],
                "pre_digest": cand["pre_digest"],
            },
            {"NEW_G128_F2": ha},
        )
        acts = as_actions(attached.get("full_actions") or [])
    else:
        acts = as_actions(recovered["full_actions"]) + [("deal",)]
    end = opening.clone()
    try:
        g = replay_actions(end, list(acts))
    except Exception as exc:
        return {"ok": False, "verdict": "F172_MOBILITY_CONTRACT_FAILURE", "reason": f"prefix_illegal:{exc}"}
    n_deal = sum(1 for a in acts if is_deal(a))
    post_digest = pack_state(end).hex()
    ident = pack_whole_game_identity(end).hex()
    h = int(stock_empty_assembly_h(end, int(g)))
    s = current_tableau_summary(end)
    tel = structural_telemetry(end)
    pre = opening.clone()
    pg = 0
    last_deal_i = max(i for i, a in enumerate(acts) if is_deal(a))
    for a in acts[:last_deal_i]:
        c = 1 if is_deal(a) else step_cost(pre, a)
        apply_action(pre, a)
        pg += int(c)
    pre_digest = pack_state(pre).hex()
    ok = (
        int(g) == 131
        and n_deal == 5
        and stock_rows(end) == 0
        and len(end.foundations) == 2
        and int(s["face_down"]) == 2
        and post_digest == cand["post_digest"]
        and ident == cand["ident"]
        and pre_digest == cand["pre_digest"]
        and int(pg) == 130
        and h == 41
        and int(g) + h == 172
        and len(tableau_actions(end)) == 10
        and assembly_slack(186, 172) == 14
    )
    return {
        "ok": bool(ok),
        "verdict": None if ok else "F172_MOBILITY_CONTRACT_FAILURE",
        "reason": None if ok else "prefix_replay_mismatch",
        "g123": {k: g123.get(k) for k in ("ok", "g", "foundations", "ordered_digest") if k in g123},
        "f2_g": f2.get("g"),
        "f2_digest": f2.get("ordered_digest"),
        "candidate": {k: cand.get(k) for k in cand if k != "full_actions"},
        "pre_g": 130,
        "pre_digest": pre_digest,
        "prep_delta_g": 2,
        "g": 131,
        "post_g": 131,
        "ordered_digest": post_digest,
        "whole_game_identity": ident,
        "ident": ident,
        "stock_rows": 0,
        "foundations": 2,
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_tableau": len(tableau_actions(end)),
        "legal": len(tableau_actions(end)),
        "visible_runs": tel["visible_runs"],
        "visible_components": tel["visible_components"],
        "mixed_suit_boundaries": tel["mixed_suit_boundaries"],
        "boundaries_total": tel["visible_runs"],
        "assembly_h": h,
        "assembly_f": int(g) + h,
        "slack": assembly_slack(186, int(g) + h),
        "n_deal": n_deal,
        "full_actions": dump_actions(acts),
        "recovery": {k: recovered.get(k) for k in ("ok", "n_prep", "stop_reason", "unique", "elapsed_s") if k in recovered},
        "autonomy": [
            "opening→g123 is machine incumbent ancestry",
            "g123→F2 is generic machine tactical cash-out (v0.84 NEW_G128_F2)",
            "the preparation state came from generic tableau-only v0.88 search",
            "the f172 root was selected by the frozen v0.89 generic mobility/Pareto evaluation",
            "SD5 is the real engine Deal",
            "no human/canonical move entered the route",
        ],
    }


def compare_root_identities(opening, post: dict) -> dict:
    a = reconstruct_root_a(opening)
    ctrl_a = immediate_deal_control(a)
    b = reconstruct_root_b(opening)
    ctrl_b = immediate_deal_control(b)

    def tel_of(digest, g):
        st = unpack_state(bytes.fromhex(digest))
        s = current_tableau_summary(st)
        t = structural_telemetry(st)
        return {
            "g": g,
            "h": None,
            "f": None,
            "ordered_digest": pack_state(st).hex(),
            "ident": pack_whole_game_identity(st).hex(),
            "legal": len(tableau_actions(st)),
            "empty_n": int(s["empty_n"]),
            "visible_runs": t["visible_runs"],
            "visible_components": t["visible_components"],
            "mixed_suit_boundaries": t["mixed_suit_boundaries"],
            "foundations": len(st.foundations),
            "face_down": int(s["face_down"]),
            "stock_rows": stock_rows(st),
        }

    new = {
        "g": post.get("g"),
        "h": post.get("assembly_h"),
        "f": post.get("assembly_f"),
        "ordered_digest": post.get("ordered_digest"),
        "ident": post.get("whole_game_identity") or post.get("ident"),
        "legal": post.get("legal_tableau") or post.get("legal"),
        "empty_n": post.get("empty_n"),
        "visible_runs": post.get("visible_runs"),
        "visible_components": post.get("visible_components"),
        "mixed_suit_boundaries": post.get("mixed_suit_boundaries"),
    }
    root_a = tel_of(ctrl_a["post_digest"], int(ctrl_a["post_g"]))
    root_a.update({"h": ctrl_a.get("assembly_h"), "f": ctrl_a.get("assembly_f"), "ok": ctrl_a.get("ok")})
    root_187 = tel_of(ctrl_b["post_digest"], int(ctrl_b["post_g"]))
    root_187.update({"h": ctrl_b.get("assembly_h"), "f": ctrl_b.get("assembly_f"), "ok": ctrl_b.get("ok")})
    return {
        "new": new,
        "root_a_immediate": root_a,
        "autonomous_187": root_187,
        "new_vs_a_digest": new.get("ordered_digest") != root_a.get("ordered_digest"),
        "new_vs_a_ident": new.get("ident") != root_a.get("ident"),
        "new_vs_187_digest": new.get("ordered_digest") != root_187.get("ordered_digest"),
        "new_vs_187_ident": new.get("ident") != root_187.get("ident"),
    }


def _tel_from_rec(rec: dict) -> dict:
    digest = rec.get("ordered_digest")
    extra = {}
    if digest:
        try:
            st = unpack_state(bytes.fromhex(digest))
            extra = structural_telemetry(st)
        except Exception:
            extra = {}
    return extra


class F172SnapshotTracker:
    def __init__(self, start_F: int = 2, start_g: int = 131) -> None:
        self.t0 = time.perf_counter()
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
        tel = _tel_from_rec(rec)
        return {
            "g": g,
            "h": h,
            "f": f,
            "slack": None if f is None else assembly_slack(FOCUSED_CEILING, int(f)),
            "elapsed_s": elapsed,
            "legal": rec.get("legal_tableau") or rec.get("legal_mobility") or rec.get("legal"),
            "visible_runs": tel.get("visible_runs"),
            "visible_components": tel.get("visible_components"),
            "mixed_suit_boundaries": tel.get("mixed_suit_boundaries"),
            "face_down": rec.get("face_down"),
            "empty_n": rec.get("empty_n"),
            "foundations": n,
            "ordered_digest": rec.get("ordered_digest"),
            "ident": rec.get("ident") or rec.get("whole_game_identity"),
            "full_actions": rec.get("full_actions"),
            "viable": None if h is None else is_proof_viable(g, int(h), FOCUSED_CEILING),
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
        blob = self._snap_rec(rec, elapsed)
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
            self.g_first_increase = g
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
            "counters_authoritative": False,
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
        end = self._capture(out, "end")
        end["counters_authoritative"] = True
        self.snapshots.append(end)


def search_f172_mobility_focused(
    *,
    opening=None,
    post: dict,
    max_unique: int = FOCUSED_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
):
    """One-root stock-empty continuation. No suffixes. No tactical layer. No closed-state skip."""

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
        "lineage": ["v089_f172_mobility"],
        "portfolio_cat": "f172_mobility_focused_root",
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
    }
    tracker = F172SnapshotTracker(start_F=int(post["foundations"]), start_g=int(post["g"]))
    start_blob = {
        "g": int(post["g"]),
        "h": post.get("assembly_h"),
        "f": post.get("assembly_f"),
        "slack": post.get("slack"),
        "elapsed_s": 0.0,
        "legal": post.get("legal_tableau") or post.get("legal"),
        "visible_runs": post.get("visible_runs"),
        "visible_components": post.get("visible_components"),
        "mixed_suit_boundaries": post.get("mixed_suit_boundaries"),
        "face_down": post.get("face_down"),
        "empty_n": post.get("empty_n"),
        "foundations": int(post["foundations"]),
        "ordered_digest": post["ordered_digest"],
        "ident": post.get("whole_game_identity"),
        "full_actions": post.get("full_actions"),
        "viable": True,
    }
    n0 = int(post["foundations"])
    tracker.cheap_F[n0] = dict(start_blob)
    tracker.first_F[n0] = dict(start_blob)
    tracker.minf_F[n0] = dict(start_blob)
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


def audit_known_closed(tracker: F172SnapshotTracker, table: Optional[dict] = None) -> dict:
    table = table if table is not None else load_prep_closed_table()
    hits = []
    reopen = []
    seen = set()
    pool = []
    for store in (tracker.cheap_F, tracker.first_F, tracker.minf_F):
        pool.extend(store.values())
    for rec in pool:
        digest = rec.get("ordered_digest")
        if not digest:
            continue
        try:
            st = unpack_state(bytes.fromhex(digest))
            ident = pack_whole_game_identity(st).hex()
        except Exception:
            continue
        if ident in seen:
            continue
        seen.add(ident)
        closed = table.get(ident)
        if closed is None:
            continue
        g = int(rec.get("g") or 0)
        item = {
            "ident": ident,
            "arrival_g": g,
            "closed_g": int(closed["g"]),
            "closed_source": closed.get("source"),
            "foundations": rec.get("foundations"),
            "f": rec.get("f"),
            "reopened": g < int(closed["g"]),
        }
        hits.append(item)
        if item["reopened"]:
            reopen.append(item)
    return {"n_hits": len(hits), "n_reopen": len(reopen), "hits": hits, "reopen": reopen}


def choose_f172_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F172_MOBILITY_CONTRACT_FAILURE", p.get("contract_reason") or "root/provenance/rules/accounting/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "F172_MOBILITY_COST_IMPROVED", f"solved at g={best}"
    max_f = int(p.get("max_foundations") or 0)
    cheap4 = ((p.get("cheap_F") or {}).get("4") or {})
    live_f4 = cheap4 and cheap4.get("f") is not None and int(cheap4["f"]) <= FOCUSED_CEILING
    if max_f >= 4 and (live_f4 or max_f >= 5):
        return "F172_MOBILITY_DEEP_ENDGAME", f"maxF={max_f} F4 f={cheap4.get('f')}"
    first3 = ((p.get("first_F") or {}).get("3") or {})
    cheap3 = ((p.get("cheap_F") or {}).get("3") or {})
    minf3 = ((p.get("minf_F") or {}).get("3") or {})
    t3 = first3.get("elapsed_s") if first3 else p.get("time_first_increase")
    if max_f >= 4 and not live_f4:
        return "F172_MOBILITY_SEARCH_LIMITED", f"reached F{max_f} but no proof-viable F4"
    if max_f == 3:
        like_a = (
            cheap3.get("g") == V085_ROOT_A["cheapest_F3_g"]
            and cheap3.get("f") == V085_ROOT_A["cheapest_F3_f"]
        ) or (
            first3.get("g") == V085_ROOT_A["first_F3_g"]
            and first3.get("f") == V085_ROOT_A["first_F3_f"]
        )
        strong = False
        if cheap3.get("f") is not None and int(cheap3["f"]) < int(V085_ROOT_A["cheapest_F3_f"]):
            strong = True
        if minf3.get("f") is not None and int(minf3["f"]) < int(V085_ROOT_A["cheapest_F3_f"]):
            strong = True
        if cheap3.get("g") is not None and int(cheap3["g"]) < int(V085_ROOT_A["cheapest_F3_g"]):
            strong = True
        if like_a and not strong:
            return "F172_MOBILITY_ROLLOUT_OVERSTATED", "focused F3 basin matches Root A; short-rollout mobility did not deepen conversion"
        if strong:
            summary = format_v090_f3_summary(first3, cheap3)
            a = summary["first_F3"]
            b = summary["cheap_F3"]
            return (
                "F172_MOBILITY_STRONG_F3_STALL",
                f"first F3 g={a.get('g')}/h={a.get('h')}/f={a.get('f')} t={a.get('elapsed_s')}; "
                f"cheap F3 g={b.get('g')}/h={b.get('h')}/f={b.get('f')} t={b.get('elapsed_s')}",
            )
        like_187 = cheap3.get("g") == V074_FOCUSED["F3"]["g"] or (
            cheap3.get("f") is not None and int(cheap3["f"]) >= int(V074_FOCUSED["F3"]["f"])
        )
        if like_187:
            return "F172_MOBILITY_MATCHES_187_CLASS", f"F3 g={cheap3.get('g')} f={cheap3.get('f')} comparable to 187-class"
        if p.get("stop_reason") == "time limit":
            return "F172_MOBILITY_SEARCH_LIMITED", "F3 frontier unresolved at 900s"
        return "F172_MOBILITY_ROLLOUT_OVERSTATED", "short-rollout F3 advantage did not produce a stronger basin"
    if max_f <= 2 and p.get("stop_reason") == "time limit":
        return "F172_MOBILITY_ROLLOUT_OVERSTATED", "did not reproduce the 10s F3 signal"
    if p.get("stop_reason") in ("time limit", "unique limit", "rss abort"):
        return "F172_MOBILITY_SEARCH_LIMITED", "promising frontier remains unresolved at 900s"
    return "F172_MOBILITY_MATCHES_187_CLASS", "long-run conversion comparable to the 187-class root"


def next_recommendation(verdict: str) -> str:
    if verdict == "F172_MOBILITY_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "F172_MOBILITY_DEEP_ENDGAME":
        return "Continue hierarchical decomposition from the strongest live later-foundation state of this exact root."
    if verdict == "F172_MOBILITY_STRONG_F3_STALL":
        return "Make the best novel F3 the next proof-aware tactical bridge root."
    if verdict == "F172_MOBILITY_SEARCH_LIMITED":
        return "Keep this exact post-SD5 root as the focused control; do not widen wall time."
    if verdict in ("F172_MOBILITY_ROLLOUT_OVERSTATED", "F172_MOBILITY_MATCHES_187_CLASS"):
        return "Move upstream to rows=1 before F2: strategic F1 preparation → tactical F2 cash-out → exact SD5."
    return "Do not promote; diagnose the contract."
