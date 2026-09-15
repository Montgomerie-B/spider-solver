"""v0.97 focused ceiling-186 search of the v0.96 ORIGINAL_G123 F5 F2.

Canonical 172 is not read. CONTROL_187 suffix is not used as search guidance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.blinded_deep_f2 import load_five_root_specs
from spider.deep_guided_f1_f2 import (
    TACTICAL_S,
    TACTICAL_UNIQUE,
    f1_as_harvest_root,
    fresh_targets,
    post_sd5_record,
    retain_f2_terminals,
)
from spider.f2_quality_frontier import harvest_f2_target, load_f2_closed_table, verify_g123_root
from spider.f3_tactical_bridge import assembly_slack
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import load_prep_closed_table
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB

ROOT = Path(__file__).resolve().parents[2]
V096_JSON = ROOT / "docs" / "research" / "deep_guided_f1_f2_v0_96.json"
PRIMARY_S = 240.0
PRIMARY_CEILING = 186
PRIMARY_UNIQUE = 800_000


def v096_f5_signal() -> dict:
    data = json.loads(V096_JSON.read_text(encoding="utf-8"))
    hits = [
        rec
        for rec in (data.get("stage_a") or [])
        if rec.get("name") == "ORIGINAL_G123" and int(rec.get("max_F") or 0) == 5
    ]
    if len(hits) != 1:
        raise KeyError(f"v0.96 F5 ORIGINAL_G123 not unique: {len(hits)}")
    rec = dict(hits[0])
    rec["source"] = "ORIGINAL_G123"
    return rec


def inspect_post(digest: str, g: int) -> dict:
    st = unpack_state(bytes.fromhex(digest))
    s = current_tableau_summary(st)
    tel = structural_telemetry(st)
    h = int(stock_empty_assembly_h(st, int(g)))
    f = int(g) + h
    return {
        "g": int(g),
        "foundations": len(st.foundations),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal": len(tableau_actions(st)),
        "visible_runs": tel["visible_runs"],
        "visible_components": tel["visible_components"],
        "mixed_suit_boundaries": tel["mixed_suit_boundaries"],
        "assembly_h": h,
        "assembly_f": f,
        "slack_186": assembly_slack(186, f),
        "ordered_digest": pack_state(st).hex(),
        "ident": pack_whole_game_identity(st).hex(),
        "stock_rows": stock_rows(st),
        "can_deal": bool(st.can_deal()),
    }


def historical_idents() -> Dict[str, str]:
    out = {}
    for rec in load_five_root_specs():
        ident = rec.get("ident")
        if ident:
            out[str(rec.get("name"))] = ident
    return out


def resolve_v096_f5_root(opening) -> dict:
    """Recover the v0.96 F5 candidate from ORIGINAL_G123 tactical F2 only. No F1 prep harvest."""

    signal = v096_f5_signal()
    g123 = verify_g123_root(opening)
    if not g123.get("ok"):
        return {"ok": False, "reason": "g123_failed", "g123": g123}
    tgts = fresh_targets(g123["ordered_digest"], int(g123["g"]))
    if not tgts:
        return {"ok": False, "reason": "no_ready_suits"}
    hv = harvest_f2_target(
        {"g": g123["g"], "ordered_digest": g123["ordered_digest"], "prefix_actions": g123.get("prefix_actions") or []},
        tgts[0],
        time_s=TACTICAL_S,
        unique=TACTICAL_UNIQUE,
    )
    kept = retain_f2_terminals(hv.get("terminals") or [])
    hist = historical_idents()
    ctrl = hist.get("CONTROL_187")
    posts = []
    for rec in kept:
        rec["f1_source"] = "ORIGINAL_G123"
        post = post_sd5_record(rec, None)
        if not post.get("ok"):
            continue
        posts.append(post)
    cands = [
        p
        for p in posts
        if int(p.get("post_g") or p.get("g") or 0) == 130
        and (p.get("ident") or p.get("whole_game_identity")) != ctrl
    ]
    if not cands:
        cands = [p for p in posts if (p.get("ident") or "") != ctrl]
    if not cands:
        return {"ok": False, "reason": "no_post_130_distinct", "n_kept": len(kept), "n_post": len(posts), "signal": signal}
    # Prefer first_f2 (cheapest ORIGINAL_G123 F2 was g128 → post 129)
    chosen = next((p for p in cands if p.get("f2_role") == "first_f2"), cands[0])
    g = int(chosen.get("post_g") or chosen.get("g"))
    insp = inspect_post(chosen.get("post_digest") or chosen.get("ordered_digest"), g)
    ident = insp["ident"]
    distinct = {name: ident != other for name, other in hist.items()}
    ok = (
        insp["foundations"] == 2
        and insp["stock_rows"] == 0
        and not insp["can_deal"]
        and insp["g"] == 130
        and distinct.get("CONTROL_187", True)
    )
    chosen.update(insp)
    chosen["ok"] = bool(ok)
    chosen["g"] = g
    chosen["ordered_digest"] = insp["ordered_digest"]
    chosen["whole_game_identity"] = ident
    chosen["ident"] = ident
    chosen["source_f1"] = "ORIGINAL_G123"
    chosen["v096_signal"] = {k: signal.get(k) for k in ("max_F", "first_deep_g", "first_deep_f", "unique", "elapsed_s")}
    chosen["distinct"] = distinct
    chosen["tactical_suit"] = tgts[0].get("suit")
    chosen["n_deal"] = sum(1 for a in as_actions(chosen.get("full_actions") or []) if is_deal(a))
    chosen["reason"] = None if ok else "telemetry_or_identity_mismatch"
    return chosen


def audit_closed(obs, table: Optional[dict] = None) -> dict:
    table = table if table is not None else {**load_f2_closed_table(), **load_prep_closed_table()}
    hits = []
    reopen = []
    seen = set()
    for store in (obs.first_F, obs.cheap_F, obs.minf_F):
        for rec in store.values():
            ident = rec.get("ident")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            closed = table.get(ident)
            if closed is None:
                continue
            g = int(rec.get("g") or 0)
            item = {
                "ident": ident,
                "arrival_g": g,
                "closed_g": int(closed.get("g") or 0),
                "closed_source": closed.get("source"),
                "F": rec.get("foundations"),
                "reopened": g < int(closed.get("g") or 0),
            }
            hits.append(item)
            if item["reopened"]:
                reopen.append(item)
    return {"n_hits": len(hits), "n_reopen": len(reopen), "hits": hits}


def choose_verdict(p: dict) -> tuple:
    if p.get("root_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "F5_PRODUCTION_CONTRACT_FAILURE", p.get("contract_reason") or "root/provenance/rules/accounting/firewall failure"
    if p.get("solved") and p.get("replay_ok") and p.get("solution_g") is not None and int(p["solution_g"]) <= 186:
        return "F5_PRODUCTION_COST_IMPROVED", f"solved at g={p.get('solution_g')}"
    if p.get("stop_reason") == "complete" and not p.get("solved"):
        return "F5_PRODUCTION_EXHAUSTED", "exact proof-viable graph completed without a solution"
    max_f = int(p.get("max_foundations") or 0)
    if not p.get("f5_reproduced"):
        return "F5_PRODUCTION_SIGNAL_NOT_REPRODUCED", f"maxF={max_f} first_F5={p.get('first_F5')}"
    if max_f >= 6 and p.get("stop_reason") in ("time limit", "unique limit", "rss abort"):
        return "F5_PRODUCTION_DEEP_LIVE", f"maxF={max_f} stop={p.get('stop_reason')}"
    if max_f == 5:
        return "F5_PRODUCTION_F5_STALL", "reproduced F5 but no deeper meaningful consequence"
    return "F5_PRODUCTION_F5_STALL", f"maxF={max_f}"


def next_recommendation(verdict: str) -> str:
    if verdict == "F5_PRODUCTION_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "F5_PRODUCTION_DEEP_LIVE":
        return "Pause paid work and consolidate; optionally continue this exact root locally/offline."
    if verdict == "F5_PRODUCTION_EXHAUSTED":
        return "Close this candidate permanently. Pause and consolidate the architecture."
    if verdict == "F5_PRODUCTION_F5_STALL":
        return "The 25-second F5 signal did not mature. Pause and consolidate."
    if verdict == "F5_PRODUCTION_SIGNAL_NOT_REPRODUCED":
        return "Diagnose exact-root mismatch before further paid search."
    return "Do not promote; diagnose the contract."
