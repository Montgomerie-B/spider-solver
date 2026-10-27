"""Two bounded tableau preparations before stock deal 5.

The search does not deal and does not continue after the deal. Each retained
pre-deal tableau is scored by applying the real next stock row once. No
suffix search is started, and neither solution file is rewritten.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.human_strategy.incumbent import verify_complete_solution
from spider.metrics import parse_moves_file, replay_actions_detailed
from spider.packed_state import pack_state
from spider.planner.backward_strategy import LocationKind, analyze_stock_backward, locate_all_cards
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.stock_reception import analyze_stock_reception
from spider.pre_sd5_preparation import (
    PROOF_CEILING,
    annotate_paths,
    assess_immediate_deal,
    pareto_shortlist,
    public_assessment,
    public_search,
    search_preparation,
    workspace_purpose,
)
from spider.research_actions import apply_action
from spider.rules import MW_RULES

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
OUT = ROOT / "artifacts" / "pre_sd5_v0_132" / "results.json"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

MAX_UNIQUE = 20_000
TIME_LIMIT_S = 30.0
RSS_ABORT_MB = 512.0
NEAR_DEPTH = 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def fifth_deal(actions) -> int:
    deals = 0
    for index, action in enumerate(actions):
        if action == ("deal",):
            deals += 1
            if deals == 5:
                return index
    raise SystemExit("route does not contain five deals")


def first_diamond(opening: SpiderState, actions) -> int:
    state = opening.clone()
    for index, action in enumerate(actions):
        before = len(state.foundations)
        apply_action(state, action)
        if len(state.foundations) > before and state.foundations[-1][0].suit == "d":
            return index
    raise SystemExit("route builds no diamond foundation")


def replay_label(path: Path, opening: SpiderState) -> dict:
    actions = parse_moves_file(path)
    state = opening.clone()
    detailed = replay_actions_detailed(state, actions)
    return {
        "path": path.name,
        "actions": len(actions),
        "mobilityware_moves": detailed["mobilityware_moves"],
        "solved": bool(state.is_solved() and len(state.foundations) == 8 and not state.stock),
        "foundations": len(state.foundations),
        "sha256": sha256(path),
    }


def mapping_proof() -> dict:
    cards = [Card(suit, rank) for suit in "shdc" for rank in range(1, 14)][:50]
    checked = []
    for length in (50, 40, 30, 20, 10):
        state = SpiderState([Column([], []) for _ in range(10)], cards[:length])
        located = [item for item in locate_all_cards(state) if item.kind == LocationKind.STOCK]
        mismatches = [
            index
            for index, item in enumerate(located)
            if item.column != index % 10 or item.depth != (length - 1 - index) // 10
        ]
        epoch_now = current_stock_epoch(state, 5)
        work = state.clone()
        engine_ok = True
        for _ in range(length // 10):
            expected = list(work.stock[-10:])
            work.deal(rules=MW_RULES)
            engine_ok = engine_ok and all(
                work.columns[column].face_up[-1] == card for column, card in enumerate(expected)
            )
        checked.append(
            {
                "stock_cards": length,
                "epoch_already_dealt": epoch_now,
                "next_stock_epoch": epoch_now + 1,
                "locate_mismatches": mismatches,
                "engine_matches_left_to_right": engine_ok,
            }
        )
    return {
        "confirmed": all(not row["locate_mismatches"] and row["engine_matches_left_to_right"] for row in checked),
        "engine": "SpiderState.deal writes stock[-10:] left to right onto columns 0..9",
        "previous_formula": "from_top % 10, which places stock[0] of a 50-card pile on column 9",
        "corrected_formula": "offset inside the 10-card chunk counted from the end; i % 10 when the length is a multiple of 10",
        "lengths": checked,
    }


def copy_labels(cards) -> list:
    seen = {}
    labels = []
    for card in cards:
        key = (card.suit, card.rank)
        seen[key] = seen.get(key, 0) + 1
        labels.append(f"{str(card).upper()}#{chr(ord('A') + seen[key] - 1)}")
    return labels


def column_snapshot(state: SpiderState) -> list:
    rows = []
    for index, column in enumerate(state.columns):
        top = column.face_up[-1] if column.face_up else None
        rows.append(
            {
                "column": index + 1,
                "top": None if top is None else str(top).upper(),
                "face_up": len(column.face_up),
                "face_down": len(column.face_down),
                "empty": column.is_empty(),
            }
        )
    return rows


def wish_rows(state: SpiderState) -> list:
    backward = analyze_stock_backward(state)
    return [
        {
            "column": wish.column + 1,
            "incoming": str(wish.incoming).upper(),
            "landing_now": wish.landing_now,
            "desired_top": wish.desired_top,
            "reason": wish.reason,
            "importance": wish.importance,
        }
        for wish in backward.receiver_wishes
    ]


def relation(item, reference) -> dict:
    pairs = (
        ("g_pre", item.g_pre, reference.g_pre, "min"),
        ("h_post", item.h_post, reference.h_post, "min"),
        ("same_suit_landings", item.same_suit_landings, reference.same_suit_landings, "max"),
        ("mobility", item.mobility, reference.mobility, "max"),
    )
    better = False
    worse = False
    axes = {}
    for name, left, right, direction in pairs:
        improved = left < right if direction == "min" else left > right
        declined = left > right if direction == "min" else left < right
        better = better or improved
        worse = worse or declined
        axes[name] = {"candidate": left, "canonical": right}
    if better and not worse:
        kind = "better_on_some_worse_on_none"
    elif worse and not better:
        kind = "worse_or_equal_on_all"
    elif not better and not worse:
        kind = "equal_on_recorded_axes"
    else:
        kind = "tradeoff"
    return {"kind": kind, "axes": axes, "complete_route": False}


def state_at(source: SpiderState, kernel, node: int) -> SpiderState:
    trial = source.clone()
    for action in kernel.reconstruct(node):
        apply_action(trial, action)
    return trial


def shortlist_rows(source, g0, found, portfolio, reference) -> list:
    annotate_paths(source, g0, found.kernel, portfolio.items)
    rows = []
    for item in portfolio.items:
        payload = public_assessment(item)
        payload["workspace"] = workspace_purpose(state_at(source, found.kernel, item.node))
        payload["compared_with_canonical_immediate_deal"] = relation(item, reference)
        rows.append(payload)
    return rows


def publish(found, portfolio, rows, interpretation: str) -> dict:
    payload = public_search(found, [])
    payload["shortlist"] = rows
    payload["pareto_front_size"] = portfolio.front_size
    payload["pareto_truncated"] = portfolio.truncated
    payload["interpretation"] = interpretation
    payload["complete_route_found"] = False
    return payload


def recommend(near: dict, last: dict, canonical_f: int) -> str:
    parts = [
        "No complete continuation and no suffix repair were run.",
        "The post-SD5 80,000-state and 90-second budgets were not increased.",
    ]
    if not last["canonical_reached"]:
        parts.append(
            "The last-preparation search did not reconstruct the canonical pre-deal tableau, so that probe is inconclusive rather than a proof that the known preparation is unreachable."
        )
    else:
        parts.append(
            f"The last-preparation search did reach the canonical pre-deal tableau at g={last['canonical_g']}."
        )
    parts.append(
        f"The exhausted three-move neighborhood kept {canonical_f} as its best immediate-deal bound. "
        "Early-deal samples with a lower g+h still have a much larger post-deal remainder, so that number is not a cheaper finish. "
        "The next complete-route experiment, only if it is authorised on its own, should return to the verified post-SD5 checkpoint at g=150 and h=18. "
        "It needs its own budget, and this release did not run it."
    )
    return " ".join(parts)


def main() -> None:
    hashes = {key: sha256(ROOT / key) for key in EXPECTED_HASHES}
    if hashes != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the probes: {hashes}")
    cards = list(load_deal(DEAL))
    opening = SpiderState.from_cards(cards)
    canonical_replay = replay_label(CANONICAL, opening)
    autonomous_replay = replay_label(AUTONOMOUS, opening)
    if canonical_replay["mobilityware_moves"] != 172 or not canonical_replay["solved"]:
        raise SystemExit(f"172 replay failed: {canonical_replay}")
    if autonomous_replay["mobilityware_moves"] != 185 or not autonomous_replay["solved"]:
        raise SystemExit(f"185 replay failed: {autonomous_replay}")
    verify_complete_solution(
        opening.clone(),
        parse_moves_file(CANONICAL),
        expected_cost=172,
        source="imported",
        source_id="solutions/4925153_canonical.moves",
    )
    verify_complete_solution(
        opening.clone(),
        parse_moves_file(AUTONOMOUS),
        expected_cost=185,
        source="imported",
        source_id="solutions/4925153_autonomous_185.moves",
    )

    mapping = mapping_proof()
    if not mapping["confirmed"]:
        raise SystemExit(f"stock mapping is not confirmed: {mapping}")

    canonical_actions = parse_moves_file(CANONICAL)
    autonomous_actions = parse_moves_file(AUTONOMOUS)
    canonical_points = build_checkpoints(opening.clone(), canonical_actions)
    autonomous_points = build_checkpoints(opening.clone(), autonomous_actions)
    deal_index = fifth_deal(canonical_actions)
    pre = canonical_points[deal_index]
    diamond_action = first_diamond(opening, canonical_actions)
    prepared = canonical_points[diamond_action + 1]
    other_index = fifth_deal(autonomous_actions)
    other = autonomous_points[other_index]
    reference = assess_immediate_deal(pre.state, pre.g, 0, 0)
    other_deal = assess_immediate_deal(other.state, other.g, 0, 0)
    if reference.f_post != 168 or reference.same_suit_landings != 4:
        raise SystemExit(f"canonical immediate deal changed: {public_assessment(reference)}")
    if other_deal.f_post != 176 or other_deal.same_suit_landings != 0:
        raise SystemExit(f"185 immediate deal changed: {public_assessment(other_deal)}")
    labels = copy_labels(cards)

    print(
        f"REFERENCES pre={pre.index} g={pre.g} diamond_checkpoint={prepared.index} "
        f"g={prepared.g} empty={prepared.empty_columns} other_g={other.g}",
        flush=True,
    )
    print(
        f"START near-deal depth={NEAR_DEPTH} g0={pre.g} unique={MAX_UNIQUE} time={TIME_LIMIT_S}",
        flush=True,
    )
    near = search_preparation(
        pre.state.clone(),
        g0=pre.g,
        label="near-deal",
        proof_ceiling=PROOF_CEILING,
        prep_ceiling=None,
        max_depth=NEAR_DEPTH,
        max_unique=MAX_UNIQUE,
        time_limit_s=TIME_LIMIT_S,
        rss_abort_mb=RSS_ABORT_MB,
        canonical_pack=pack_state(pre.state),
    )
    near_portfolio = pareto_shortlist(near.assessments, canonical_node=near.canonical_node)
    near_rows = shortlist_rows(pre.state, pre.g, near, near_portfolio, reference)
    near_public = publish(
        near,
        near_portfolio,
        near_rows,
        "Every tableau action, including a zero-cost whole-column transfer, consumes one of the three moves. Corrected g is recorded. The kernel ceiling is the 171 proof ceiling with the raw admissible bound. A separate cost-only ceiling was not run.",
    )
    print(
        f"NEAR stop={near.stop_reason} unique={near.unique} expanded={near.expanded} "
        f"min_f={near_public['min_f_post']} landings={near_public['max_same_suit_landings']} "
        f"elapsed={near.elapsed_s:.3f}",
        flush=True,
    )

    print(
        f"START last-preparation g0={prepared.g} prep_ceiling={pre.g} unique={MAX_UNIQUE}",
        flush=True,
    )
    last = search_preparation(
        prepared.state.clone(),
        g0=prepared.g,
        label="last-preparation",
        proof_ceiling=PROOF_CEILING,
        prep_ceiling=pre.g,
        max_depth=None,
        max_unique=MAX_UNIQUE,
        time_limit_s=TIME_LIMIT_S,
        rss_abort_mb=RSS_ABORT_MB,
        canonical_pack=pack_state(pre.state),
    )
    last_portfolio = pareto_shortlist(last.assessments, canonical_node=last.canonical_node)
    last_rows = shortlist_rows(prepared.state, prepared.g, last, last_portfolio, reference)
    last_public = publish(
        last,
        last_portfolio,
        last_rows,
        "The kernel cost ceiling is the canonical pre-deal g. The height is shifted by 171 minus that budget, so a lower-bound rejection means g + admissible > 171. It does not prove anything against the preparation budget itself. Deal-now f >= 172 only labels that immediate deal.",
    )
    outcome = "reached" if last.canonical_reached else "inconclusive"
    print(
        f"LAST stop={last.stop_reason} unique={last.unique} expanded={last.expanded} "
        f"canonical={outcome} g={last.canonical_g} min_f={last_public['min_f_post']} "
        f"elapsed={last.elapsed_s:.3f}",
        flush=True,
    )

    after = {key: sha256(ROOT / key) for key in EXPECTED_HASHES}
    if after != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch after the probes: {after}")

    document = {
        "schema": "spider-pre-sd5-backward-preparation-0.132",
        "independent_cold_complete": False,
        "complete_continuation_started": False,
        "suffix_repair_started": False,
        "post_sd5_budgets_increased": False,
        "solution_hashes_before": hashes,
        "solution_hashes_after": after,
        "replays": {"canonical_172": canonical_replay, "autonomous_185": autonomous_replay},
        "mapping": mapping,
        "sd5": {
            "text": ", ".join(str(card).upper() for card in pre.state.stock),
            "copies": ", ".join(labels[54:64]),
            "both_club_threes_still_in_stock": True,
            "club_foundation_before_deal": False,
        },
        "canonical_pre_sd5": {
            "checkpoint": pre.index,
            "deal_action": deal_index,
            "g": pre.g,
            "stock_cards": pre.stock_cards,
            "empty_columns": pre.empty_columns,
            "foundations": pre.foundations,
            "face_down": pre.face_down,
            "bonds": pre.bonds,
            "columns": column_snapshot(pre.state),
            "immediate_deal": public_assessment(reference),
        },
        "canonical_after_first_diamond": {
            "action": diamond_action,
            "checkpoint": prepared.index,
            "g": prepared.g,
            "stock_cards": prepared.stock_cards,
            "empty_columns": prepared.empty_columns,
            "foundations": prepared.foundations,
            "face_down": prepared.face_down,
            "bonds": prepared.bonds,
            "actions_until_pre_deal": pre.index - prepared.index,
            "paid_until_pre_deal": pre.g - prepared.g,
            "columns": column_snapshot(prepared.state),
        },
        "autonomous_185_pre_sd5": {
            "checkpoint": other.index,
            "g": other.g,
            "empty_columns": other.empty_columns,
            "face_down": other.face_down,
            "bonds": other.bonds,
            "immediate_deal": public_assessment(other_deal),
        },
        "receiver_wishes": wish_rows(pre.state),
        "buried_long_run_threshold": 6,
        "near_deal": near_public,
        "last_preparation": last_public,
        "last_preparation_outcome": outcome,
        "recommendation": recommend(near_public, last_public, int(reference.f_post)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)
    print(document["recommendation"], flush=True)


if __name__ == "__main__":
    main()
