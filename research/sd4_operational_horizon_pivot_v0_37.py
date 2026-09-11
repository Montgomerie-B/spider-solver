#!/usr/bin/env python3
"""v0.37: SD4 operational-horizon pivot — unlock JH then unique 9H.

SD4 is legal. SD5 is never taken. Predicted four-action macros are tested
through engine legality, then an independent depth-6 exact search.
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
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import gate1_progress
from spider.simple_gate3 import verify_gate3_chain
from spider.simple_h9_cut import mandatory_rank_status
from spider.simple_progressive_solver import format_moves_text
from spider.simple_sd4_horizon import (
    EXPECTED_SD4,
    MACRO_A,
    MACRO_B,
    apply_macro,
    continuation_lb_audit,
    jack_onto_any_queen_ok,
    search_h9_from_gate2,
    verify_sd4_row,
)
from spider.simple_two_gate import verify_ah_release_legality
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "sd4_operational_horizon_pivot_v0_37"
BASE_SHA = "b30850880e1cc76789478e3824ff827269533a71"
BRANCH = "agent/sd4-operational-horizon-pivot-v0-37"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V36_G1 = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate1_sources.json"
V36_G2 = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate2_portfolio.json"
V35_G2 = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
H9_PORT = ROOT / "docs" / "research" / f"{EXPERIMENT}_h9_portfolio.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_37_h9_best.moves.txt"


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


def load_union(opening: SpiderState):
    g1 = json.loads(V36_G1.read_text(encoding="utf-8"))
    g2 = json.loads(V36_G2.read_text(encoding="utf-8"))
    v35 = json.loads(V35_G2.read_text(encoding="utf-8"))
    best = {}
    rows = []
    failures = []

    def consider(full, g_hint, lineage):
        end = opening.clone()
        cost = replay_actions(end, full)
        ident = pack_state(end)
        prog = gate1_progress(end)
        chain = verify_gate3_chain(end)
        ok = (
            chain["valid"]
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and stock_rows(end) == 2
            and prog.get("fd_blockers") == 1
            and prog.get("top_fd") == "JH"
            and not prog.get("face_up")
            and prog.get("column_0") == 1
            and "AH" in [pretty_card(c) for c in end.columns[1].face_up]
            and not prog.get("can_move_packet")
        )
        rec = {
            "ok": ok,
            "full_cost": cost,
            "g": cost,
            "lineage": lineage,
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "stock_rows": stock_rows(end),
            "fd_blockers": prog.get("fd_blockers"),
            "ah_movable": bool(prog.get("can_move_packet")),
            "replay_ok": ok and (g_hint is None or cost == g_hint),
        }
        if not rec["replay_ok"]:
            failures.append({"lineage": lineage, "ok": ok, "cost": cost, "hint": g_hint})
            return
        prev = best.get(ident)
        if prev is not None and cost >= prev:
            return
        best[ident] = cost
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx] = rec
        else:
            rows.append(rec)

    for rec in v35["states"]:
        consider(as_actions(rec["full_actions"]), rec.get("full_cost"), "v0.35")
    g1_states = g1["states"]
    for rec in g2["states"]:
        origin = rec.get("origin")
        if origin is None or origin >= len(g1_states):
            failures.append({"lineage": "v0.36", "reason": "bad origin", "origin": origin})
            continue
        full = as_actions(g1_states[origin]["full_actions"]) + as_actions(rec.get("actions_to_gate2") or [])
        consider(full, rec.get("g"), "v0.36")

    rows.sort(key=lambda r: (r["full_cost"], r["ordered_digest"]))
    states = []
    paths = []
    gs = []
    for rec in rows:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(rec["full_cost"])
    counts = {}
    for r in rows:
        counts[str(r["full_cost"])] = counts.get(str(r["full_cost"]), 0) + 1
    print(
        f"UNION n={len(rows)} costs={counts} v35={sum(1 for r in rows if r['lineage']=='v0.35')} "
        f"v36={sum(1 for r in rows if r['lineage']=='v0.36')} failures={len(failures)}",
        flush=True,
    )
    return rows, states, paths, gs, failures


def count_2d(state: SpiderState) -> dict:
    tab = 0
    for col in state.columns:
        tab += sum(1 for c in list(col.face_down) + list(col.face_up) if pretty_card(c) == "2D")
    stock_names = [pretty_card(c) for c in state.stock]
    sd4 = [pretty_card(c) for c in state.stock[-10:]] if stock_rows(state) == 2 else []
    sd5 = [pretty_card(c) for c in state.stock[-20:-10]] if len(state.stock) >= 20 else []
    return {
        "tableau": tab,
        "stock": stock_names.count("2D"),
        "sd4": sd4.count("2D"),
        "sd5": sd5.count("2D"),
        "sd4_has_2d": "2D" in sd4,
        "sd5_has_2d": "2D" in sd5,
    }


def choose_verdict(replay_ok, row_ok, a_hits, b_hits, search_hits, explosion, n_src):
    if not replay_ok:
        return "SOURCE_REPLAY_FAILURE", "Gate-2 union failed replay"
    if not row_ok:
        return "SD4_ROW_ORIENTATION_MISMATCH", "engine SD4 row differs from predicted orientation"
    if explosion and not (a_hits or b_hits or search_hits):
        return "SD4_H9_SEARCH_STATE_EXPLOSION", "resource limits bound before 9H"
    a_all = a_hits == n_src and n_src > 0
    b_all = b_hits == n_src and n_src > 0
    if a_hits and b_hits:
        return "SD4_UNLOCKS_H9_MULTIPLE_ROUTES", f"macros A ({a_hits}/{n_src}) and B ({b_hits}/{n_src}) both expose 9H"
    if a_hits and a_all and not search_hits:
        return "SD4_UNLOCKS_H9_AS_PREDICTED", "predicted macro A unlocks 9H"
    if (a_hits or b_hits) and search_hits:
        return "SD4_UNLOCKS_H9_MULTIPLE_ROUTES", "predicted macro(s) and independent search expose 9H"
    if a_hits or b_hits:
        which = "A" if a_hits else "B"
        return "SD4_UNLOCKS_H9_AS_PREDICTED", f"predicted macro {which} unlocks 9H"
    if search_hits:
        return "SD4_UNLOCKS_H9_VIA_DIFFERENT_ROUTE", "independent short search exposed 9H without the predicted macros succeeding"
    return "SD4_DOES_NOT_UNLOCK_H9_IN_SHORT_ENVELOPE", "no 9H exposure in macros or depth-6 envelope"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("SD4_UNLOCKS_H9"):
        return (
            "Heart operational unlock is at SD4 for this lineage. Next: choose the post-9H target "
            "— continue the Heart foundation, or reassess Diamonds now that 2D is the AH parking spot. "
            "Do not take SD5 yet. Do not inspect the human route."
        )
    return (
        "SD4 did not unlock 9H in the short envelope. Diagnose the failed macros before widening. "
        "Do not take SD5. Do not inspect the human route."
    )


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.37 — SD4 Operational-Horizon Pivot",
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
        "## 2. Sources",
        "",
        json.dumps(payload.get("sources") or {}, indent=2)[:2000],
        "",
        "## 3. SD4 and macros",
        "",
        json.dumps({"sd4": payload.get("sd4"), "macros": payload.get("macros")}, indent=2)[:4000],
        "",
        "## 4. Search",
        "",
        json.dumps(payload.get("search") or {}, indent=2)[:2500],
        "",
        "## 5. Proof / lower bound",
        "",
        json.dumps(payload.get("proof") or {}, indent=2)[:2000],
        "",
        "## 6. H9 boundary",
        "",
        json.dumps(payload.get("h9") or {}, indent=2)[:2500],
        "",
        "## 7. Diamond interaction",
        "",
        json.dumps(payload.get("diamond") or {}, indent=2)[:2000],
        "",
        "## 8. Operational horizon",
        "",
        f"`{payload.get('operational_horizon')}`",
        "",
        "## 9. Portfolio",
        "",
        json.dumps(payload.get("portfolio") or {}, indent=2)[:1500],
        "",
        "## 10. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD5 expanded={payload.get('sd5_expanded')}.",
        "Gate 4 terminal. No Heart foundation search. No Diamond search. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()

    rows, states, paths, gs, failures = load_union(opening)
    replay_ok = bool(states) and all(r["ok"] and r["replay_ok"] for r in rows)
    print(f"SOURCES n={len(states)} replay_ok={replay_ok} fail={len(failures)}", flush=True)

    sd4 = verify_sd4_row(states[0]) if states else {"valid": False, "row": None}
    print(f"SD4_ROW valid={sd4.get('valid')} row={sd4.get('row')}", flush=True)
    jq = jack_onto_any_queen_ok()
    ah = verify_ah_release_legality()
    lb = continuation_lb_audit(states[0]) if states else {"valid": False}
    print(f"LB valid={lb.get('valid')} lb={lb.get('lb')} jq={jq['valid']} ah={ah['valid']}", flush=True)

    if states and not sd4.get("valid"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "verdict": "SD4_ROW_ORIENTATION_MISMATCH",
            "verdict_reason": sd4.get("mismatch"),
            "sd4": sd4,
            "sources": {"n": len(states)},
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT SD4_ROW_ORIENTATION_MISMATCH", flush=True)
        return payload

    a_hits = b_hits = 0
    a_fail = b_fail = None
    macro_rows = []
    print("PHASE_A macros on all sources", flush=True)
    for i, (st, g0, row) in enumerate(zip(states, gs, rows)):
        rec = {"source": i, "source_g": g0, "lineage": row["lineage"]}
        for name, macro in (("A", MACRO_A), ("B", MACRO_B)):
            child = st.clone()
            out = apply_macro(child, macro)
            rec[name] = out
            if out["legal"] and out["gate4"]:
                if name == "A":
                    a_hits += 1
                else:
                    b_hits += 1
            elif out["failure"] and name == "A" and a_fail is None:
                a_fail = out["failure"]
            elif out["failure"] and name == "B" and b_fail is None:
                b_fail = out["failure"]
        macro_rows.append(rec)
    print(f"PHASE_A A={a_hits}/{len(states)} B={b_hits}/{len(states)}", flush=True)

    remaining = 300.0 - (time.perf_counter() - started)
    print(f"PHASE_B exact depth-6 search budget={max(5.0, remaining):.0f}s", flush=True)
    search = search_h9_from_gate2(
        states,
        paths,
        gs,
        max_depth=6,
        max_unique=250_000,
        time_limit_s=max(5.0, remaining),
        rss_abort_mb=1024.0,
        harvest_slack=3,
        harvest_limit=256,
    )
    explosion = search.stop_reason in ("unique limit", "rss abort") and not search.witnesses
    print(
        f"SEARCH unique={search.unique} exp={search.expanded} inc={search.incumbent} "
        f"wit={len(search.witnesses)} first_t={search.first_h9_s} stop={search.stop_reason}",
        flush=True,
    )

    rebuilt = []
    for rec in search.witnesses:
        full = list(paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        prog = gate1_progress(end)
        col = prog.get("column_0")
        c3 = end.columns[2].face_up
        qh_jh = len(c3) >= 2 and pretty_card(c3[-1]) == "JH" and pretty_card(c3[-2]) == "QH"
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "continuation": cost - gs[rec["origin"]],
                "source_g": gs[rec["origin"]],
                "source_lineage": rows[rec["origin"]]["lineage"],
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "fd": face_down_count(end),
                "foundations": len(end.foundations),
                "empties": list(empty_column_indices(end)),
                "stock_rows": stock_rows(end),
                "face_up_col": [pretty_card(c) for c in end.columns[col].face_up] if col is not None else [],
                "face_down_col": [pretty_card(c) for c in end.columns[col].face_down] if col is not None else [],
                "mandatory_ranks": mandatory_rank_status(end),
                "qh_jh_same_suit": qh_jh,
                "c3_top": pretty_card(end.columns[2].face_up[-1]) if end.columns[2].face_up else None,
                "c4_top": pretty_card(end.columns[3].face_up[-1]) if end.columns[3].face_up else None,
                "c6_top": pretty_card(end.columns[5].face_up[-1]) if end.columns[5].face_up else None,
                "ordered_digest": pack_state(end).hex(),
                "full_replay_ok": bool(prog.get("face_up")) and pretty_card(end.columns[col].face_up[-1]) == "9H" and cost == rec["g"],
            }
        )

    # Also materialise cheapest macro witnesses so the portfolio includes A/B even if
    # search found the same states.
    for i, rec in enumerate(macro_rows):
        for name in ("A", "B"):
            out = rec[name]
            if not (out["legal"] and out["gate4"]):
                continue
            macro = MACRO_A if name == "A" else MACRO_B
            full = list(paths[i]) + list(macro)
            end = opening.clone()
            cost = replay_actions(end, full)
            ident = pack_state(end).hex()
            if any(w["ordered_digest"] == ident and w["full_cost"] <= cost for w in rebuilt):
                for w in rebuilt:
                    if w["ordered_digest"] == ident:
                        w.setdefault("macros", [])
                        if name not in w["macros"]:
                            w["macros"].append(name)
                continue
            prog = gate1_progress(end)
            col = prog.get("column_0")
            c3 = end.columns[2].face_up
            rebuilt.append(
                {
                    "origin": i,
                    "g": cost,
                    "full_cost": cost,
                    "continuation": cost - gs[i],
                    "source_g": gs[i],
                    "source_lineage": rows[i]["lineage"],
                    "depth": 4,
                    "actions": dump_actions(macro),
                    "full_actions": dump_actions(full),
                    "full_path_length": len(full),
                    "fd": face_down_count(end),
                    "foundations": len(end.foundations),
                    "empties": list(empty_column_indices(end)),
                    "stock_rows": stock_rows(end),
                    "face_up_col": [pretty_card(c) for c in end.columns[col].face_up] if col is not None else [],
                    "face_down_col": [pretty_card(c) for c in end.columns[col].face_down] if col is not None else [],
                    "mandatory_ranks": mandatory_rank_status(end),
                    "qh_jh_same_suit": len(c3) >= 2 and pretty_card(c3[-1]) == "JH" and pretty_card(c3[-2]) == "QH",
                    "c3_top": pretty_card(end.columns[2].face_up[-1]) if end.columns[2].face_up else None,
                    "c4_top": pretty_card(end.columns[3].face_up[-1]) if end.columns[3].face_up else None,
                    "c6_top": pretty_card(end.columns[5].face_up[-1]) if end.columns[5].face_up else None,
                    "ordered_digest": ident,
                    "full_replay_ok": True,
                    "macros": [name],
                    "via": f"macro_{name}",
                }
            )

    if rebuilt:
        h = min(w["full_cost"] for w in rebuilt)
        rebuilt = [w for w in rebuilt if w["full_cost"] <= h + 3]
        rebuilt.sort(key=lambda w: (w["full_cost"], w.get("full_path_length", 10**9), w.get("origin", 0)))
        rebuilt = rebuilt[:256]
    first = rebuilt[0] if rebuilt else None
    fixture = None
    if first:
        FIXTURE.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=(
                    f"# v0.37 first unique 9H via SD4\n"
                    f"# full_mw: {first['full_cost']}\n"
                    f"# continuation: {first.get('continuation')}\n"
                    f"# via: {first.get('via') or first.get('macros')}"
                ),
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    two_d = count_2d(states[0]) if states else {}
    ah_on_2d = False
    ah_release = None
    if first:
        end = opening.clone()
        replay_actions(end, as_actions(first["full_actions"]))
        c4 = end.columns[3].face_up
        ah_on_2d = len(c4) >= 2 and pretty_card(c4[-1]) == "AH" and pretty_card(c4[-2]) == "2D"
        dests = []
        if ah_on_2d:
            for dst in range(10):
                if dst == 3:
                    continue
                if end.can_move(3, dst, 1):
                    top = end.columns[dst].top()
                    dests.append("empty" if top is None else pretty_card(top))
            ah_release = {"legal_ah_dests": dests, "can_release_now": bool(dests)}

    bands = {}
    for w in rebuilt:
        bands[str(w["full_cost"])] = bands.get(str(w["full_cost"]), 0) + 1
    _write_json(
        H9_PORT,
        {
            "experiment": EXPERIMENT,
            "kind": "h9_portfolio",
            "h": None if not first else first["full_cost"],
            "n": len(rebuilt),
            "bands": bands,
            "states": rebuilt,
        },
    )

    n_src = len(states)
    verdict, reason = choose_verdict(
        replay_ok, bool(sd4.get("valid")), a_hits, b_hits, bool(search.witnesses), explosion, n_src
    )
    horizon = None
    if verdict.startswith("SD4_UNLOCKS_H9"):
        horizon = "HEART_OPERATIONAL_UNLOCK_AT_SD4"
    local_opt = bool(lb.get("valid") and first and first.get("continuation") == lb.get("lb"))
    interpretation = (
        f"{reason}. SD4 row {sd4.get('row')}. Macro A unlocked {a_hits}/{n_src}; "
        f"macro B unlocked {b_hits}/{n_src}. Continuation LB {lb.get('lb')} valid={lb.get('valid')}. "
        f"Independent depth-6 search incumbent={search.incumbent} first_t={search.first_h9_s}. "
        "SD5 never expanded. 9H is terminal. Diamond/2D is telemetry only. "
        "This is an operational-horizon statement for the explored Gate-2 lineage, "
        "not a proof that no pre-SD4 Heart route exists."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "operational_horizon": horizon,
        "sources": {
            "n": n_src,
            "cost_counts": {str(k): sum(1 for r in rows if r["full_cost"] == int(k)) for k in sorted({r["full_cost"] for r in rows})},
            "cost_min": None if not gs else min(gs),
            "cost_max": None if not gs else max(gs),
            "all_replay_ok": replay_ok,
            "failures": len(failures),
        },
        "sd4": sd4,
        "macros": {
            "A": {"hits": a_hits, "n": n_src, "pct": None if not n_src else round(100.0 * a_hits / n_src, 1), "first_failure": a_fail},
            "B": {"hits": b_hits, "n": n_src, "pct": None if not n_src else round(100.0 * b_hits / n_src, 1), "first_failure": b_fail},
            "labels": ["STOCK_MEDIATED_RELEASE", "STOCK_MEDIATED_SAME_SUIT_BUILD"],
        },
        "search": {
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "first_s": search.first_h9_s,
            "first_unique": search.first_h9_unique,
            "first_g": search.first_h9_g,
            "incumbent": search.incumbent,
            "max_depth": search.max_depth,
            "complete_depth": search.complete_depth,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "stop_reason": search.stop_reason,
            "sd5_expanded": search.sd5_expanded,
            "witnesses": len(search.witnesses),
        },
        "proof": {
            "continuation_lb": lb,
            "local_plus4_optimal": local_opt,
            "global_claim": False,
        },
        "h9": None
        if not first
        else {
            "full_cost": first["full_cost"],
            "full_path_length": first.get("full_path_length"),
            "continuation": first.get("continuation"),
            "source_g": first.get("source_g"),
            "stock_rows": first.get("stock_rows"),
            "fd": first.get("fd"),
            "foundations": first.get("foundations"),
            "empties": first.get("empties"),
            "face_up_col": first.get("face_up_col"),
            "face_down_col": first.get("face_down_col"),
            "mandatory_ranks": first.get("mandatory_ranks"),
            "qh_jh_same_suit": first.get("qh_jh_same_suit"),
            "c3_top": first.get("c3_top"),
            "c4_top": first.get("c4_top"),
            "c6_top": first.get("c6_top"),
            "full_replay_ok": first.get("full_replay_ok"),
            "fixture": fixture,
            "via": first.get("via") or first.get("macros"),
        },
        "diamond": {
            "gate2_2d": two_d,
            "sd4_2d_unique_pre_sd5": bool(two_d.get("sd4_has_2d") and not two_d.get("sd5_has_2d") and two_d.get("tableau", 1) == 0),
            "ah_temporarily_on_2d": ah_on_2d,
            "ah_release_from_2d": ah_release,
            "note": "Telemetry only. Diamond foundation is not searched.",
        },
        "portfolio": {
            "n": len(rebuilt),
            "bands": bands,
            "path": H9_PORT.relative_to(ROOT).as_posix(),
        },
        "min_mw": None if not first else first["full_cost"],
        "fixture": fixture,
        "sd5_expanded": search.sd5_expanded,
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "jack_any_queen": jq,
        "ah_any_two": ah,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
