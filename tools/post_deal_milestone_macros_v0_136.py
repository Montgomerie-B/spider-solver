"""Post-deal milestone macros for one reveal and one club foundation.

Gate A searches the canonical stock-empty state without the reference
actions. Gate B and Gate C run only after that control replays. Caps stay
at the issue limits. Solution files are not rewritten.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import format_action, parse_moves_file, replay_actions_detailed
from spider.origin_fair_continuation import (
    CONTINUATION_RSS_MB,
    CONTINUATION_TIME_S,
    CONTINUATION_UNIQUE,
    search_origin_fair,
)
from spider.post_deal_milestone import (
    CONTROL_DEPTH,
    CONTROL_PAID,
    CONTROL_PROOF,
    CONTROL_RSS_MB,
    CONTROL_TIME_S,
    CONTROL_UNIQUE,
    SCHEMA,
    TACTIC_DEPTH,
    TACTIC_PAID,
    TACTIC_PROOF,
    TACTIC_RSS_MB,
    TACTIC_TIME_S,
    TACTIC_UNIQUE,
    WORKERS,
    MilestoneEndpoint,
    as_continuation_roots,
    control_succeeded,
    retain_endpoints,
    route_for_endpoint,
    search_milestone,
    suit_foundation_count,
)
from spider.purposeful_macro import (
    CEILING,
    CHECKPOINT_PREP,
    DISCOVERY_DEPTH,
    DISCOVERY_PAID,
    DISCOVERY_RSS_MB,
    DISCOVERY_TIME_S,
    DISCOVERY_UNIQUE,
    accept_improved_route,
    discover_macros,
    roots_from_portfolio,
)
from spider.research_actions import apply_action, face_down_count
from spider.stock_boundary_bridge import POST_SD5, load_verified_bridge_inputs

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
PREVIOUS_MACROS = ROOT / "artifacts" / "purposeful_macro_v0_134" / "results.json"
PREVIOUS_FAIR = ROOT / "artifacts" / "origin_fair_v0_135" / "results.json"
OUT = ROOT / "artifacts" / "post_deal_milestone_v0_136" / "results.json"
MILESTONE_END = 160

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def hashes() -> dict:
    return {name: sha256(ROOT / name) for name in EXPECTED_HASHES}


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


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(item: dict) -> dict:
    return {
        "actions": list(item["actions"]),
        "g_post": item["g_post"],
        "h_post": item["h_post"],
        "f_post": item["f_post"],
        "hits": item["hits"],
        "post_pack": item["post_pack"],
        "symmetry": item["symmetry"],
    }


def same_portfolio(live: list, recorded: list) -> bool:
    if len(live) != len(recorded):
        return False
    return all(fingerprint(left) == fingerprint(right) for left, right in zip(live, recorded))


def portfolio_rows(payload: dict) -> list:
    discovery = payload.get("discovery") or {}
    return list(discovery.get("portfolio") or [])


def continuation_snapshot(payload: dict) -> dict:
    block = payload.get("continuation") or {}
    if not block:
        return {}
    return {
        "accepted": block.get("accepted"),
        "stop_reason": block.get("stop_reason"),
        "outcome": payload.get("outcome"),
        "unique": block.get("unique"),
        "expanded": block.get("expanded"),
        "generated": block.get("generated"),
        "lower_bound_prunes": block.get("lower_bound_prunes"),
        "proof_prune_identities": block.get("proof_prune_identities"),
        "min_f": block.get("min_f"),
        "max_foundations": block.get("max_foundations"),
        "elapsed_s": block.get("elapsed_s"),
        "expansions_by_origin": block.get("expansions_by_origin"),
        "roots": "eight early post-SD5 macro roots",
    }


def oracle_window(checkpoints, canonical) -> dict:
    """Replay the known suffix only to record feasibility. It is not a seed."""

    post = checkpoints[POST_SD5]
    end = checkpoints[MILESTONE_END]
    prep = checkpoints[CHECKPOINT_PREP]
    state = post.state.clone()
    g = int(post.g)
    reveal_step = None
    foundation_step = None
    costs = []
    hidden_before = face_down_count(state)
    clubs_before = suit_foundation_count(state, "c")
    for step, action in enumerate(canonical[POST_SD5:MILESTONE_END], start=1):
        before_hidden = face_down_count(state)
        before_clubs = suit_foundation_count(state, "c")
        cost = int(apply_action(state, action))
        g += cost
        costs.append(cost)
        if reveal_step is None and face_down_count(state) < before_hidden:
            reveal_step = step
        if foundation_step is None and suit_foundation_count(state, "c") > before_clubs:
            foundation_step = step
    row = list(prep.state.stock[-10:])
    buried_threes = sum(1 for card in row if card.rank == 3 and card.suit == "c")
    return {
        "prep_index": int(prep.index),
        "prep_g": int(prep.g),
        "prep_stock_cards": int(prep.stock_cards),
        "prep_club_foundations": suit_foundation_count(prep.state, "c"),
        "both_three_of_clubs_in_final_stock_row": buried_threes == 2 and len(row) == 10,
        "final_stock_row_three_of_clubs": buried_threes,
        "source_index": int(post.index),
        "source_g": int(post.g),
        "source_h": int(post.admissible_remaining),
        "source_f": int(post.g) + int(post.admissible_remaining),
        "source_stock": int(post.stock_cards),
        "source_face_down": hidden_before,
        "source_club_foundations": clubs_before,
        "source_foundations": int(post.foundations),
        "window_actions": MILESTONE_END - POST_SD5,
        "window_paid": sum(costs),
        "reveal_step": reveal_step,
        "foundation_step": foundation_step,
        "end_index": int(end.index),
        "end_g": int(end.g),
        "replay_end_g": g,
        "end_face_down": face_down_count(state),
        "end_club_foundations": suit_foundation_count(state, "c"),
        "end_foundations": len(state.foundations),
        "seeded_into_search": False,
    }


def require_oracle(oracle: dict) -> None:
    expected = {
        "source_g": 150,
        "source_stock": 0,
        "source_face_down": 1,
        "source_club_foundations": 0,
        "reveal_step": 7,
        "foundation_step": 8,
        "end_g": 158,
        "replay_end_g": 158,
        "window_paid": 8,
        "end_face_down": 0,
        "end_club_foundations": 1,
        "both_three_of_clubs_in_final_stock_row": True,
        "prep_club_foundations": 0,
    }
    mismatches = {key: oracle.get(key) for key, value in expected.items() if oracle.get(key) != value}
    if mismatches:
        raise SystemExit(f"canonical milestone facts did not recompute: {mismatches}")


def match_endpoint(kept, fair):
    if fair.origin is None or fair.origin < 0 or fair.origin >= len(fair.origins):
        return None
    row = fair.origins[fair.origin]
    matches = [
        item
        for item in kept
        if item.pack == row["pack"]
        and [format_action(action) for action in item.pre_deal_macro] == list(row["macro"])
        and int(item.g) == int(row["g"])
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def main() -> None:
    before = hashes()
    if before != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the milestone search: {before}")
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    canonical = parse_moves_file(CANONICAL)
    canonical_label = replay_label(CANONICAL, opening)
    autonomous = replay_label(AUTONOMOUS, opening)
    if not canonical_label["solved"] or canonical_label["mobilityware_moves"] != 172:
        raise SystemExit("canonical 172 route did not replay")
    if not autonomous["solved"] or autonomous["mobilityware_moves"] != 185:
        raise SystemExit("autonomous 185 route did not replay")
    _early, table, _targets, checkpoints = load_verified_bridge_inputs(opening, canonical)
    post = checkpoints[POST_SD5]
    prep = checkpoints[CHECKPOINT_PREP]
    oracle = oracle_window(checkpoints, canonical)
    require_oracle(oracle)
    print(
        f"ORACLE source={oracle['source_index']} g={oracle['source_g']} "
        f"h={oracle['source_h']} fd={oracle['source_face_down']} "
        f"clubs={oracle['source_club_foundations']} reveal={oracle['reveal_step']} "
        f"foundation={oracle['foundation_step']} end_g={oracle['end_g']}",
        flush=True,
    )
    control = search_milestone(
        post.state,
        g0=post.g,
        suit="c",
        paid_moves=CONTROL_PAID,
        max_depth=CONTROL_DEPTH,
        max_unique=CONTROL_UNIQUE,
        time_limit_s=CONTROL_TIME_S,
        rss_abort_mb=CONTROL_RSS_MB,
        proof_ceiling=CONTROL_PROOF,
        stop_on_first=True,
    )
    print(
        f"GATE_A met={control.met} replay={control.replay_ok} stop={control.stop_reason} "
        f"g={control.g} paid={control.paid} unique={control.unique} "
        f"expanded={control.expanded} generated={control.generated} "
        f"elapsed={control.elapsed_s:.3f}s actions={control.public()['actions']}",
        flush=True,
    )
    discovery = None
    tactic_rows = []
    endpoints = []
    kept = []
    dominated = []
    fair = None
    verification = None
    full_actions = []
    provenance = None
    outcome = "positive_control_failed"
    if not control_succeeded(control):
        outcome = "positive_control_failed"
    else:
        discovery = discover_macros(
            prep.state,
            g0=prep.g,
            max_depth=DISCOVERY_DEPTH,
            paid_moves=DISCOVERY_PAID,
            max_unique=DISCOVERY_UNIQUE,
            time_limit_s=DISCOVERY_TIME_S,
            rss_abort_mb=DISCOVERY_RSS_MB,
        )
        print(
            f"DISCOVERY gate_b={discovery.gate_b} portfolio={len(discovery.portfolio)} "
            f"unique={discovery.unique} stop={discovery.stop_reason} "
            f"elapsed={discovery.elapsed_s:.3f}s",
            flush=True,
        )
        roots = roots_from_portfolio(discovery.portfolio)
        for index, root in enumerate(roots):
            found = search_milestone(
                root.state,
                g0=int(root.g),
                suit="c",
                paid_moves=TACTIC_PAID,
                max_depth=TACTIC_DEPTH,
                max_unique=TACTIC_UNIQUE,
                time_limit_s=TACTIC_TIME_S,
                rss_abort_mb=TACTIC_RSS_MB,
                proof_ceiling=TACTIC_PROOF,
                stop_on_first=False,
            )
            print(
                f"TACTIC {index} g0={root.g} met={found.met} stop={found.stop_reason} "
                f"hits={len(found.hits)} unique={found.unique} expanded={found.expanded} "
                f"elapsed={found.elapsed_s:.3f}s min_f={found.min_f}",
                flush=True,
            )
            tactic_rows.append(
                {
                    "root_index": index,
                    "g0": int(root.g),
                    "h0": root.h,
                    "f0": root.f,
                    "pre_deal_macro": [format_action(action) for action in root.macro],
                    "source_face_down": face_down_count(root.state),
                    "source_club_foundations": suit_foundation_count(root.state, "c"),
                    "search": found.public(),
                }
            )
            for hit in found.hits:
                if hit.state is None or not hit.replay_ok or hit.suit_gain < 1 or hit.face_down_drop < 1:
                    continue
                if int(hit.g) != int(root.g) + int(hit.paid):
                    continue
                h_value = int(admissible_remaining(hit.state))
                endpoints.append(
                    MilestoneEndpoint(
                        root_index=index,
                        g=int(hit.g),
                        h=h_value,
                        actions=tuple(hit.actions),
                        pre_deal_macro=tuple(root.macro),
                        state=hit.state,
                        pack=hit.pack,
                        symmetry=hit.symmetry,
                        suit_gain=int(hit.suit_gain),
                        face_down_drop=int(hit.face_down_drop),
                        zero_cost=int(hit.zero_cost),
                        paid=int(hit.paid),
                        replay_ok=True,
                    )
                )
        kept, dominated = retain_endpoints(endpoints)
        print(f"ENDPOINTS candidates={len(endpoints)} kept={len(kept)} dominated={len(dominated)}", flush=True)
        if not kept:
            outcome = "bounded_planning_miss"
        else:
            fair = search_origin_fair(
                as_continuation_roots(kept),
                references=table,
                ceiling=CEILING,
                max_unique=CONTINUATION_UNIQUE,
                time_limit_s=CONTINUATION_TIME_S,
                rss_abort_mb=CONTINUATION_RSS_MB,
                progress=True,
            )
            print(
                f"GATE_C accepted={fair.accepted} stop={fair.stop_reason} "
                f"unique={fair.unique} expanded={fair.expanded} min_f={fair.min_f} "
                f"elapsed={fair.elapsed_s:.3f}s",
                flush=True,
            )
            if fair.accepted:
                endpoint = match_endpoint(kept, fair)
                if endpoint is None or tuple(fair.macro) != tuple(endpoint.pre_deal_macro):
                    outcome = "provenance_mismatch"
                    provenance = {"ok": False, "origin": fair.origin}
                else:
                    full_actions = route_for_endpoint(
                        canonical,
                        endpoint,
                        fair.continuation,
                        fair.remapped_suffix,
                    )
                    verified = accept_improved_route(
                        opening,
                        full_actions,
                        expected_cost=fair.projected_cost,
                        ceiling=CEILING,
                    )
                    provenance = {
                        "ok": verified is not None,
                        "origin": fair.origin,
                        "root_index": endpoint.root_index,
                        "pre_deal_macro": [format_action(action) for action in endpoint.pre_deal_macro],
                        "tactical": [format_action(action) for action in endpoint.actions],
                        "milestone_g": endpoint.g,
                        "milestone_h": endpoint.h,
                        "milestone_f": endpoint.f,
                    }
                    if verified is None:
                        outcome = "replay_rejected"
                        verification = {"ok": False, "projected_cost": fair.projected_cost}
                    else:
                        outcome = "improvement"
                        verification = {
                            "ok": True,
                            "cost": verified.cost,
                            "foundations": verified.foundations,
                            "actions": len(verified.actions),
                            "source": verified.source,
                        }
            elif fair.inconclusive:
                outcome = "inconclusive"
            elif fair.negative_within_cap:
                outcome = "negative_within_cap"
            elif fair.stop_reason == "replay rejected":
                outcome = "replay_rejected"
            else:
                outcome = fair.stop_reason or "inconclusive"
    after = hashes()
    if after != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch after the milestone search: {after}")
    macro_artifact = load_json(PREVIOUS_MACROS)
    fair_artifact = load_json(PREVIOUS_FAIR)
    live_rows = [] if discovery is None else [item.public() for item in discovery.portfolio]
    paired_v0134 = bool(live_rows) and same_portfolio(live_rows, portfolio_rows(macro_artifact))
    paired_v0135 = bool(live_rows) and same_portfolio(live_rows, portfolio_rows(fair_artifact))
    if paired_v0134 or paired_v0135:
        comparison = "paired"
    elif discovery is None:
        comparison = "not run"
    else:
        comparison = "historical only"
    payload = {
        "schema": SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/post-deal-milestone-macros-v0-136",
        "outcome": outcome,
        "gate_stopped": (
            "A"
            if outcome == "positive_control_failed"
            else "B"
            if outcome == "bounded_planning_miss"
            else "C"
        ),
        "workers": WORKERS,
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "caps_raised": False,
        "v0_137_started": False,
        "empty_count_is_objective": False,
        "reference_actions_seeded": False,
        "milestone_is_not_a_171_claim": True,
        "oracle": oracle,
        "control_limits": {
            "paid_moves": CONTROL_PAID,
            "max_depth": CONTROL_DEPTH,
            "max_unique": CONTROL_UNIQUE,
            "time_limit_s": CONTROL_TIME_S,
            "rss_abort_mb": CONTROL_RSS_MB,
            "proof_ceiling": CONTROL_PROOF,
        },
        "tactic_limits": {
            "paid_moves": TACTIC_PAID,
            "max_depth": TACTIC_DEPTH,
            "max_unique": TACTIC_UNIQUE,
            "time_limit_s": TACTIC_TIME_S,
            "rss_abort_mb": TACTIC_RSS_MB,
            "proof_ceiling": TACTIC_PROOF,
            "ran": discovery is not None,
        },
        "continuation_limits": {
            "max_unique": CONTINUATION_UNIQUE,
            "time_limit_s": CONTINUATION_TIME_S,
            "rss_abort_mb": CONTINUATION_RSS_MB,
            "ceiling": CEILING,
            "ran": fair is not None,
            "roots": "verified milestone endpoints" if fair is not None else None,
        },
        "discovery_limits": {
            "depth": DISCOVERY_DEPTH,
            "paid_moves": DISCOVERY_PAID,
            "max_unique": DISCOVERY_UNIQUE,
            "time_limit_s": DISCOVERY_TIME_S,
            "rss_abort_mb": DISCOVERY_RSS_MB,
        },
        "control": control.public(),
        "portfolio_comparison": comparison,
        "paired_with_v0134": paired_v0134,
        "paired_with_v0135": paired_v0135,
        "discovery": None if discovery is None else discovery.public(),
        "tactics": tactic_rows,
        "endpoint_candidates": len(endpoints),
        "kept_endpoints": [item.public() for item in kept],
        "dominated_endpoints": dominated,
        "continuation": None if fair is None else fair.public(),
        "provenance": provenance,
        "verification": verification,
        "full_route": [format_action(action) for action in full_actions] if outcome == "improvement" else [],
        "historical_v0135_continuation": continuation_snapshot(fair_artifact),
        "historical_note": "Gate C roots are milestone endpoints, not the eight early SD5 roots.",
        "canonical_replay": canonical_label,
        "autonomous_replay": autonomous,
        "hashes_before": before,
        "hashes_after": after,
        "solution_files_unchanged": before == after,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"OUTCOME {outcome}", flush=True)
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
