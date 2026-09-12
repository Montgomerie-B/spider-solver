#!/usr/bin/env python3
"""v0.50: audit whether v0.49 TAIL4 joins auto-removed Foundation 2.

Do not rewrite v0.49 reports. Do not search Spades, Hearts, rank 5, or Foundation 3.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import replay_actions
from spider.simple_club_diamond_tail3_ready import tail3_already, tail4_ready
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, opening_state
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import format_moves_text
from spider.simple_tail4_auto_removal import (
    CLUB_T3,
    DIA_T3,
    EXPECTED_CLUB,
    EXPECTED_DIA,
    FOUNDATION_AUTO_REMOVED,
    audit_immediate_joins,
    harvest_foundation2,
    load_v049_tail3,
    reconstruct_tail4_ready_preview,
    reproduce_accounting_bug,
)

EXPERIMENT = "tail4_auto_removal_audit_v0_50"
BASE_SHA = "1d8537e28094729dd37f312ade6868dace1e41c2"
BRANCH = "agent/tail4-auto-removal-audit-v0-50"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CLUB_OUT = ROOT / "docs" / "research" / "club_tail4_transition_v0_50.json"
CLUB_READY = ROOT / "docs" / "research" / "club_tail4_ready_v0_50.json"
DIA_READY = ROOT / "docs" / "research" / "diamond_tail4_ready_v0_50.json"
DIA_OUT = ROOT / "docs" / "research" / "diamond_tail4_transition_v0_50.json"
F2_OUT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_50.json"
CLUB_FIX = ROOT / "solutions" / "4925153_v0_50_club_foundation2.moves.txt"
DIA_FIX = ROOT / "solutions" / "4925153_v0_50_diamond_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim_t(rows, limit=None):
    keys = (
        "class",
        "g",
        "source_g",
        "join",
        "full_actions",
        "ordered_digest",
        "symmetry_digest",
        "foundation_count",
        "foundation_suits",
        "ka_ok",
        "tail4_present",
        "upper_run",
        "fd",
        "empties",
        "suit",
    )
    out = []
    for r in rows if limit is None else rows[:limit]:
        out.append({k: r[k] for k in keys if k in r})
    return out


def choose_verdict(p: dict) -> tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.49 TAIL3 portfolios failed replay"
    if p.get("contract_n", 0) > 0 and not p.get("club_f2") and not p.get("dia_f2") and not p.get("persists"):
        return "TAIL4_ACCOUNTING_CONTRACT_FAILURE", "joins produced neither TAIL4 nor Foundation 2"
    club_f2 = p.get("club_f2_n", 0)
    dia_f2 = p.get("dia_f2_n", 0)
    persists = p.get("persists_n", 0)
    bug = p.get("bug_reproduced")
    if club_f2 and dia_f2:
        return "BOTH_SUITS_REACH_FOUNDATION2", "Club and Diamond 3-2-A onto K-4 auto-removed Foundation 2"
    if club_f2:
        return "CLUB_FOUNDATION2_WAS_HIDDEN_SUCCESS", "Club 3-2-A onto K-4 auto-removed Foundation 2; v0.49 missed it"
    if dia_f2:
        return "DIAMOND_FOUNDATION2_WAS_HIDDEN_SUCCESS", "Diamond 3-2-A onto K-4 auto-removed Foundation 2; v0.49 missed it"
    if persists and bug:
        return "TAIL4_ACCOUNTING_BUG_CONFIRMED_NO_REAL_FOUNDATION", "bug reproduced on synthetic K-4, but v0.49 READY states persist TAIL4"
    if persists:
        return "TAIL4_PERSISTS_NO_FOUNDATION2", "legal 4-3-2-A remains in tableau; no auto-removal"
    if bug:
        return "TAIL4_ACCOUNTING_BUG_CONFIRMED_NO_REAL_FOUNDATION", "synthetic defect confirmed; no live Foundation 2 on v0.49 states"
    return "INCONCLUSIVE", "audit finished without a classified outcome"


def next_recommendation(verdict: str) -> str:
    if verdict in (
        "CLUB_FOUNDATION2_WAS_HIDDEN_SUCCESS",
        "DIAMOND_FOUNDATION2_WAS_HIDDEN_SUCCESS",
        "BOTH_SUITS_REACH_FOUNDATION2",
    ):
        return (
            "Foundation 2 is already in hand. Replan from the exact Foundation-2 frontier. "
            "Do not search TAIL4, Spades, Hearts, or Foundation 3."
        )
    if verdict in ("TAIL4_PERSISTS_NO_FOUNDATION2", "TAIL4_ACCOUNTING_BUG_CONFIRMED_NO_REAL_FOUNDATION"):
        return (
            "v0.49 TAIL4_READY comparison stands. Next: equal Club/Diamond TAIL4_READY searches "
            "from those boundaries, using the corrected join classifier. Do not resume Spades."
        )
    return "Keep the TAIL4 auto-removal correction. Do not search Foundation 3 or Spades."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.50 — TAIL4 Auto-Removal Audit",
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
        "## 2. Bug reproduction",
        "",
        "```json",
        json.dumps(payload.get("bug"), indent=2)[:2000],
        "```",
        "",
        "## 3. Club",
        "",
        "```json",
        json.dumps(payload.get("club"), indent=2)[:3500],
        "```",
        "",
        "## 4. Diamond",
        "",
        "```json",
        json.dumps(payload.get("diamond"), indent=2)[:3500],
        "```",
        "",
        "## 5. Foundation 2",
        "",
        "```json",
        json.dumps(payload.get("foundation2"), indent=2)[:2500],
        "```",
        "",
        "v0.49 reports were not rewritten. No Spade/Heart/rank-5/Foundation-3 search.",
        "",
        "## 6. Files",
        "",
        json.dumps(payload.get("files"), indent=2),
        "",
        "## 7. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()

    print("BUG REPRO", flush=True)
    bug = reproduce_accounting_bug()
    print(f"BUG reproduced={bug['bug_reproduced']} old={bug['old_helper']} new={bug['new_helper_class']}", flush=True)

    print("LOAD CLUB TAIL3", flush=True)
    club_bundle = load_v049_tail3(CLUB_T3, opening, "c", EXPECTED_CLUB)
    print(
        f"CLUB n={club_bundle['replayed']} fail={club_bundle['replay_fail']} ready={club_bundle['tail4_ready_n']}",
        flush=True,
    )
    print("RECONSTRUCT CLUB TAIL4_READY (v0.49 IMMEDIATE included depth<=1)", flush=True)
    club_reconstructed = []
    club_preview_counts = Counter()
    for rec in club_bundle["states"]:
        hit = reconstruct_tail4_ready_preview(rec, opening, "c")
        club_preview_counts[hit["status"]] += 1
        if hit["status"] in ("TAIL4_READY_IMMEDIATE", "TAIL4_READY_WITHIN_5"):
            club_reconstructed.append(hit)
    print(f"CLUB preview {dict(club_preview_counts)} reconstructed={len(club_reconstructed)}", flush=True)
    _write_json(
        CLUB_READY,
        {"experiment": EXPERIMENT, "n": len(club_reconstructed), "counts": dict(club_preview_counts), "states": club_reconstructed},
    )
    club_ready_rows = [
        {
            "g": hit["g"],
            "full_actions": hit["full_actions"],
            "ordered_digest": hit["ordered_digest"],
            "symmetry_digest": hit["symmetry_digest"],
            "tail4_ready": True,
        }
        for hit in club_reconstructed
    ]
    print("AUDIT CLUB JOINS", flush=True)
    club_audit = audit_immediate_joins(club_ready_rows, opening, "c")
    print(
        f"CLUB joins={club_audit['n_joins']} classes={club_audit['classes']} upper={club_audit['upper_runs']} "
        f"f2={club_audit['cheapest_f2']}",
        flush=True,
    )
    _write_json(
        CLUB_OUT,
        {
            "experiment": EXPERIMENT,
            "suit": "c",
            "n_ready": club_audit["n_ready"],
            "n_joins": club_audit["n_joins"],
            "classes": club_audit["classes"],
            "upper_runs": club_audit["upper_runs"],
            "preview_counts": dict(club_preview_counts),
            "transitions": _slim_t(club_audit["transitions"]),
        },
    )

    print("LOAD DIAMOND TAIL3", flush=True)
    dia_bundle = load_v049_tail3(DIA_T3, opening, "d", EXPECTED_DIA)
    print(
        f"DIA n={dia_bundle['replayed']} fail={dia_bundle['replay_fail']} ready={dia_bundle['tail4_ready_n']}",
        flush=True,
    )
    print("AUDIT DIAMOND IMMEDIATE", flush=True)
    dia_imm = audit_immediate_joins(dia_bundle["states"], opening, "d")
    print(f"DIA immediate ready={dia_imm['n_ready']} joins={dia_imm['n_joins']} classes={dia_imm['classes']}", flush=True)

    print("RECONSTRUCT DIAMOND WITHIN-5", flush=True)
    reconstructed = []
    preview_counts = Counter()
    for rec in dia_bundle["states"]:
        hit = reconstruct_tail4_ready_preview(rec, opening, "d")
        preview_counts[hit["status"]] += 1
        if hit["status"] in ("TAIL4_READY_IMMEDIATE", "TAIL4_READY_WITHIN_5"):
            reconstructed.append(hit)
    print(f"DIA preview {dict(preview_counts)} reconstructed={len(reconstructed)}", flush=True)
    _write_json(
        DIA_READY,
        {"experiment": EXPERIMENT, "n": len(reconstructed), "counts": dict(preview_counts), "states": reconstructed},
    )

    print("AUDIT DIAMOND READY JOINS", flush=True)
    dia_ready_rows = []
    for hit in reconstructed:
        dia_ready_rows.append(
            {
                "g": hit["g"],
                "full_actions": hit["full_actions"],
                "ordered_digest": hit["ordered_digest"],
                "symmetry_digest": hit["symmetry_digest"],
                "tail4_ready": True,
            }
        )
    dia_audit = audit_immediate_joins(dia_ready_rows, opening, "d")
    print(
        f"DIA joins={dia_audit['n_joins']} classes={dia_audit['classes']} upper={dia_audit['upper_runs']} "
        f"f2={dia_audit['cheapest_f2']}",
        flush=True,
    )
    _write_json(
        DIA_OUT,
        {
            "experiment": EXPERIMENT,
            "suit": "d",
            "n_ready": dia_audit["n_ready"],
            "n_joins": dia_audit["n_joins"],
            "classes": dia_audit["classes"],
            "upper_runs": dia_audit["upper_runs"],
            "immediate": dia_imm,
            "preview_counts": dict(preview_counts),
            "transitions": _slim_t(dia_audit["transitions"]),
        },
    )

    all_f2 = list(club_audit["foundation2"]) + list(dia_audit["foundation2"])
    portfolio = harvest_foundation2(all_f2)
    fixtures = {}
    if portfolio:
        _write_json(
            F2_OUT,
            {
                "experiment": EXPERIMENT,
                "n": len(portfolio),
                "cheapest": portfolio[0]["g"],
                "states": _slim_t(portfolio),
            },
        )
        by_suit = {}
        for w in portfolio:
            s = w.get("suit")
            if s not in by_suit or w["g"] < by_suit[s]["g"]:
                by_suit[s] = w
        if "c" in by_suit:
            CLUB_FIX.parent.mkdir(parents=True, exist_ok=True)
            CLUB_FIX.write_text(
                format_moves_text(as_actions(by_suit["c"]["full_actions"]), header="# v0.50 Club Foundation 2 (auto-removed K-A)\n"),
                encoding="utf-8",
            )
            fixtures["c"] = CLUB_FIX.relative_to(ROOT).as_posix()
        if "d" in by_suit:
            DIA_FIX.parent.mkdir(parents=True, exist_ok=True)
            DIA_FIX.write_text(
                format_moves_text(as_actions(by_suit["d"]["full_actions"]), header="# v0.50 Diamond Foundation 2 (auto-removed K-A)\n"),
                encoding="utf-8",
            )
            fixtures["d"] = DIA_FIX.relative_to(ROOT).as_posix()
        from spider.metrics import parse_moves_file

        for suit, fpath in (("c", CLUB_FIX), ("d", DIA_FIX)):
            if not fpath.exists():
                continue
            end = opening.clone()
            acts = parse_moves_file(fpath)
            cost = replay_actions(end, acts)
            print(
                f"FIXTURE {suit} mw={cost} fdn={len(end.foundations)} suits={[r[0].suit for r in end.foundations]}",
                flush=True,
            )

    persists_n = club_audit["persists_n"] + dia_audit["persists_n"]
    contract_n = club_audit["contract_n"] + dia_audit["contract_n"]
    payload_pre = {
        "all_replay_ok": club_bundle["all_replay_ok"] and dia_bundle["all_replay_ok"],
        "bug_reproduced": bug["bug_reproduced"],
        "club_f2": club_audit["foundation2_n"] > 0,
        "dia_f2": dia_audit["foundation2_n"] > 0,
        "club_f2_n": club_audit["foundation2_n"],
        "dia_f2_n": dia_audit["foundation2_n"],
        "persists": persists_n > 0,
        "persists_n": persists_n,
        "contract_n": contract_n,
    }
    verdict, reason = choose_verdict(payload_pre)
    cheapest_club = club_audit["cheapest_f2"]
    cheapest_dia = dia_audit["cheapest_f2"]
    cheapest = None
    if cheapest_club is not None and cheapest_dia is not None:
        cheapest = min(cheapest_club, cheapest_dia)
    elif cheapest_club is not None:
        cheapest = cheapest_club
    else:
        cheapest = cheapest_dia
    f2_suit = None
    if cheapest_club is not None and (cheapest_dia is None or cheapest_club <= cheapest_dia):
        f2_suit = "c" if cheapest_dia is None or cheapest_club < cheapest_dia else "both"
    elif cheapest_dia is not None:
        f2_suit = "d"
    interpretation = (
        f"{reason}. Club reconstructed {len(club_reconstructed)} READY joins={club_audit['n_joins']} "
        f"F2={club_audit['foundation2_n']} persist={club_audit['persists_n']} cheap={cheapest_club}. "
        f"Diamond reconstructed {len(reconstructed)} READY joins={dia_audit['n_joins']} "
        f"F2={dia_audit['foundation2_n']} persist={dia_audit['persists_n']} cheap={cheapest_dia}. "
        f"v0.49 reports unchanged."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "bug": {k: bug[k] for k in bug if k != "classified"},
        "club": {
            "replayed": club_bundle["replayed"],
            "all_replay_ok": club_bundle["all_replay_ok"],
            "tail4_ready_n": club_bundle["tail4_ready_n"],
            "preview_counts": dict(club_preview_counts),
            "reconstructed": len(club_reconstructed),
            "n_joins": club_audit["n_joins"],
            "classes": club_audit["classes"],
            "upper_runs": club_audit["upper_runs"],
            "foundation2_n": club_audit["foundation2_n"],
            "persists_n": club_audit["persists_n"],
            "contract_n": club_audit["contract_n"],
            "cheapest_f2": cheapest_club,
        },
        "diamond": {
            "replayed": dia_bundle["replayed"],
            "all_replay_ok": dia_bundle["all_replay_ok"],
            "immediate_ready_n": dia_bundle["tail4_ready_n"],
            "preview_counts": dict(preview_counts),
            "reconstructed": len(reconstructed),
            "n_joins": dia_audit["n_joins"],
            "classes": dia_audit["classes"],
            "upper_runs": dia_audit["upper_runs"],
            "foundation2_n": dia_audit["foundation2_n"],
            "persists_n": dia_audit["persists_n"],
            "contract_n": dia_audit["contract_n"],
            "cheapest_f2": cheapest_dia,
        },
        "foundation2": {
            "reached": bool(portfolio),
            "n": len(portfolio),
            "cheapest": cheapest,
            "suit": f2_suit,
            "fixtures": fixtures,
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "club": CLUB_OUT.relative_to(ROOT).as_posix(),
            "club_ready": CLUB_READY.relative_to(ROOT).as_posix() if CLUB_READY.exists() else None,
            "diamond_ready": DIA_READY.relative_to(ROOT).as_posix() if DIA_READY.exists() else None,
            "diamond": DIA_OUT.relative_to(ROOT).as_posix(),
            "foundation2": F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None,
            "club_fixture": fixtures.get("c"),
            "diamond_fixture": fixtures.get("d"),
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "v049_unchanged": True,
        "all_replay_ok": payload_pre["all_replay_ok"],
        "bug_reproduced": bug["bug_reproduced"],
        "club_f2": payload_pre["club_f2"],
        "dia_f2": payload_pre["dia_f2"],
        "club_f2_n": payload_pre["club_f2_n"],
        "dia_f2_n": payload_pre["dia_f2_n"],
        "persists": payload_pre["persists"],
        "persists_n": persists_n,
        "contract_n": contract_n,
    }
    payload["files"]["club_ready"] = CLUB_READY.relative_to(ROOT).as_posix() if CLUB_READY.exists() else None
    payload["files"]["diamond_ready"] = DIA_READY.relative_to(ROOT).as_posix() if DIA_READY.exists() else None
    payload["files"]["foundation2"] = F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
