#!/usr/bin/env python3
"""v0.38: post-SD4 foundation race — Heart 1 vs Diamond 1.

Equal envelopes. SD5 never taken. Current-horizon occurrence excludes SD5.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_current_horizon import (
    audit_pre_sd4_hearts_leak,
    backward_map,
    current_horizon_material_audit,
    occurrence_counts,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import search_foundation, suit_foundation_count
from spider.simple_h9_cut import JOIN_BREAK, allowed_at_level, annotate_h9_action
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

EXPERIMENT = "post_sd4_foundation_race_v0_38"
BASE_SHA = "45080bfa768298def726fe473ea5bc12e0963bd8"
BRANCH = "agent/post-sd4-foundation-race-v0-38"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
H9_PORT = ROOT / "docs" / "research" / "sd4_operational_horizon_pivot_v0_37_h9_portfolio.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
HEART_PORT = ROOT / "docs" / "research" / f"{EXPERIMENT}_heart_portfolio.json"
DIAMOND_PORT = ROOT / "docs" / "research" / f"{EXPERIMENT}_diamond_portfolio.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
HEART_FIX = ROOT / "solutions" / "4925153_v0_38_heart_foundation_best.moves.txt"
DIAMOND_FIX = ROOT / "solutions" / "4925153_v0_38_diamond_foundation_best.moves.txt"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def dump_actions(actions):
    return [list(a) if a != ("deal",) else ["deal"] for a in actions]


def load_h9(opening: SpiderState):
    port = json.loads(H9_PORT.read_text(encoding="utf-8"))
    rows, states, paths, gs = [], [], [], []
    seen = {}
    for rec in port["states"]:
        full = as_actions(rec["full_actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        ident = pack_state(end)
        ok = (
            cost == rec["full_cost"]
            and ident.hex() == rec["ordered_digest"]
            and stock_rows(end) == 1
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and pretty_card(end.columns[1].face_up[-1]) == "9H"
        )
        item = {
            "ok": ok,
            "full_cost": cost,
            "qh_jh_same_suit": bool(rec.get("qh_jh_same_suit")),
            "macros": rec.get("macros") or rec.get("via") or [],
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "family": "A" if rec.get("qh_jh_same_suit") else "B",
        }
        prev = seen.get(ident)
        if prev is not None and cost >= prev:
            continue
        seen[ident] = cost
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx] = item
            states[idx] = end
            paths[idx] = full
            gs[idx] = cost
        else:
            rows.append(item)
            states.append(end)
            paths.append(full)
            gs.append(cost)
    print(
        f"H9 n={len(rows)} costs={Counter(r['full_cost'] for r in rows)} "
        f"A={sum(1 for r in rows if r['family']=='A')} B={sum(1 for r in rows if r['family']=='B')} "
        f"ok={all(r['ok'] for r in rows)}",
        flush=True,
    )
    return rows, states, paths, gs


def aggregate_maps(states, suit: str) -> dict:
    hard_freq = Counter()
    alt_freq = Counter()
    gate_status = Counter()
    for st in states:
        m = backward_map(st, suit)
        for r in m["hard_ranks"]:
            hard_freq[r] += 1
        for r in m["alternative_ranks"]:
            alt_freq[r] += 1
        for g in m["nearest_gates"]:
            gate_status[f"{g['card']}:{g['status']}"] += 1
    n = len(states)
    return {
        "n": n,
        "hard_on_all": sorted(r for r, c in hard_freq.items() if c == n),
        "hard_on_some": dict(hard_freq),
        "alternative_on_all": sorted(r for r, c in alt_freq.items() if c == n),
        "gate_status": dict(gate_status),
    }


def classify_interaction(before: SpiderState, after: Optional[SpiderState], other_suit: str) -> str:
    if after is None:
        return "CROSS_TARGET_NEUTRAL"
    b = backward_map(before, other_suit)
    a = backward_map(after, other_suit)
    b_hard = {g["card"] + g["status"] for g in b["nearest_gates"]}
    a_open = sum(1 for g in a["nearest_gates"] if g["status"] == "exposed_movable")
    b_open = sum(1 for g in b["nearest_gates"] if g["status"] == "exposed_movable")
    a_down = sum(1 for g in a["nearest_gates"] if g["requires_reveal"])
    b_down = sum(1 for g in b["nearest_gates"] if g["requires_reveal"])
    if a_open > b_open or a_down < b_down:
        return "CROSS_TARGET_HELP"
    if a_open < b_open or a_down > b_down:
        return "CROSS_TARGET_DEBT"
    return "CROSS_TARGET_NEUTRAL"


def persist_portfolio(opening, rows, paths, gs, search, path: Path, fixture_path: Path, tag: str):
    rebuilt = []
    for rec in search.witnesses:
        full = list(paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "continuation": cost - gs[rec["origin"]],
                "source_g": gs[rec["origin"]],
                "family": rows[rec["origin"]]["family"],
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "fd": face_down_count(end),
                "foundations": len(end.foundations),
                "foundation_suits": [run[0].suit for run in end.foundations if run],
                "empties": list(empty_column_indices(end)),
                "stock_rows": stock_rows(end),
                "ordered_digest": pack_state(end).hex(),
                "full_replay_ok": cost == rec["g"] and suit_foundation_count(end, tag[0]) >= 1,
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w["full_path_length"]))
    first = rebuilt[0] if rebuilt else None
    fixture = None
    if first:
        fixture_path.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=f"# v0.38 {tag} foundation\n# full_mw: {first['full_cost']}",
            ),
            encoding="utf-8",
        )
        first["fixture"] = fixture_path.relative_to(ROOT).as_posix()
        fixture = first["fixture"]
    bands = Counter(w["full_cost"] for w in rebuilt)
    _write_json(
        path,
        {
            "experiment": EXPERIMENT,
            "kind": f"{tag}_portfolio",
            "f": None if not first else first["full_cost"],
            "n": len(rebuilt),
            "bands": {str(k): int(v) for k, v in sorted(bands.items())},
            "states": rebuilt,
        },
    )
    return rebuilt, first, fixture


def choose_verdict(h_class, d_class, h_f, d_f, replay_ok, horizon_ok, explosion):
    if not replay_ok:
        return "SOURCE_REPLAY_FAILURE", "H9 portfolio failed replay"
    if not horizon_ok:
        return "HORIZON_ACCOUNTING_MISMATCH", "current/future material audit contradicts engine"
    if explosion and h_class != "FOUNDATION_REACHED" and d_class != "FOUNDATION_REACHED":
        return "TARGET_RACE_STATE_EXPLOSION", "resource limits prevent a meaningful comparison"
    h_hit = h_class == "FOUNDATION_REACHED"
    d_hit = d_class == "FOUNDATION_REACHED"
    if h_hit and not d_hit:
        return "HEART_SECOND_FOUNDATION_LEADS", f"Heart 1 at full MW {h_f}; Diamond 1 not reached"
    if d_hit and not h_hit:
        return "DIAMOND_SECOND_FOUNDATION_LEADS", f"Diamond 1 at full MW {d_f}; Heart 1 not reached"
    if h_hit and d_hit:
        if h_f < d_f:
            return "BOTH_SECOND_FOUNDATIONS_VIABLE_HEART_COST_LEADER", f"Heart {h_f} vs Diamond {d_f}"
        if d_f < h_f:
            return "BOTH_SECOND_FOUNDATIONS_VIABLE_DIAMOND_COST_LEADER", f"Diamond {d_f} vs Heart {h_f}"
        return "BOTH_SECOND_FOUNDATIONS_VIABLE_COST_TIE", f"both at full MW {h_f}"
    return "NO_SECOND_FOUNDATION_IN_ENVELOPE", "neither Heart 1 nor Diamond 1 reached before SD5"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("HEART_SECOND"):
        return (
            "Heart 1 is the operational leader before SD5. Carry the Heart foundation portfolio "
            "and reassess Diamond 1 (especially 2D under AH) as the next extra foundation. Do not take SD5 yet."
        )
    if verdict.startswith("DIAMOND_SECOND"):
        return (
            "Diamond 1 is the operational leader before SD5. Carry the Diamond foundation portfolio "
            "and reassess Heart 1 from the resulting states. Do not take SD5 yet."
        )
    if verdict.startswith("BOTH_SECOND"):
        return (
            "Both Heart 1 and Diamond 1 are viable before SD5. Keep both portfolios and choose the "
            "next cut by residual cross-target access, not sunk-cost Heart history. Do not take SD5 yet."
        )
    if verdict == "NO_SECOND_FOUNDATION_IN_ENVELOPE":
        return (
            "Neither foundation was removed before SD5 in the equal envelope. Next: attack the "
            "nearest remaining mandatory gates (Diamond: AH-on-2D; Heart: remaining unique buried ranks) "
            "rather than raising budgets. Do not take SD5 yet."
        )
    return "Keep the equal-envelope race. Do not take SD5. Do not inspect the human route."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.38 — Post-SD4 Foundation Race: Heart 1 vs Diamond 1",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "",
        "## 2. Horizon audit",
        "",
        json.dumps(payload.get("horizon") or {}, indent=2)[:3500],
        "",
        "## 3. Heart backward map",
        "",
        json.dumps(payload.get("heart_map") or {}, indent=2)[:3500],
        "",
        "## 4. Diamond backward map",
        "",
        json.dumps(payload.get("diamond_map") or {}, indent=2)[:3500],
        "",
        "## 5. Heart search",
        "",
        json.dumps(payload.get("heart_search") or {}, indent=2)[:2500],
        "",
        "## 6. Diamond search",
        "",
        json.dumps(payload.get("diamond_search") or {}, indent=2)[:2500],
        "",
        "## 7. Cross-target effects",
        "",
        json.dumps(payload.get("cross_target") or {}, indent=2)[:2000],
        "",
        "## 8. Comparison",
        "",
        json.dumps(payload.get("comparison") or {}, indent=2)[:2000],
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD5 expanded H={payload.get('sd5_h')} D={payload.get('sd5_d')}.",
        "Equal envelopes. Current-horizon excludes SD5. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def search_block(search, rebuilt, first, fixture, classification):
    return {
        "classification": classification,
        "reached": classification == "FOUNDATION_REACHED",
        "first_s": search.first_s,
        "first_unique": search.first_unique,
        "best_full_mw": None if not first else first.get("full_cost"),
        "unique": search.unique,
        "expanded": search.expanded,
        "generated": search.generated,
        "duplicate_skips": search.duplicate_skips,
        "levels": search.levels_reached,
        "elapsed_s": search.elapsed_s,
        "peak_rss_mb": search.peak_rss_mb,
        "stop_reason": search.stop_reason,
        "sd5_expanded": search.sd5_expanded,
        "portfolio_n": len(rebuilt),
        "replay": None if not first else first.get("full_replay_ok"),
        "fixture": fixture,
        "fd": None if not first else first.get("fd"),
        "empties": None if not first else first.get("empties"),
        "foundations": None if not first else first.get("foundation_suits"),
    }


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    rows, states, paths, gs = load_h9(opening)
    replay_ok = bool(states) and all(r["ok"] for r in rows)

    leak = audit_pre_sd4_hearts_leak(states[0], 9) if states else {"confirmed": False}
    print(f"HORIZON_LEAK confirmed={leak.get('confirmed')} legacy={leak.get('legacy_count')} current={leak.get('current_tableau_count')}", flush=True)
    material = current_horizon_material_audit(states[0]) if states else {}
    print(
        f"MATERIAL H1={material.get('heart_1_now')} D1={material.get('diamond_1_now')} "
        f"S2={material.get('spade_2_now')} C1={material.get('club_1_now')}",
        flush=True,
    )
    horizon_ok = bool(
        material.get("heart_1_now")
        and material.get("diamond_1_now")
        and not material.get("spade_2_now")
        and not material.get("club_1_now")
    )

    h_detail = backward_map(states[0], "h") if states else {}
    d_detail = backward_map(states[0], "d") if states else {}
    # Prefer a Macro-A 77-state for Heart component detail if present.
    a77 = next((i for i, r in enumerate(rows) if r["full_cost"] == 77 and r["family"] == "A"), None)
    b77 = next((i for i, r in enumerate(rows) if r["full_cost"] == 77 and r["family"] == "B"), None)
    h_agg = aggregate_maps(states, "h")
    d_agg = aggregate_maps(states, "d")
    two_d = occurrence_counts(states[0], "d", 2) if states else {}
    five_d = occurrence_counts(states[0], "d", 5) if states else {}
    print(
        f"MAP H hard_all={h_agg['hard_on_all']} D hard_all={d_agg['hard_on_all']} "
        f"2D current={two_d.get('current_count')} 5D current={five_d.get('current_count')}",
        flush=True,
    )

    print("SEARCH H start 450s", flush=True)
    h_search = search_foundation(states, paths, gs, suit="h", time_limit_s=450.0, max_unique=500_000, rss_abort_mb=2 * 1024.0)
    h_rebuilt, h_first, h_fix = persist_portfolio(opening, rows, paths, gs, h_search, HEART_PORT, HEART_FIX, "heart")
    print(f"SEARCH H class={h_search.classification} inc={h_search.incumbent} unique={h_search.unique}", flush=True)

    print("SEARCH D start 450s", flush=True)
    d_search = search_foundation(states, paths, gs, suit="d", time_limit_s=450.0, max_unique=500_000, rss_abort_mb=2 * 1024.0)
    d_rebuilt, d_first, d_fix = persist_portfolio(opening, rows, paths, gs, d_search, DIAMOND_PORT, DIAMOND_FIX, "diamond")
    print(f"SEARCH D class={d_search.classification} inc={d_search.incumbent} unique={d_search.unique}", flush=True)

    h_after = None
    d_after = None
    if h_first:
        h_after = opening.clone()
        replay_actions(h_after, as_actions(h_first["full_actions"]))
    if d_first:
        d_after = opening.clone()
        replay_actions(d_after, as_actions(d_first["full_actions"]))
    cross = {
        "heart_path_on_diamond": classify_interaction(states[0], h_after, "d"),
        "diamond_path_on_heart": classify_interaction(states[0], d_after, "h"),
        "heart_frees_2d": None,
        "diamond_moves_ah": None,
    }
    if h_after is not None:
        occ = occurrence_counts(h_after, "d", 2)
        tops = [c for c in occ["tableau"] if c.get("top")]
        cross["heart_frees_2d"] = bool(tops) and any(t.get("top") for t in tops)
        if h_after.columns[3].face_up:
            cross["heart_c4_top"] = pretty_card(h_after.columns[3].face_up[-1])
    if d_after is not None:
        cross["diamond_ah_still_on_2d"] = (
            len(d_after.columns[3].face_up) >= 2
            and pretty_card(d_after.columns[3].face_up[-1]) == "AH"
            and pretty_card(d_after.columns[3].face_up[-2]) == "2D"
        )
        cross["diamond_qh_jh"] = backward_map(d_after, "h")["components"]

    explosion = h_search.classification == "STATE_EXPLOSION" and d_search.classification == "STATE_EXPLOSION"
    verdict, reason = choose_verdict(
        h_search.classification,
        d_search.classification,
        None if not h_first else h_first["full_cost"],
        None if not d_first else d_first["full_cost"],
        replay_ok,
        horizon_ok,
        explosion,
    )
    leader = None
    cost_leader = None
    if verdict.startswith("HEART"):
        leader, cost_leader = "Heart 1", "Heart 1" if h_first else None
    elif verdict.startswith("DIAMOND"):
        leader, cost_leader = "Diamond 1", "Diamond 1" if d_first else None
    elif "HEART_COST_LEADER" in verdict:
        leader, cost_leader = "both", "Heart 1"
    elif "DIAMOND_COST_LEADER" in verdict:
        leader, cost_leader = "both", "Diamond 1"
    elif "COST_TIE" in verdict:
        leader, cost_leader = "both", "tie"

    interpretation = (
        f"{reason}. post-SD4 helper leak confirmed={leak.get('confirmed')}. "
        f"Current material: Heart1={material.get('heart_1_now')} Diamond1={material.get('diamond_1_now')} "
        f"Spade2={material.get('spade_2_now')} Club1={material.get('club_1_now')}. "
        f"SD4 2D current_count={two_d.get('current_count')} (unique pre-SD5={two_d.get('hard')}); "
        f"5D current_count={five_d.get('current_count')}. "
        f"Search H {h_search.classification} / Search D {d_search.classification}. "
        "Equal 450s/500k envelopes. SD5 never expanded. Sunk-cost Heart history was not used as a prior."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "horizon": {
            "pre_sd4_hearts_leak": leak,
            "material": material,
            "horizon_ok": horizon_ok,
        },
        "heart_map": {
            "aggregate": h_agg,
            "detail_source0": {
                "hard_ranks": h_detail.get("hard_ranks"),
                "alternative_ranks": h_detail.get("alternative_ranks"),
                "components": h_detail.get("components"),
                "nearest_gates": h_detail.get("nearest_gates"),
            },
            "macro_a_77_components": None if a77 is None else backward_map(states[a77], "h")["components"],
            "macro_b_77_components": None if b77 is None else backward_map(states[b77], "h")["components"],
        },
        "diamond_map": {
            "aggregate": d_agg,
            "detail_source0": {
                "hard_ranks": d_detail.get("hard_ranks"),
                "alternative_ranks": d_detail.get("alternative_ranks"),
                "components": d_detail.get("components"),
                "nearest_gates": d_detail.get("nearest_gates"),
            },
            "sd4_2d": two_d,
            "unique_5d": five_d,
        },
        "heart_search": search_block(h_search, h_rebuilt, h_first, h_fix, h_search.classification),
        "diamond_search": search_block(d_search, d_rebuilt, d_first, d_fix, d_search.classification),
        "cross_target": cross,
        "comparison": {
            "operational_leader": leader,
            "cost_leader": cost_leader,
            "heart_class": h_search.classification,
            "diamond_class": d_search.classification,
            "heart_unique": h_search.unique,
            "diamond_unique": d_search.unique,
            "heart_time": h_search.elapsed_s,
            "diamond_time": d_search.elapsed_s,
            "equal_envelope": True,
        },
        "sources": {
            "n": len(rows),
            "cost_counts": dict(Counter(r["full_cost"] for r in rows)),
            "family_A": sum(1 for r in rows if r["family"] == "A"),
            "family_B": sum(1 for r in rows if r["family"] == "B"),
            "all_replay_ok": replay_ok,
        },
        "sd5_h": h_search.sd5_expanded,
        "sd5_d": d_search.sd5_expanded,
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "no_sunk_cost_bias": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
