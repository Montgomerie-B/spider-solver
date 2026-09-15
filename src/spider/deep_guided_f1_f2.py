"""v0.96 deep-guided rows=1 F1 preparation → F2 cash-out → lean consequence.

Canonical 172 is not read. CONTROL_187 suffix is not used as search guidance.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.blinded_deep_f2 import load_five_root_specs, run_blinded_lean
from spider.f2_quality_frontier import apply_exact_final_deal, harvest_f2_target, verify_g123_root
from spider.g128_focused_endgame import reconstruct_g123
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import harvest_preparation
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.structural_analysis import current_tableau_summary

PREP_S = 90.0
PREP_UNIQUE = 100_000
PREP_MAX_DG = 8
PREP_SELECT = 4
TACTICAL_S = 12.0
TACTICAL_UNIQUE = 75_000
TARGETS_PER_F1 = 2
NOVEL_MAX = 6
STAGE_A_S = 25.0
STAGE_A_CEILING = 186
STAGE_A_UNIQUE = 300_000
STAGE_B_S = 35.0
STAGE_B_CEILING = 187
STAGE_B_UNIQUE = 300_000
STAGE_C_S = 180.0
STAGE_C_CEILING = 186
STAGE_C_UNIQUE = 800_000
BANDS = ("1-2", "3-4", "5-6", "7-8")


def f1_prep_band(dg: int) -> str:
    d = int(dg)
    if d <= 0:
        return "0"
    if d <= 2:
        return "1-2"
    if d <= 4:
        return "3-4"
    if d <= 6:
        return "5-6"
    return "7-8"


def f1_as_harvest_root(g123: dict) -> dict:
    return {
        "g": int(g123["g"]),
        "ordered_digest": g123["ordered_digest"],
        "full_actions": g123.get("prefix_actions") or g123.get("full_actions") or [],
        "name": "G123_F1",
    }


def select_prepared_f1s(cands: Sequence[dict], original: dict) -> List[dict]:
    orig = dict(original)
    orig["prep_delta_g"] = 0
    orig["prep_band"] = "0"
    orig["source_role"] = "ORIGINAL_G123"
    picks = [orig]
    seen = {orig["ordered_digest"]}
    by_band: Dict[str, List[dict]] = {b: [] for b in BANDS}
    for rec in cands:
        if int(rec.get("foundations") or 1) != 1:
            continue
        d = rec["ordered_digest"]
        if d in seen:
            continue
        dg = int(rec.get("prep_delta_g") or 0)
        if dg <= 0:
            continue
        band = f1_prep_band(dg)
        if band in by_band:
            by_band[band].append(rec)
    for band in BANDS:
        rows = sorted(by_band[band], key=lambda r: (int(r["g"]), -int(r.get("legal_tableau") or 0), r["ordered_digest"]))
        if not rows:
            continue
        rec = dict(rows[0])
        rec["source_role"] = f"PREP_{band}"
        picks.append(rec)
        seen.add(rec["ordered_digest"])
        if len(picks) >= 1 + int(PREP_SELECT):
            break
    return picks[: 1 + int(PREP_SELECT)]


def fresh_targets(digest: str, g: int) -> List[dict]:
    st = unpack_state(bytes.fromhex(digest))
    ranked = rank_ready_suits(st, g=int(g))
    ready = set(ranked.get("ready_suits") or [])
    out = []
    for rec in ranked.get("ranked") or []:
        if rec.get("suit") in ready:
            out.append(dict(rec))
        if len(out) >= TARGETS_PER_F1:
            break
    return out


def retain_f2_terminals(terms: Sequence[dict]) -> List[dict]:
    f2 = [r for r in terms if int(r.get("foundations") or 0) == 2 and int(r.get("stock_rows") or 0) == 1]
    if not f2:
        return []
    first = min(f2, key=lambda r: (r.get("delta_g") if r.get("delta_g") is not None else 10**9, int(r["g"]), r["ordered_digest"]))
    cheap = min(f2, key=lambda r: (int(r["g"]), r["ordered_digest"]))
    picks = []
    seen: Set[str] = set()
    for rec, role in ((first, "first_f2"), (cheap, "cheapest_f2")):
        d = rec["ordered_digest"]
        if d in seen:
            continue
        item = dict(rec)
        item["f2_role"] = role
        picks.append(item)
        seen.add(d)
    extras = [r for r in f2 if r["ordered_digest"] not in seen]
    if extras:
        extra = min(extras, key=lambda r: (int(r["g"]), r["ordered_digest"]))
        extra = dict(extra)
        extra["f2_role"] = "extra_f2"
        picks.append(extra)
    return picks


def post_sd5_record(f2: dict, cache) -> dict:
    post = apply_exact_final_deal(
        {
            "g": int(f2["g"]),
            "ordered_digest": f2["ordered_digest"],
            "full_actions": f2.get("full_actions") or [],
            "tactical_target": f2.get("tactical_target"),
        }
    )
    f = int(post.get("assembly_f") or 10**9)
    post["slack_186"] = 186 - f
    post["slack_187"] = 187 - f
    post["production_viable"] = f <= 186
    post["incumbent_class_viable"] = f == 187
    post["proof_dead"] = f > 187
    post["f2_role"] = f2.get("f2_role")
    post["f1_source"] = f2.get("f1_source")
    post["prep_delta_g"] = f2.get("prep_delta_g")
    return post


def known_post_idents() -> Dict[str, dict]:
    out = {}
    for rec in load_five_root_specs():
        ident = rec.get("ident") or rec.get("whole_game_identity")
        if ident:
            out[ident] = {"name": rec.get("name"), "g": int(rec.get("post_g") or rec.get("g") or 0)}
    return out


def select_novel_posts(posts: Sequence[dict], known: dict, *, k: int = NOVEL_MAX) -> tuple:
    hits = []
    reopen = []
    live = []
    for rec in posts:
        if rec.get("proof_dead") or not rec.get("ok"):
            continue
        ident = rec.get("ident") or rec.get("whole_game_identity")
        g = int(rec.get("post_g") or rec.get("g") or 0)
        prev = known.get(ident)
        if prev is not None:
            item = dict(rec)
            item["known_name"] = prev.get("name")
            if g < int(prev["g"]):
                item["reopened"] = True
                reopen.append(item)
                live.append(item)
            else:
                item["known_hit"] = True
                hits.append(item)
            continue
        live.append(rec)
    picks: List[dict] = []
    seen: Set[str] = set()

    def take(rec):
        if rec is None:
            return
        ident = rec.get("ident")
        if not ident or ident in seen:
            return
        seen.add(ident)
        picks.append(rec)

    for rec in reopen:
        take(rec)
    by_src: Dict[str, List[dict]] = {}
    for rec in live:
        if rec.get("ident") in seen:
            continue
        by_src.setdefault(str(rec.get("f1_source") or "x"), []).append(rec)
    srcs = sorted(by_src)
    i = 0
    while len(picks) < int(k) and any(by_src[s] for s in srcs):
        s = srcs[i % len(srcs)]
        rows = by_src[s]
        if rows:
            rec = min(rows, key=lambda r: (int(r.get("assembly_f") or 10**9), int(r.get("post_g") or 10**9), r.get("post_digest") or ""))
            rows.remove(rec)
            take(rec)
        i += 1
    return picks[: int(k)], hits, reopen


def classify_completion(stage_a: dict, stage_b: dict) -> str:
    if stage_a.get("solved") and stage_a.get("terminal_g") is not None and int(stage_a["terminal_g"]) <= 186:
        return "CLASS_186"
    if stage_b.get("solved") and stage_b.get("terminal_g") is not None and int(stage_b["terminal_g"]) == 187:
        return "CLASS_187"
    return "UNRESOLVED_187"


def route_pressure(opening, post: dict, kr, cache) -> dict:
    if not kr.terminals:
        return {}
    term = kr.terminals[0]
    path = kr.reconstruct(int(term["node"]))
    st = unpack_state(bytes.fromhex(post["ordered_digest"]))
    g = int(post["g"])
    first_187 = None
    n_187 = 0
    run = 0
    max_run = 0
    first_F = None
    for i, a in enumerate(path):
        if is_deal(a):
            continue
        from spider.research_actions import apply_action, step_cost

        c = step_cost(st, a)
        apply_action(st, a)
        g += int(c)
        h = int(cache(st, g))
        f = g + h
        if f >= 187:
            n_187 += 1
            run += 1
            max_run = max(max_run, run)
            if first_187 is None:
                first_187 = {"action_index": i, "g": g, "h": h, "f": f, "foundations": len(st.foundations)}
                first_F = len(st.foundations)
        else:
            run = 0
    return {
        "n_actions": len(path),
        "n_f187": n_187,
        "max_run_f187": max_run,
        "first_f187": first_187,
        "first_f187_F": first_F,
    }


def choose_stage_c(rows: Sequence[dict], pressures: dict) -> Optional[dict]:
    novels = [r for r in rows if r.get("name") != "CONTROL_187" and r.get("cls") == "CLASS_187"]
    if not novels:
        return None

    def key(r):
        pr = pressures.get(r["name"]) or {}
        first = pr.get("first_f187") or {}
        return (
            -(int(first.get("action_index") or -1)),
            int(pr.get("n_f187") or 10**9),
            int(pr.get("max_run_f187") or 10**9),
            int((r.get("stage_b") or {}).get("unique") or 10**9),
            r.get("post_digest") or "",
        )

    return min(novels, key=key)


def choose_verdict(p: dict) -> tuple:
    if p.get("root_fail") or p.get("accounting_fail"):
        return "DEEP_GUIDED_F1_F2_CONTRACT_FAILURE", p.get("contract_reason") or "state/rules/accounting/identity/firewall/replay failure"
    if p.get("calibration_failure"):
        return "DEEP_GUIDED_F1_F2_CALIBRATION_FAILURE", "CONTROL_187 failed the frozen 35s ceiling-187 check"
    if p.get("lower_g_control"):
        return "DEEP_GUIDED_F1_F2_LOWER_G_CONVERGENCE", "CONTROL_187 identity reached at lower g"
    if p.get("novel_le_186") and p.get("replay_ok"):
        return "DEEP_GUIDED_F1_F2_COST_IMPROVED", f"novel g={p.get('best_novel_g')}"
    if p.get("n_novel_187"):
        return "DEEP_GUIDED_F1_F2_NEW_187_CLASS", f"{p.get('n_novel_187')} novel CLASS_187 root(s)"
    if p.get("deep_candidate"):
        return "DEEP_GUIDED_F1_F2_DEEP_CANDIDATE", "novel lineage remains live with deep consequence"
    return "DEEP_GUIDED_F1_F2_NO_GAIN", "calibration passed but no novel root materially improves existing F2 choices"


def next_recommendation(verdict: str) -> str:
    if verdict == "DEEP_GUIDED_F1_F2_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "DEEP_GUIDED_F1_F2_LOWER_G_CONVERGENCE":
        return "Validate/complete the lower-g CONTROL_187 arrival at ceiling 186."
    if verdict == "DEEP_GUIDED_F1_F2_NEW_187_CLASS":
        return "That novel CLASS_187 F2 is the only serious production candidate; target its completed 187 path for a one-move cut."
    if verdict == "DEEP_GUIDED_F1_F2_DEEP_CANDIDATE":
        return "Continue the live novel lineage at ceiling 186."
    if verdict == "DEEP_GUIDED_F1_F2_CALIBRATION_FAILURE":
        return "Repair evaluator performance before broadening."
    return "This bounded F1-preparation hypothesis failed. Do not keep mining it automatically."
