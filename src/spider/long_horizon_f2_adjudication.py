"""v0.92 long-horizon adjudication of the existing v0.84 F2 population.

Selects three novel F2s plus CONTROL_187. Frozen global stock-empty search
compares deep consequence. Canonical 172 is not read. The 187 suffix is not
used as search guidance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from spider.f2_quality_frontier import apply_exact_final_deal, load_f2_closed_table
from spider.f3_quality_frontier import is_known_closed
from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack, search_f4_portfolio
from spider.g128_focused_endgame import reconstruct_g123
from spider.metrics import replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import reconstruct_root_a, reconstruct_root_b
from spider.proof_aware_tactical_bridge import (
    interpret_continuation_stop,
    is_proof_viable,
    recover_digest_path,
)
from spider.research_actions import as_actions, dump_actions, is_deal, stock_rows, tableau_actions
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, SEARCH_UNIQUE

ROOT = Path(__file__).resolve().parents[2]
V084_JSON = ROOT / "docs" / "research" / "f2_quality_frontier_v0_84.json"
V089_JSON = ROOT / "docs" / "research" / "exhaustive_post_f2_prep_v0_89.json"

STAGE_A_S = 150.0
STAGE_A_N = 4
STAGE_A_UNIQUE = 300_000
STAGE_A_MAX_S = 600.0
CALIBRATION_EXTRA_S = 150.0
STAGE_B_N = 1
STAGE_B_MAX_S = 450.0
TOTAL_S = SEARCH_TIME_S


def load_v084_artefact() -> dict:
    return json.loads(V084_JSON.read_text(encoding="utf-8"))


def load_v084_population() -> dict:
    data = load_v084_artefact()
    posts: Dict[str, dict] = {}
    for src in ("pareto", "selected"):
        for rec in data.get(src) or []:
            d = rec.get("post_digest")
            if not d:
                continue
            item = dict(rec)
            item["_src"] = src
            prev = posts.get(d)
            if prev is None:
                posts[d] = item
            elif src == "pareto" and prev.get("_src") != "pareto":
                posts[d] = item
    return {
        "n_f2": int(data.get("n_f2") or 0),
        "n_unique_pre": int(data.get("n_unique_pre") or 0),
        "n_viable_post": int(data.get("n_viable_post") or 0),
        "n_persisted_post": len(posts),
        "n_pareto": len(data.get("pareto") or []),
        "policy_reads_canonical": bool(data.get("policy_reads_canonical")),
        "posts": list(posts.values()),
        "pareto": [dict(r) for r in (data.get("pareto") or [])],
        "selected": [dict(r) for r in (data.get("selected") or [])],
        "ok": int(data.get("n_f2") or 0) == 279 and int(data.get("n_unique_pre") or 0) == 279,
    }


def _f172_post_digest() -> Optional[str]:
    if not V089_JSON.exists():
        return None
    data = json.loads(V089_JSON.read_text(encoding="utf-8"))
    for rec in data.get("selected") or []:
        if rec.get("selection_role") == "f172_mobility":
            return rec.get("post_digest")
    return None


def identify_controls(pop: Optional[dict] = None) -> dict:
    pop = pop if pop is not None else load_v084_population()
    ctrl_187 = None
    ctrl_a = None
    v071 = None
    for rec in pop["posts"] + pop["pareto"] + pop["selected"]:
        tag = rec.get("control_tag")
        if tag == "g187_f2" and ctrl_187 is None:
            ctrl_187 = dict(rec)
            ctrl_187["name"] = "CONTROL_187"
        elif tag == "g128_tactical" and v071 is None:
            v071 = dict(rec)
            v071["name"] = "V071_G128"
        elif (
            tag is None
            and int(rec.get("pre_g") or 0) == 128
            and int(rec.get("post_g") or 0) == 129
            and int(rec.get("assembly_h") or 0) == 42
            and int(rec.get("assembly_f") or 0) == 171
            and ctrl_a is None
        ):
            ctrl_a = dict(rec)
            ctrl_a["name"] = "CONTROL_ROOT_A"
    ok = (
        ctrl_187 is not None
        and int(ctrl_187.get("pre_g") or 0) == 129
        and int(ctrl_187.get("post_g") or 0) == 130
        and int(ctrl_187.get("assembly_h") or 0) == 41
        and int(ctrl_187.get("assembly_f") or 0) == 171
        and ctrl_a is not None
    )
    return {"ok": ok, "control_187": ctrl_187, "control_root_a": ctrl_a, "v071_g128": v071}


def _post_ident(rec: dict) -> str:
    d = rec.get("post_digest")
    if not d:
        return ""
    try:
        return pack_whole_game_identity(unpack_state(bytes.fromhex(d))).hex()
    except Exception:
        return rec.get("ident") or rec.get("whole_game_identity") or d


def excluded_idents(controls: dict, closed: Optional[dict] = None) -> Set[str]:
    closed = closed if closed is not None else load_f2_closed_table()
    out = set(closed.keys())
    for rec in (controls.get("control_187"), controls.get("control_root_a"), controls.get("v071_g128")):
        if rec:
            out.add(_post_ident(rec))
            if rec.get("post_digest"):
                out.add(rec["post_digest"])
    d172 = _f172_post_digest()
    if d172:
        out.add(d172)
        try:
            out.add(pack_whole_game_identity(unpack_state(bytes.fromhex(d172))).hex())
        except Exception:
            pass
    return out


def eligible_pareto(pop: Optional[dict] = None, controls: Optional[dict] = None) -> List[dict]:
    pop = pop if pop is not None else load_v084_population()
    controls = controls if controls is not None else identify_controls(pop)
    banned = excluded_idents(controls)
    out = []
    seen: Set[str] = set()
    for rec in pop.get("pareto") or []:
        ident = _post_ident(rec)
        digest = rec.get("post_digest")
        if not digest or ident in seen:
            continue
        if ident in banned or digest in banned:
            continue
        if rec.get("control_tag") in ("g187_f2", "g128_tactical"):
            continue
        item = dict(rec)
        item["ident"] = ident
        st = unpack_state(bytes.fromhex(digest))
        tel = structural_telemetry(st)
        item["visible_runs"] = tel["visible_runs"]
        item["mixed_suit_boundaries"] = tel["mixed_suit_boundaries"]
        item["legal"] = int(item.get("legal") or len(tableau_actions(st)))
        out.append(item)
        seen.add(ident)
    return out


def select_novel_roots(pop: Optional[dict] = None) -> dict:
    """Freeze three novel F2s from Pareto. Does not read old rollout ranks."""

    pop = pop if pop is not None else load_v084_population()
    controls = identify_controls(pop)
    pool = eligible_pareto(pop, controls)
    if len(pool) < 3:
        return {"ok": False, "reason": "insufficient_eligible_pareto", "n": len(pool), "pool": pool}

    def digest(r):
        return r.get("post_digest") or ""

    novel_a = min(pool, key=lambda r: (int(r["assembly_h"]), int(r["assembly_f"]), int(r["post_g"]), digest(r)))
    rest = [r for r in pool if r["post_digest"] != novel_a["post_digest"]]
    novel_b = min(rest, key=lambda r: (int(r["post_g"]), int(r["assembly_f"]), int(r["assembly_h"]), digest(r)))
    rest_c = [r for r in rest if r["post_digest"] != novel_b["post_digest"]]
    novel_c = min(
        rest_c,
        key=lambda r: (
            -int(r.get("legal") or 0),
            int(r.get("mixed_suit_boundaries") or 10**9),
            int(r.get("visible_runs") or r.get("boundaries") or 10**9),
            int(r["assembly_f"]),
            digest(r),
        ),
    )
    for rec, name, reason in (
        (novel_a, "NOVEL_A", "lowest_h_then_f_then_g"),
        (novel_b, "NOVEL_B", "cheapest_distinct_g_f"),
        (novel_c, "NOVEL_C", "greatest_legal_then_fewer_mixed_runs"),
    ):
        rec["name"] = name
        rec["selection_reason"] = reason
        rec["selection_frozen"] = True
        rec["rollout_attached"] = False
    return {
        "ok": True,
        "n_pareto": len(pop.get("pareto") or []),
        "n_eligible": len(pool),
        "novel_a": novel_a,
        "novel_b": novel_b,
        "novel_c": novel_c,
        "controls": controls,
        "selection_frozen_before_rollout": True,
    }


def attach_historical_rollout(selection: dict) -> dict:
    """Attach v0.84 short-rollout labels only after identities are frozen."""

    data = load_v084_artefact()
    by_digest = {}
    for rec in data.get("selected") or []:
        if rec.get("post_digest"):
            by_digest[rec["post_digest"]] = rec
    stage = []
    for i, sa in enumerate(data.get("stage_a") or []):
        c2 = (sa.get("cheap_F") or {}).get("2") or {}
        d = c2.get("ordered_digest")
        if d:
            stage.append({"i": i, "role": sa.get("role"), "max_F": sa.get("max_F"), "min_f": sa.get("min_f"), "digest": d, "pre_g": sa.get("pre_g"), "post_g": sa.get("post_g")})
    out = dict(selection)
    labels = {}
    for key in ("novel_a", "novel_b", "novel_c"):
        rec = dict(out[key])
        d = rec.get("post_digest")
        sel = by_digest.get(d)
        hits = [s for s in stage if s.get("digest") == d]
        rec["rollout_attached"] = True
        rec["v084_selected"] = bool(sel)
        rec["v084_selection_role"] = None if not sel else sel.get("selection_role")
        rec["v084_stage_a"] = hits
        rec["v084_short_liked"] = bool(sel and sel.get("selection_role") not in (None, "fill"))
        labels[key] = {
            "selected": rec["v084_selected"],
            "role": rec["v084_selection_role"],
            "stage_a_roles": [h.get("role") for h in hits],
            "stage_a_maxF": [h.get("max_F") for h in hits],
        }
        out[key] = rec
    c187 = selection.get("controls", {}).get("control_187") or {}
    c187_d = c187.get("post_digest")
    labels["control_187"] = {
        "selected": any(r.get("post_digest") == c187_d for r in data.get("selected") or []),
        "role": next((r.get("selection_role") for r in data.get("selected") or [] if r.get("post_digest") == c187_d), None),
        "stage_a_roles": [h.get("role") for h in stage if h.get("digest") == c187_d],
        "stage_a_maxF": [h.get("max_F") for h in stage if h.get("digest") == c187_d],
    }
    out["historical_rollout"] = labels
    return out


def _ancestry_from_stage_a(post_digest: str) -> Optional[list]:
    data = load_v084_artefact()
    for sa in data.get("stage_a") or []:
        c2 = (sa.get("cheap_F") or {}).get("2") or {}
        if c2.get("ordered_digest") == post_digest and c2.get("full_actions"):
            return c2["full_actions"]
    return None


def verify_post_deal(rec: dict) -> dict:
    pre = {
        "g": int(rec["pre_g"]),
        "ordered_digest": rec["pre_digest"],
        "full_actions": rec.get("full_actions") or [],
        "control_tag": rec.get("control_tag"),
        "tactical_target": rec.get("tactical_target"),
    }
    post = apply_exact_final_deal(pre)
    ok = (
        post.get("ok")
        and post.get("post_digest") == rec.get("post_digest")
        and int(post.get("post_g") or 0) == int(rec.get("post_g") or 0)
        and int(post.get("assembly_h") or 0) == int(rec.get("assembly_h") or 0)
        and int(post.get("assembly_f") or 0) == int(rec.get("assembly_f") or 0)
        and post.get("foundations") == 2
        and post.get("stock_rows") == 0
        and not unpack_state(bytes.fromhex(post["post_digest"])).can_deal()
    )
    post["verify_ok"] = bool(ok)
    post["name"] = rec.get("name")
    post["selection_reason"] = rec.get("selection_reason")
    tel = structural_telemetry(unpack_state(bytes.fromhex(post["post_digest"]))) if post.get("post_digest") else {}
    post.update(tel)
    return post


def reconstruct_active_root(opening, rec: dict) -> dict:
    """Rebuild opening→g123→F2→SD5 for one selected F2. No hand edits."""

    name = rec.get("name")
    acts = _ancestry_from_stage_a(rec.get("post_digest") or "")
    if name == "CONTROL_187":
        f2 = reconstruct_root_b(opening)
        if f2.get("ok"):
            post = apply_exact_final_deal({"g": f2["g"], "ordered_digest": f2["ordered_digest"], "full_actions": f2.get("full_actions") or []})
            post["name"] = name
            post["verify_ok"] = bool(post.get("ok") and post.get("post_digest") == rec.get("post_digest"))
            post["pre_g"] = f2["g"]
            post["g"] = post.get("post_g")
            post["ordered_digest"] = post.get("post_digest")
            post["whole_game_identity"] = post.get("ident")
            post["n_deal"] = sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a))
            return post
    if name == "CONTROL_ROOT_A":
        f2 = reconstruct_root_a(opening)
        if f2.get("ok"):
            post = apply_exact_final_deal({"g": f2["g"], "ordered_digest": f2["ordered_digest"], "full_actions": f2.get("full_actions") or []})
            post["name"] = name
            post["verify_ok"] = bool(post.get("ok") and post.get("post_digest") == rec.get("post_digest"))
            post["pre_g"] = f2["g"]
            post["g"] = post.get("post_g")
            post["ordered_digest"] = post.get("post_digest")
            post["whole_game_identity"] = post.get("ident")
            post["n_deal"] = sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a))
            return post
    if acts:
        n_deal = sum(1 for a in as_actions(acts) if is_deal(a))
        if n_deal == 5:
            end = opening.clone()
            try:
                g_rep = replay_actions(end, as_actions(acts))
            except Exception:
                g_rep = None
            digest_ok = pack_state(end).hex() == rec["post_digest"]
            st = unpack_state(bytes.fromhex(rec["post_digest"]))
            tel = structural_telemetry(st)
            ident = pack_whole_game_identity(st).hex()
            return {
                "ok": True,
                "verify_ok": bool(g_rep == int(rec["post_g"]) and digest_ok and stock_rows(end) == 0),
                "name": name,
                "pre_g": rec.get("pre_g"),
                "pre_digest": rec.get("pre_digest"),
                "g": int(rec["post_g"]),
                "post_g": int(rec["post_g"]),
                "post_digest": rec["post_digest"],
                "ordered_digest": rec["post_digest"],
                "ident": ident,
                "whole_game_identity": ident,
                "full_actions": dump_actions(as_actions(acts)),
                "n_deal": 5,
                "foundations": 2,
                "face_down": rec.get("face_down") or 2,
                "empty_n": rec.get("empty_n") or 0,
                "stock_rows": 0,
                "assembly_h": rec.get("assembly_h"),
                "assembly_f": rec.get("assembly_f"),
                "slack": rec.get("slack"),
                "legal": rec.get("legal"),
                "legal_tableau": rec.get("legal"),
                **tel,
            }
        rec = dict(rec)
        rec["full_actions"] = acts
        post = verify_post_deal(rec)
        post["g"] = post.get("post_g")
        post["ordered_digest"] = post.get("post_digest")
        post["whole_game_identity"] = post.get("ident")
        post["n_deal"] = sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a))
        post["name"] = name
        return post
    g123 = reconstruct_g123(opening)
    if not g123.get("ok"):
        return {"ok": False, "verify_ok": False, "reason": "g123_failed", "name": name}
    g123_root = {
        "g": int(g123["g"]),
        "ordered_digest": g123["ordered_digest"],
        "whole_game_identity": g123.get("whole_game_identity") or g123["ordered_digest"],
        "full_actions": g123.get("prefix_actions") or g123.get("full_actions") or [],
        "stock_rows": 1,
        "foundations": 1,
        "face_down": g123.get("face_down") or 2,
    }
    recov = recover_digest_path(opening, g123_root, rec["pre_digest"], int(rec["pre_g"]), time_s=120.0, unique=200_000)
    if not recov.get("ok"):
        recov = recover_digest_path(opening, g123_root, rec["post_digest"], int(rec["post_g"]), time_s=120.0, unique=200_000)
        if recov.get("ok"):
            post = dict(rec)
            post["full_actions"] = recov.get("full_actions")
            post["ok"] = True
            post["verify_ok"] = True
            post["g"] = rec["post_g"]
            post["ordered_digest"] = rec["post_digest"]
            post["whole_game_identity"] = _post_ident(rec)
            post["ident"] = post["whole_game_identity"]
            post["n_deal"] = sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a))
            post["foundations"] = 2
            post["face_down"] = rec.get("face_down") or 2
            post["stock_rows"] = 0
            post["name"] = name
            return post
        return {"ok": False, "verify_ok": False, "reason": recov.get("reason") or "ancestry_recover_failed", "name": name}
    pre = {
        "g": int(rec["pre_g"]),
        "ordered_digest": rec["pre_digest"],
        "full_actions": recov.get("full_actions"),
        "tactical_target": rec.get("tactical_target"),
    }
    post = apply_exact_final_deal(pre)
    post["name"] = name
    post["verify_ok"] = bool(post.get("ok") and post.get("post_digest") == rec.get("post_digest"))
    post["g"] = post.get("post_g")
    post["ordered_digest"] = post.get("post_digest")
    post["whole_game_identity"] = post.get("ident")
    post["n_deal"] = sum(1 for a in as_actions(post.get("full_actions") or []) if is_deal(a))
    return post


def as_search_root(post: dict) -> dict:
    return {
        "g": int(post.get("g") or post.get("post_g")),
        "ordered_digest": post.get("ordered_digest") or post.get("post_digest"),
        "ident": post.get("ident") or post.get("whole_game_identity"),
        "whole_game_identity": post.get("whole_game_identity") or post.get("ident"),
        "full_actions": post.get("full_actions") or [],
        "stock_rows": 0,
        "foundations": int(post.get("foundations") or 2),
        "face_down": int(post.get("face_down") or 2),
        "assembly_h": post.get("assembly_h"),
        "assembly_f": post.get("assembly_f"),
        "lineage": [post.get("name") or "f2"],
        "name": post.get("name"),
    }


def search_one_f2(opening, post: dict, *, time_s: float, unique: int = STAGE_A_UNIQUE):
    root = as_search_root(post)
    return search_f4_portfolio(opening, [root], time_s=float(time_s), unique=int(unique))


def classify_search(res, rec: dict) -> dict:
    tracker = getattr(res, "snapshot_tracker", None)
    max_f = int(getattr(tracker, "max_F", rec.get("foundations") or 2) or 2)
    cheap = dict(getattr(tracker, "cheap_F", {}) or {})
    deep = cheap.get(max_f) or cheap.get(str(max_f)) or {}
    if not deep.get("g"):
        deep = {
            "g": rec.get("g") or rec.get("post_g"),
            "h": rec.get("assembly_h"),
            "f": rec.get("assembly_f"),
            "slack": rec.get("slack"),
        }
    interp = interpret_continuation_stop(res.stop_reason, solved=bool(res.solved))
    f_at = deep.get("f")
    if interp.get("exhausted") and not res.solved:
        status = "LONG_HORIZON_DEAD"
    elif interp.get("resource_limited"):
        status = "LONG_HORIZON_LIVE"
    else:
        status = "LONG_HORIZON_DEAD"
    slack = None if f_at is None else assembly_slack(BRIDGE_CEILING, int(f_at))
    return {
        "name": rec.get("name"),
        "start_g": rec.get("g") or rec.get("post_g"),
        "start_h": rec.get("assembly_h"),
        "start_f": rec.get("assembly_f"),
        "max_F": max_f,
        "deepest": {"F": max_f, "g": deep.get("g"), "h": deep.get("h"), "f": f_at, "slack": slack},
        "time_first_increase": getattr(tracker, "time_first_increase", None),
        "stop_reason": res.stop_reason,
        "exhausted": bool(interp.get("exhausted")),
        "resource_limited": bool(interp.get("resource_limited")),
        "status": status,
        "solved": bool(res.solved),
        "solution_g": res.solution_g,
        "unique": res.unique,
        "expanded": res.expanded,
        "elapsed_s": res.elapsed_s,
        "calibration": rec.get("name") == "CONTROL_187",
    }


def novel_rank_key(sig: dict) -> tuple:
    """Deep consequence only. Starting f and old rollout are ignored."""

    solved = 0 if sig.get("solved") and sig.get("solution_g") is not None and int(sig["solution_g"]) <= 186 else 1
    term = int(sig["solution_g"]) if solved == 0 else 10**9
    max_f = int(sig.get("max_F") or 0)
    deep = sig.get("deepest") or {}
    f_at = int(deep["f"]) if deep.get("f") is not None else 10**9
    slack = int(deep["slack"]) if deep.get("slack") is not None else -10**9
    g_at = int(deep["g"]) if deep.get("g") is not None else 10**9
    dead = 1 if sig.get("status") == "LONG_HORIZON_DEAD" else 0
    h_at = int(deep["h"]) if deep.get("h") is not None else 10**9
    return (solved, term, -max_f, f_at, -slack, g_at, dead, h_at)


def choose_f2_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "LONG_HORIZON_F2_CONTRACT_FAILURE", p.get("contract_reason") or "state/provenance/search/accounting/firewall failure"
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("novel_solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "LONG_HORIZON_F2_COST_IMPROVED", f"novel solved at g={best}"
    if p.get("calibration_insufficient"):
        return "LONG_HORIZON_F2_CALIBRATION_INSUFFICIENT", "CONTROL_187 did not reach F4; horizon cannot distinguish the known-good F2"
    ctrl = p.get("control_sig") or {}
    novels = list(p.get("novel_sigs") or [])
    ctrl_f = int(ctrl.get("max_F") or 0)
    best_novel_f = 0 if not novels else max(int(s.get("max_F") or 0) for s in novels)
    live_deep = [s for s in novels if int(s.get("max_F") or 0) >= 6 and s.get("status") == "LONG_HORIZON_LIVE"]
    if live_deep:
        return "LONG_HORIZON_F2_DEEP_CANDIDATE", f"novel maxF={live_deep[0].get('max_F')}"
    surplus_f5 = [
        s for s in novels
        if int(s.get("max_F") or 0) >= 5
        and (s.get("deepest") or {}).get("slack") is not None
        and int((s.get("deepest") or {}).get("slack") or 0) >= 1
        and s.get("status") == "LONG_HORIZON_LIVE"
    ]
    if surplus_f5:
        return "LONG_HORIZON_F2_DEEP_CANDIDATE", "novel live F5 with retained slack"
    if novels and all(s.get("status") == "LONG_HORIZON_DEAD" for s in novels) and ctrl_f >= 4:
        return "LONG_HORIZON_F2_NOVELS_EXHAUSTED", "novel graphs closed; CONTROL_187 remained deeper/live"
    if ctrl_f > best_novel_f or (
        ctrl_f >= 4 and best_novel_f <= 3 and ctrl.get("status") != "LONG_HORIZON_DEAD"
    ):
        return "LONG_HORIZON_F2_CONTROL_VALIDATED", f"CONTROL_187 maxF={ctrl_f} vs novel maxF={best_novel_f}"
    if any(s.get("status") == "LONG_HORIZON_LIVE" and int(s.get("max_F") or 0) >= 4 for s in novels):
        return "LONG_HORIZON_F2_SEARCH_LIMITED", "a deep novel lineage remains unresolved"
    if ctrl_f <= 3 and best_novel_f <= 3:
        return "LONG_HORIZON_F2_CALIBRATION_INSUFFICIENT", "neither control nor novels escaped F3"
    return "LONG_HORIZON_F2_CONTROL_VALIDATED", "CONTROL_187 is the strongest observed deep root"


def next_recommendation(verdict: str) -> str:
    if verdict == "LONG_HORIZON_F2_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "LONG_HORIZON_F2_DEEP_CANDIDATE":
        return "Focus the next version on that exact novel F2 root."
    if verdict == "LONG_HORIZON_F2_SEARCH_LIMITED":
        return "Keep the live novel F2 as the focused control; do not widen wall time."
    if verdict == "LONG_HORIZON_F2_CALIBRATION_INSUFFICIENT":
        return "Do not generate more upstream candidates yet. Improve consequence-evaluator depth/efficiency first."
    if verdict in ("LONG_HORIZON_F2_CONTROL_VALIDATED", "LONG_HORIZON_F2_NOVELS_EXHAUSTED"):
        return (
            "Move upstream: strategic rows=1 F1 preparation → tactical F2 cash-out → SD5 → long-horizon adjudication."
        )
    return "Do not promote; diagnose the contract."
