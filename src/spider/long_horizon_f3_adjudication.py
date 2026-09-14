"""v0.91 long-horizon adjudication of the v0.90 F3 basin.

Tactical F3→F4 probes generate candidates. Frozen global continuation
adjudicates whether any F4 is a cheaper eventual game. Canonical 172 is
not read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from spider.f3_quality_frontier import (
    G141_CONTROL,
    aggregate_f3_probes,
    bridge_loss,
    control_digests,
    is_known_closed,
    next_foundation_quality,
)
from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack, search_f4_portfolio
from spider.f172_mobility_focused_endgame import (
    V090_F3_SUMMARY_FORMATTING_FIX,
    format_v090_f3_summary,
)
from spider.new_family_f3_bridge import load_new_family_roots
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import load_prep_closed_table
from spider.proof_aware_tactical_bridge import (
    ExactHCache,
    inspect_stock_empty_root,
    interpret_continuation_stop,
    is_proof_viable,
    is_surplus,
    probe_proof_aware_target,
)
from spider.research_actions import stock_rows, tableau_actions
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, SEARCH_UNIQUE

ROOT = Path(__file__).resolve().parents[2]
V090_JSON = ROOT / "docs" / "research" / "f172_mobility_focused_endgame_v0_90.json"

STAGE_A_S = 30.0
STAGE_A_UNIQUE = 100_000
STAGE_B_S = 30.0
STAGE_B_N = 4
STAGE_B_UNIQUE = 100_000
TACTICAL_MAX_S = 360.0
STAGE_C_S = 90.0
STAGE_C_N = 4
STAGE_C_MAX_S = 360.0
STAGE_D_N = 2
PORTFOLIO_MAX = 4
TOTAL_S = SEARCH_TIME_S
G148_CONTROL = {"g": 148, "h": 29, "f": 177, "f4_f": 181, "f5_f": 186}

ROOT_SPECS = (
    {
        "name": "FIRST_LOWEST_F_F3",
        "json_path": ("first_F", "3"),
        "g": 138,
        "h": 35,
        "f": 173,
        "slack": 13,
        "face_down": 2,
        "empty_n": 1,
        "legal_tableau": 20,
    },
    {
        "name": "CHEAPEST_G_F3",
        "json_path": ("cheap_F", "3"),
        "g": 134,
        "h": 40,
        "f": 174,
        "slack": 12,
        "face_down": 2,
        "empty_n": 1,
        "legal_tableau": 13,
    },
)


def _get_path(data: dict, path: tuple) -> dict:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key) if key in cur else cur.get(str(key))
    return dict(cur) if isinstance(cur, dict) else {}


def gateway_class(f: int, ceiling: int = BRIDGE_CEILING) -> str:
    """Gateway labels only. Not a final measure of state value."""

    n = int(f)
    if n <= 184:
        return "STRONG_SURPLUS"
    if n <= 185:
        return "SURPLUS"
    if n <= int(ceiling):
        return "PROOF_VIABLE"
    return "RAW_NEXT_FOUNDATION"


def load_v090_f3(spec: dict, data: Optional[dict] = None) -> dict:
    """Load one F3 from v0.90 telemetry. Digest is not a policy constant."""

    data = data if data is not None else json.loads(V090_JSON.read_text(encoding="utf-8"))
    rec = _get_path(data, spec["json_path"])
    if not rec.get("ordered_digest"):
        raise KeyError(f"v0.90 {spec['name']} missing ordered_digest")
    g = int(rec.get("g") or 0)
    h = int(rec.get("h") or rec.get("assembly_h") or 0)
    f = int(rec.get("f") or rec.get("assembly_f") or 0)
    if g != spec["g"] or h != spec["h"] or f != spec["f"]:
        raise KeyError(f"v0.90 {spec['name']} metrics mismatch: {rec}")
    rec["calibration_name"] = spec["name"]
    rec["assembly_h"] = h
    rec["assembly_f"] = f
    rec["legal_tableau"] = int(rec.get("legal") or rec.get("legal_tableau") or 0)
    rec["elapsed_s"] = rec.get("elapsed_s")
    return rec


def load_v090_f3_roots() -> List[dict]:
    data = json.loads(V090_JSON.read_text(encoding="utf-8"))
    return [load_v090_f3(spec, data) for spec in ROOT_SPECS]


def v090_f3_summary_from_artefact(data: Optional[dict] = None) -> dict:
    data = data if data is not None else json.loads(V090_JSON.read_text(encoding="utf-8"))
    first = _get_path(data, ("first_F", "3"))
    cheap = _get_path(data, ("cheap_F", "3"))
    return format_v090_f3_summary(first, cheap)


def verify_v090_f3_root(spec: dict, rec: dict) -> dict:
    digest = rec.get("ordered_digest")
    if not digest:
        return {"ok": False, "reason": "missing_digest", "name": spec["name"]}
    st = unpack_state(bytes.fromhex(digest))
    inspect = inspect_stock_empty_root(digest, g=int(spec["g"]))
    s = current_tableau_summary(st)
    tel = structural_telemetry(st)
    expected = {
        "g": spec["g"],
        "foundations": 3,
        "assembly_h": spec["h"],
        "assembly_f": spec["f"],
        "slack": spec["slack"],
        "face_down": spec["face_down"],
        "empty_n": spec["empty_n"],
        "legal_tableau": spec["legal_tableau"],
        "stock_rows": 0,
        "can_deal": False,
    }
    mismatches = {k: {"expected": v, "got": inspect.get(k)} for k, v in expected.items() if inspect.get(k) != v}
    inspect["viable"] = is_proof_viable(int(inspect["g"]), int(inspect["assembly_h"]), BRIDGE_CEILING)
    inspect["visible_runs"] = tel["visible_runs"]
    inspect["visible_components"] = tel["visible_components"]
    inspect["mixed_suit_boundaries"] = tel["mixed_suit_boundaries"]
    inspect["ok"] = bool(not mismatches and inspect.get("stock_rows") == 0 and not inspect.get("can_deal") and inspect.get("viable"))
    inspect["reason"] = None if inspect["ok"] else "recompute_mismatch"
    inspect["mismatches"] = mismatches
    inspect["calibration_name"] = spec["name"]
    inspect["elapsed_s"] = rec.get("elapsed_s")
    inspect["ident"] = inspect.get("whole_game_identity") or pack_whole_game_identity(st).hex()
    inspect["tableau_legal"] = len(tableau_actions(st))
    inspect["summary_face_down"] = int(s["face_down"])
    return inspect


def historical_control_idents() -> dict:
    controls = control_digests()
    out = {
        "g141_digest": controls.get("g141"),
        "g141_ident": controls.get("g141_ident"),
        "g158_digest": controls.get("g158"),
        "g158_ident": controls.get("g158_ident"),
    }
    try:
        fam = load_new_family_roots()
        first = next((r for r in fam if int(r.get("g") or 0) == 148), None)
        if first and first.get("ordered_digest"):
            st = unpack_state(bytes.fromhex(first["ordered_digest"]))
            out["g148_digest"] = first["ordered_digest"]
            out["g148_ident"] = pack_whole_game_identity(st).hex()
    except Exception:
        out["g148_digest"] = None
        out["g148_ident"] = None
    return out


def verify_all_v090_f3_roots() -> dict:
    roots = load_v090_f3_roots()
    hist = historical_control_idents()
    closed = load_prep_closed_table()
    verified = []
    ok = True
    idents = []
    for spec, rec in zip(ROOT_SPECS, roots):
        info = verify_v090_f3_root(spec, rec)
        ident = info.get("ident")
        digest = info.get("ordered_digest")
        info["vs_g141_digest"] = digest != hist.get("g141_digest")
        info["vs_g141_ident"] = ident != hist.get("g141_ident")
        info["vs_g148_digest"] = digest != hist.get("g148_digest")
        info["vs_g148_ident"] = ident != hist.get("g148_ident")
        info["known_closed"] = bool(ident and is_known_closed(ident, int(info["g"]), closed))
        if info["known_closed"] or not info.get("ok"):
            ok = False
            if info["known_closed"] and info.get("ok"):
                info["ok"] = False
                info["reason"] = "matches_known_closed"
        if not (info["vs_g141_ident"] and info["vs_g148_ident"]):
            ok = False
            info["ok"] = False
            info["reason"] = "matches_historical_control"
        verified.append(info)
        idents.append(ident)
    distinct = len(set(idents)) == len(idents)
    if not distinct:
        ok = False
    return {
        "ok": bool(ok and distinct),
        "roots": verified,
        "n": len(verified),
        "distinct": distinct,
        "historical": hist,
        "v090_summary": v090_f3_summary_from_artefact(),
        "formatting_fix": V090_F3_SUMMARY_FORMATTING_FIX,
    }


def fresh_targets(inspect: dict) -> List[dict]:
    """Rank ready suits on the supplied state. No inherited target order."""

    st = unpack_state(bytes.fromhex(inspect["ordered_digest"]))
    ranked = rank_ready_suits(st, g=int(inspect["g"]))
    ready = set(ranked.get("ready_suits") or [])
    out = []
    for rec in inspect.get("remaining_targets") or []:
        if rec.get("suit") in ready:
            out.append(dict(rec))
    if not out:
        out = [dict(r) for r in (inspect.get("remaining_targets") or [])[:4]]
    return out[:4]


def promote_stage_b(probes: Sequence[dict], *, k: int = STAGE_B_N) -> List[dict]:
    def key(p):
        viable = int(p.get("viable_count") or 0) > 0
        return (
            0 if viable else 1,
            int(p.get("best_viable_f") if p.get("best_viable_f") is not None else 10**9),
            -int(p.get("max_viable_slack") if p.get("max_viable_slack") is not None else p.get("max_slack") or -10**9),
            int(p.get("min_h_viable") if p.get("min_h_viable") is not None else 10**9),
            int(p.get("min_cover") if p.get("min_cover") is not None else 10**9),
            p.get("root_name") or "",
            p.get("suit") or "",
        )

    return sorted(probes, key=key)[: int(k)]


def classify_f4(rec: dict) -> str:
    return gateway_class(int(rec.get("assembly_f") or rec.get("f") or 10**9))


def select_adjudication_portfolio(aggs: Sequence[dict], closed: dict, *, hard_max: int = PORTFOLIO_MAX) -> List[dict]:
    pool = []
    seen: Set[str] = set()
    for agg in aggs:
        for rec in agg.get("viable_terminals") or []:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            if not ident or ident in seen:
                continue
            if not is_proof_viable(int(rec["g"]), int(rec["assembly_h"]), BRIDGE_CEILING):
                continue
            item = dict(rec)
            item["ident"] = ident
            item["root_name"] = agg.get("calibration_name")
            item["root_g"] = agg.get("root_g")
            item["root_h"] = agg.get("root_h")
            item["root_f"] = agg.get("root_f")
            item["gateway"] = classify_f4(item)
            item["closed"] = bool(is_known_closed(ident, int(item["g"]), closed))
            if item["closed"]:
                item["closed_tag"] = "KNOWN_CLOSED_STATE"
            else:
                prev = closed.get(ident)
                if prev is not None and int(item["g"]) < int(prev["g"]):
                    item["reopened"] = True
            seen.add(ident)
            pool.append(item)
    live = [r for r in pool if not r.get("closed")]
    picks: List[dict] = []
    taken: Set[str] = set()

    def take(rec, role):
        if rec is None:
            return
        ident = rec.get("ident")
        if not ident or ident in taken:
            return
        taken.add(ident)
        item = dict(rec)
        item["portfolio_role"] = role
        picks.append(item)

    by_root = {}
    for rec in live:
        by_root.setdefault(rec.get("root_name"), []).append(rec)
    for name in ("FIRST_LOWEST_F_F3", "CHEAPEST_G_F3"):
        rows = by_root.get(name) or []
        if rows:
            take(min(rows, key=lambda r: (int(r["assembly_f"]), int(r["g"]))), f"best_{name}")
    if live:
        take(min(live, key=lambda r: (int(r["assembly_f"]), int(r["g"]))), "lowest_f")
        take(min(live, key=lambda r: (int(r["assembly_h"]), int(r["g"]))), "lowest_h")
        take(max(live, key=lambda r: (int(r.get("legal_tableau") or 0), -int(r["assembly_f"]))), "highest_mobility")
    for rec in sorted(live, key=lambda r: (int(r["assembly_f"]), int(r["g"]), r.get("ident") or "")):
        if len(picks) >= int(hard_max):
            break
        take(rec, "fill")
    return picks[: int(hard_max)]


def stage_c_key(sig: dict) -> tuple:
    """Downstream outcome first. Immediate F4 f is not primary."""

    solved = 0 if sig.get("solved") else 1
    term = int(sig["solution_g"]) if sig.get("solved") and sig.get("solution_g") is not None else 10**9
    max_f = int(sig.get("max_F") or 0)
    deep = sig.get("deepest") or {}
    f_at = int(deep["f"]) if deep.get("f") is not None else 10**9
    slack_at = int(deep["slack"]) if deep.get("slack") is not None else -10**9
    g_at = int(deep["g"]) if deep.get("g") is not None else 10**9
    dead = 1 if sig.get("status") == "LONG_HORIZON_DEAD" else 0
    h_at = int(deep["h"]) if deep.get("h") is not None else 10**9
    mob = int(sig.get("best_mobility") or 0)
    return (solved, term, -max_f, f_at, -slack_at, g_at, dead, h_at, -mob)


def classify_stage_c(res, rec: dict) -> dict:
    tracker = getattr(res, "snapshot_tracker", None)
    max_f = int(getattr(tracker, "max_F", rec.get("foundations") or 4) or 0)
    cheap = dict(getattr(tracker, "cheap_F", {}) or {})
    deep = cheap.get(max_f) or cheap.get(str(max_f)) or {}
    if not deep.get("g"):
        deep = {
            "g": rec.get("g"),
            "h": rec.get("assembly_h"),
            "f": rec.get("assembly_f"),
            "slack": rec.get("slack"),
            "ordered_digest": rec.get("ordered_digest"),
            "full_actions": rec.get("full_actions"),
        }
    interp = interpret_continuation_stop(res.stop_reason, solved=bool(res.solved))
    f_at = deep.get("f")
    viable_deep = f_at is not None and int(f_at) <= BRIDGE_CEILING
    if interp.get("exhausted") and not res.solved:
        status = "LONG_HORIZON_DEAD"
    elif viable_deep and interp.get("resource_limited"):
        status = "LONG_HORIZON_LIVE"
    elif viable_deep and max_f >= 5:
        status = "LONG_HORIZON_LIVE"
    elif interp.get("resource_limited"):
        status = "LONG_HORIZON_LIVE"
    else:
        status = "LONG_HORIZON_DEAD"
    traj = []
    for n in range(3, 9):
        row = cheap.get(n) or cheap.get(str(n))
        if not row:
            continue
        traj.append(
            {
                "F": n,
                "g": row.get("g"),
                "h": row.get("h"),
                "f": row.get("f"),
                "slack": row.get("slack") if row.get("slack") is not None else (
                    None if row.get("f") is None else assembly_slack(BRIDGE_CEILING, int(row["f"]))
                ),
            }
        )
    return {
        "source_f3": rec.get("root_name"),
        "f4_g": rec.get("g"),
        "f4_h": rec.get("assembly_h"),
        "f4_f": rec.get("assembly_f"),
        "f4_slack": rec.get("slack"),
        "f4_legal": rec.get("legal_tableau"),
        "target": rec.get("tactical_target"),
        "max_F": max_f,
        "deepest": {
            "F": max_f,
            "g": deep.get("g"),
            "h": deep.get("h"),
            "f": deep.get("f"),
            "slack": None if deep.get("f") is None else assembly_slack(BRIDGE_CEILING, int(deep["f"])),
            "ordered_digest": deep.get("ordered_digest"),
            "full_actions": deep.get("full_actions"),
        },
        "stop_reason": res.stop_reason,
        "exhausted": bool(interp.get("exhausted")),
        "resource_limited": bool(interp.get("resource_limited")),
        "status": status,
        "solved": bool(res.solved),
        "solution_g": res.solution_g,
        "unique": res.unique,
        "expanded": res.expanded,
        "elapsed_s": res.elapsed_s,
        "best_mobility": getattr(tracker, "best_mobility", None),
        "trajectory": traj,
        "ident": rec.get("ident"),
        "ordered_digest": rec.get("ordered_digest"),
        "full_actions": rec.get("full_actions"),
        "root_g": rec.get("root_g"),
        "portfolio_role": rec.get("portfolio_role"),
    }


def select_stage_d(scorecard: Sequence[dict], *, k: int = STAGE_D_N) -> List[dict]:
    live = [s for s in scorecard if s.get("status") == "LONG_HORIZON_LIVE" and not s.get("exhausted")]
    live.sort(key=stage_c_key)
    return live[: int(k)]


def choose_long_horizon_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "LONG_HORIZON_F3_CONTRACT_FAILURE", p.get("contract_reason") or "state/proof/identity/accounting/firewall/reporting failure"
    if p.get("cross_wired"):
        return "LONG_HORIZON_F3_CONTRACT_FAILURE", "v0.90 first/cheap F3 times were cross-wired in the live summary helper"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "LONG_HORIZON_F3_COST_IMPROVED", f"solved at g={best}"
    max_f = int(p.get("max_foundations") or 0)
    deepest_f = p.get("deepest_f")
    deepest_slack = p.get("deepest_slack")
    n_viable = int(p.get("n_viable_f4") or 0)
    n_live = int(p.get("n_live") or 0)
    n_dead = int(p.get("n_dead") or 0)
    if max_f >= 6 and deepest_f is not None and int(deepest_f) <= BRIDGE_CEILING:
        return "LONG_HORIZON_F3_DEEP_ENDGAME", f"maxF={max_f} deepest_f={deepest_f}"
    if max_f >= 5 and deepest_slack is not None and int(deepest_slack) >= 1 and n_live:
        return "LONG_HORIZON_F3_LIVE_F5", f"F5 f={deepest_f} slack={deepest_slack} live={n_live}"
    if n_viable == 0:
        if p.get("tactical_limited"):
            return "LONG_HORIZON_F3_SEARCH_LIMITED", "no proof-viable F4; tactical probes were resource-limited"
        return "LONG_HORIZON_F3_NO_CONVERSION", "no proof-viable F4 generated"
    if n_live and max_f >= 5:
        return "LONG_HORIZON_F3_LIVE_F5", f"live F5+ resource-limited maxF={max_f}"
    if n_live and p.get("stage_d_limited"):
        return "LONG_HORIZON_F3_SEARCH_LIMITED", "deep candidates remain resource-limited before a consequence judgment"
    if n_viable and n_dead and not n_live:
        return "LONG_HORIZON_F3_EXHAUSTED", "generated F4/F5 candidates exhausted without a solution"
    if n_viable and max_f <= 4:
        return "LONG_HORIZON_F3_F4_ONLY", "new F4 exists but downstream adjudication shows no durable deeper advantage"
    if p.get("search_limited"):
        return "LONG_HORIZON_F3_SEARCH_LIMITED", "important searches remain resource-limited"
    return "LONG_HORIZON_F3_F4_ONLY", "F4 generated; no deeper durable conversion"


def next_recommendation(verdict: str) -> str:
    if verdict == "LONG_HORIZON_F3_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict in ("LONG_HORIZON_F3_DEEP_ENDGAME", "LONG_HORIZON_F3_LIVE_F5"):
        return "Continue from the deepest proof-live state of the winning lineage."
    if verdict == "LONG_HORIZON_F3_SEARCH_LIMITED":
        return "Keep the live deep candidate as the focused control; do not widen wall time."
    if verdict in ("LONG_HORIZON_F3_F4_ONLY", "LONG_HORIZON_F3_EXHAUSTED", "LONG_HORIZON_F3_NO_CONVERSION"):
        return (
            "Stop mining this prepared-root family. Move upstream to strategic rows=1 F1 preparation "
            "→ tactical F2 cash-out → SD5 → long-horizon evaluation."
        )
    return "Do not promote; diagnose the contract."
