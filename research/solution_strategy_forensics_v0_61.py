#!/usr/bin/env python3
"""v0.61: comparative strategy forensics, autonomous 198 vs canonical 172.

Analysis only. Does not change search policy or write a new solution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import parse_moves_file
from spider.packed_state import unpack_state
from spider.solution_forensics import (
    AUTO_MOVES,
    CANON_MOVES,
    compare_boundaries,
    epoch_waterfall,
    extract_epochs,
    instrumented_replay,
    load_opening,
    physical_labels,
    rehandling_summary,
    structural_view,
)

EXPERIMENT = "solution_strategy_forensics_v0_61"
BASE_SHA = "db18b944f9f612c2ab19ec54fde9f15a46b00218"
BRANCH = "agent/solution-strategy-forensics-v0-61"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
EPOCH_JSON = ROOT / "docs" / "research" / "solution_strategy_epoch_comparison_v0_61.json"
LIFE_JSON = ROOT / "docs" / "research" / "solution_strategy_card_lifecycle_v0_61.json"
V060 = ROOT / "docs" / "research" / "autonomous_cost_optimisation_v0_60.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def slim_lifecycle(life: dict) -> dict:
    keep = (
        "label", "suit", "rank", "initial", "initial_zone", "deal_row",
        "first_exposure_g", "first_move_g", "move_actions", "paid_actions",
        "zero_cost_actions", "first_same_suit_attach_g", "durable_component_g",
        "foundation_g", "paid_after_attach", "mixed_park_g",
    )
    return {lab: {k: rec.get(k) for k in keep} for lab, rec in life.items()}


def slim_epoch(ep: dict) -> dict:
    def slim_view(v):
        if not isinstance(v, dict):
            return v
        out = {k: v.get(k) for k in (
            "g", "stock_rows", "foundations", "foundation_suits", "face_down",
            "empty_n", "legal_tableau", "same_suit_bonds", "run_compression",
            "longest_run", "merge_edges", "n_ready", "ready_suits",
            "nearest_horizon", "nearest_suits", "remaining_cost", "by_suit",
        )}
        return out
    return {
        "label": ep.get("label"),
        "stock_rows": ep.get("stock_rows"),
        "is_deal": bool(ep.get("is_deal")),
        "delta_g": ep.get("delta_g"),
        "paid": ep.get("paid"),
        "zero_cost": ep.get("zero_cost"),
        "tableau_n": ep.get("tableau_n"),
        "fd_delta": ep.get("fd_delta"),
        "bonds_delta": ep.get("bonds_delta"),
        "foundations_enter": ep.get("foundations_enter"),
        "foundations_exit": ep.get("foundations_exit"),
        "empty_enter": ep.get("empty_enter"),
        "empty_exit": ep.get("empty_exit"),
        "enter": slim_view(ep.get("enter")),
        "exit": slim_view(ep.get("exit")),
        "remaining_cost_after": ep.get("remaining_cost_after"),
    }


def cheap_f1_appendix() -> dict | None:
    if not V060.exists():
        return None
    data = json.loads(V060.read_text(encoding="utf-8"))
    rec = ((data.get("foundations") or {}).get("cheap") or {}).get("1")
    if not rec or not rec.get("ordered_digest"):
        return None
    st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    view = structural_view(st)
    view["g"] = rec.get("g")
    view["note"] = "v0.60 cheapest F1 snapshot; not a complete solution"
    return view


def main() -> dict:
    opening, raw, labels = load_opening()
    if len(labels) != 104 or len(set(labels.values())) != 104:
        raise SystemExit("FORENSICS_CONTRACT_FAILURE: physical identity")
    auto_actions = parse_moves_file(AUTO_MOVES)
    canon_actions = parse_moves_file(CANON_MOVES)
    print("REPLAY autonomous", flush=True)
    auto = instrumented_replay(opening, auto_actions, labels, expected_g=198)
    print("REPLAY canonical", flush=True)
    canon = instrumented_replay(opening, canon_actions, labels, expected_g=172)
    print("EPOCHS", flush=True)
    auto_ep = extract_epochs(auto, opening, auto_actions, labels)
    canon_ep = extract_epochs(canon, opening, canon_actions, labels)
    waterfall = epoch_waterfall(auto_ep, canon_ep)
    print("WATERFALL cum", waterfall[-1]["cumulative_gap"], flush=True)
    bounds = compare_boundaries(auto_ep, canon_ep)
    rh_auto = rehandling_summary(auto)
    rh_canon = rehandling_summary(canon)

    def f_table(tr):
        return [
            {
                "n": rec["n"],
                "g": rec["g"],
                "suit": rec["suit"],
                "stock_rows": rec["stock_rows"],
                "action_index": rec["action_index"],
                "via": rec["via"],
                "face_down": rec.get("face_down"),
                "empty_n": rec.get("empty_n"),
                "observed_remaining_cost": tr["g"] - rec["g"],
            }
            for rec in tr["foundations"]
        ]

    def bucket_delta():
        keys = sorted(set(auto["bucket_mw"]) | set(canon["bucket_mw"]))
        rows = []
        cum = 0
        for k in keys:
            a = int(auto["bucket_mw"].get(k, 0))
            c = int(canon["bucket_mw"].get(k, 0))
            d = a - c
            cum += d
            rows.append({"bucket": k, "auto": a, "canon": c, "delta_198_minus_172": d})
        return {"rows": rows, "sum_delta": cum}

    post5_auto = next(ep for ep in auto_ep if ep["label"] == "post-SD5")
    post5_canon = next(ep for ep in canon_ep if ep["label"] == "post-SD5")
    sd5_auto = next(ep for ep in auto_ep if ep["label"] == "SD5")
    sd5_canon = next(ep for ep in canon_ep if ep["label"] == "SD5")

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "contract": {
            "auto_g": auto["g"],
            "canon_g": canon["g"],
            "auto_deals": auto["n_deals"],
            "canon_deals": canon["n_deals"],
            "auto_solved": auto["solved"],
            "canon_solved": canon["solved"],
            "physical_cards": auto["n_physical"],
            "gap": auto["g"] - canon["g"],
        },
        "counts": {
            "auto_tableau": auto["tableau_commands"],
            "canon_tableau": canon["tableau_commands"],
            "auto_zero_cost": auto["zero_cost_commands"],
            "canon_zero_cost": canon["zero_cost_commands"],
            "auto_explicit": auto["n_actions"],
            "canon_explicit": canon["n_actions"],
        },
        "waterfall": waterfall,
        "foundations_auto": f_table(auto),
        "foundations_canon": f_table(canon),
        "rehandling_auto": rh_auto,
        "rehandling_canon": rh_canon,
        "bucket_mw_auto": auto["bucket_mw"],
        "bucket_mw_canon": canon["bucket_mw"],
        "deals_auto": auto["deal_events"],
        "deals_canon": canon["deal_events"],
        "post_sd5": {
            "auto_enter_g": post5_auto["enter"]["g"],
            "canon_enter_g": post5_canon["enter"]["g"],
            "auto_remaining": post5_auto["enter"]["remaining_cost"],
            "canon_remaining": post5_canon["enter"]["remaining_cost"],
            "auto_delta": post5_auto["delta_g"],
            "canon_delta": post5_canon["delta_g"],
            "auto_tableau_n": post5_auto["tableau_n"],
            "canon_tableau_n": post5_canon["tableau_n"],
            "auto_zero_cost": post5_auto["zero_cost"],
            "canon_zero_cost": post5_canon["zero_cost"],
            "auto": post5_auto["enter"],
            "canon": post5_canon["enter"],
            "sd5_land_auto": sd5_auto["exit"],
            "sd5_land_canon": sd5_canon["exit"],
        },
        "cheap_f1_v060": cheap_f1_appendix(),
        "exclusive_bucket_waterfall": bucket_delta(),
        "verdict": "FORENSICS_IDENTIFIES_GENERALISABLE_GAP",
        "policy_unchanged": True,
        "no_new_solution": True,
        "hypotheses": [
            {
                "rank": 1,
                "name": "rehandling_aware_economy",
                "genericity": "GENERAL",
                "mechanism": "Penalise repeat paid movement of already-attached cards in ECONOMY/harvest; prefer durable placements.",
            },
            {
                "rank": 2,
                "name": "deal_reception_shaping",
                "genericity": "PLAUSIBLY_GENERAL",
                "mechanism": "Score DEAL_NOW roots by observed landings (rank_ok, same-suit, mixed_block, legal_after), not cheapest g alone.",
            },
            {
                "rank": 3,
                "name": "excavation_gated_foundation_cashout",
                "genericity": "PLAUSIBLY_GENERAL",
                "mechanism": "Seek midgame foundations only when face-down/mobility are healthy; do not harvest cheapest-g F1.",
            },
            {
                "rank": 4,
                "name": "early_excavation_vs_cheapest_g",
                "genericity": "PLAUSIBLY_GENERAL",
                "mechanism": "Keep a high-excavation cohort alongside cheapest-g so early fd work is not starved.",
            },
            {
                "rank": 5,
                "name": "low_cover_ka_topology",
                "genericity": "PLAUSIBLY_GENERAL",
                "mechanism": "Post-stock, prefer low cover and small K/A gaps over raw bond count or longest run.",
            },
        ],
    }
    _write_json(RESULT, _jsonable(payload))
    _write_json(
        EPOCH_JSON,
        _jsonable(
            {
                "waterfall": waterfall,
                "auto_epochs": [slim_epoch(ep) for ep in auto_ep],
                "canon_epochs": [slim_epoch(ep) for ep in canon_ep],
                "boundaries": [
                    {
                        "label": b["label"],
                        "auto_g": (b["auto"] or {}).get("g"),
                        "canon_g": (b["canon"] or {}).get("g"),
                        "auto_remaining": b["auto_remaining"],
                        "canon_remaining": b["canon_remaining"],
                        "auto_fd": (b["auto"] or {}).get("face_down"),
                        "canon_fd": (b["canon"] or {}).get("face_down"),
                        "auto_empty": (b["auto"] or {}).get("empty_n"),
                        "canon_empty": (b["canon"] or {}).get("empty_n"),
                        "auto_bonds": (b["auto"] or {}).get("same_suit_bonds"),
                        "canon_bonds": (b["canon"] or {}).get("same_suit_bonds"),
                        "auto_n_ready": (b["auto"] or {}).get("n_ready"),
                        "canon_n_ready": (b["canon"] or {}).get("n_ready"),
                        "auto_F": (b["auto"] or {}).get("foundations"),
                        "canon_F": (b["canon"] or {}).get("foundations"),
                        "auto_legal": (b["auto"] or {}).get("legal_tableau"),
                        "canon_legal": (b["canon"] or {}).get("legal_tableau"),
                        "auto_suits": (b["auto"] or {}).get("by_suit"),
                        "canon_suits": (b["canon"] or {}).get("by_suit"),
                    }
                    for b in bounds
                ],
            }
        ),
    )
    _write_json(
        LIFE_JSON,
        _jsonable(
            {
                "auto": slim_lifecycle(auto["lifecycle"]),
                "canon": slim_lifecycle(canon["lifecycle"]),
            }
        ),
    )
    print("WROTE", RESULT, flush=True)
    return payload


if __name__ == "__main__":
    main()
