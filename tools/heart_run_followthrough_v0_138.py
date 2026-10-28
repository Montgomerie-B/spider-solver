"""Heart-run follow-through after the fifth deal.

The canonical three-action window and the five-move shortcut are replayed
as comparisons. Neither list is a search seed. Portfolio search stays
behind the positive control. A continuation stays behind the f screen.
Solution files are not rewritten.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.heart_run_followthrough import (
    CANONICAL_ASSEMBLY_G,
    CONTROL_DEPTH,
    CONTROL_PAID,
    CONTROL_PROOF,
    CONTROL_RSS_MB,
    CONTROL_TIME_S,
    CONTROL_UNIQUE,
    HEART_RUN,
    HEART_SUIT,
    REPAIR_DEPTH,
    REPAIR_PAID,
    REPAIR_PROOF,
    REPAIR_RSS_MB,
    REPAIR_TIME_S,
    REPAIR_UNIQUE,
    TACTIC_DEPTH,
    TACTIC_PAID,
    TACTIC_PROOF,
    TACTIC_RSS_MB,
    TACTIC_TIME_S,
    TACTIC_UNIQUE,
    WORKERS,
    as_heart_roots,
    choose_heart_obligation,
    heart_goal,
    heart_route_actions,
    screen_heart_endpoint,
    select_heart_endpoints,
    top_run_length,
)
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import format_action, parse_moves_file, replay_actions_detailed
from spider.origin_fair_continuation import (
    CONTINUATION_RSS_MB,
    CONTINUATION_TIME_S,
    CONTINUATION_UNIQUE,
    search_origin_fair,
)
from spider.post_deal_milestone import (
    MilestoneEndpoint,
    control_succeeded,
    describe_position,
    search_milestone,
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
from spider.research_actions import apply_action
from spider.stock_boundary_bridge import POST_SD5, load_verified_bridge_inputs

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
PREVIOUS_MACROS = ROOT / "artifacts" / "purposeful_macro_v0_134" / "results.json"
PREVIOUS_FAIR = ROOT / "artifacts" / "origin_fair_v0_135" / "results.json"
PREVIOUS_MILESTONE = ROOT / "artifacts" / "post_deal_milestone_v0_136" / "results.json"
PREVIOUS_PHASE = ROOT / "artifacts" / "phase_aware_milestone_v0_137" / "results.json"
OUT = ROOT / "artifacts" / "heart_run_followthrough_v0_138" / "results.json"
HEART_START = 160
HEART_END = 163
DRIVER_SCHEMA = "spider-heart-run-followthrough-0.138"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

# Recorded v0.136 shortcut. Forensic replay only.
RECORDED_SHORTCUT = ((4, 1, 1), (4, 8, 1), (3, 4, 1), (3, 0, 2), (3, 8, 1))


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


def replay_shortcut(source: SpiderState, g0: int) -> tuple:
    """Apply the recorded shortcut. The tuples are not returned to a search."""

    state = source.clone()
    g = int(g0)
    for action in RECORDED_SHORTCUT:
        g += int(apply_action(state, action))
    return state, g


def oracle_window(checkpoints, canonical) -> dict:
    """Replay the next three canonical actions. They are not a seed."""

    start = checkpoints[HEART_START]
    end = checkpoints[HEART_END]
    state = start.state.clone()
    g = int(start.g)
    costs = []
    for action in canonical[HEART_START:HEART_END]:
        cost = int(apply_action(state, action))
        g += cost
        costs.append(cost)
    obligation = choose_heart_obligation(start.state, state)
    position = describe_position(state, g)
    position["top_heart_run"] = top_run_length(state, HEART_SUIT)
    return {
        "start_index": int(start.index),
        "start_g": int(start.g),
        "start_h": int(start.admissible_remaining),
        "start_f": int(start.g) + int(start.admissible_remaining),
        "start_stock": int(start.stock_cards),
        "start_foundations": int(start.foundations),
        "window_actions": HEART_END - HEART_START,
        "window_paid": sum(costs),
        "costs": costs,
        "end_index": int(end.index),
        "end_g": int(end.g),
        "replay_end_g": g,
        "pack_matches_checkpoint": position["pack"] == describe_position(end.state, end.g)["pack"],
        "obligation_mode": obligation["mode"],
        "buried_before": obligation["buried_before"],
        "top_before": obligation["top_before"],
        "buried_after": obligation["buried_after"],
        "top_after": obligation["top_after"],
        "top_length_before": obligation["top_length_before"],
        "top_length_after": obligation["top_length_after"],
        "end_position": position,
        "seeded_into_search": False,
    }


def require_oracle(oracle: dict) -> dict:
    """Lock the recomputed window. A mismatch stops the release."""

    problems = []
    if oracle["start_g"] != 158 or oracle["start_stock"] != 0:
        problems.append("checkpoint 160 cost or stock")
    if oracle["replay_end_g"] != CANONICAL_ASSEMBLY_G or oracle["end_g"] != CANONICAL_ASSEMBLY_G:
        problems.append("assembly cost")
    if oracle["window_paid"] != 3 or oracle["costs"] != [1, 1, 1]:
        problems.append("window costs")
    if not oracle["pack_matches_checkpoint"]:
        problems.append("checkpoint pack")
    if oracle["obligation_mode"] != "top_same_suit_run_at_least":
        problems.append(oracle["obligation_mode"])
    if not oracle["buried_before"] or oracle["top_before"] or not oracle["top_after"]:
        problems.append("run facts")
    return {"ok": not problems, "problems": problems}


def exhausted_identities(*payloads: dict) -> dict:
    packs = []
    symmetries = []
    for payload in payloads:
        for row in payload.get("kept_endpoints") or []:
            pack = str(row.get("pack") or "")
            symmetry = str(row.get("symmetry") or "")
            if pack:
                packs.append(pack)
            if symmetry:
                symmetries.append(symmetry)
    return {"packs": packs, "symmetries": symmetries}


def endpoint_from_hit(index: int, root_g: int, macro, hit) -> MilestoneEndpoint:
    h_value = int(admissible_remaining(hit.state))
    return MilestoneEndpoint(
        root_index=index,
        g=int(hit.g),
        h=h_value,
        actions=tuple(hit.actions),
        pre_deal_macro=tuple(macro),
        state=hit.state,
        pack=hit.pack,
        symmetry=hit.symmetry,
        suit_gain=int(hit.suit_gain),
        face_down_drop=int(hit.face_down_drop),
        zero_cost=int(hit.zero_cost),
        paid=int(hit.paid),
        replay_ok=True,
    )


def position_of(endpoint: MilestoneEndpoint) -> dict:
    row = describe_position(endpoint.state, endpoint.g)
    row["top_heart_run"] = top_run_length(endpoint.state, HEART_SUIT)
    row["heart_goal"] = heart_goal(endpoint.state)
    row["actions"] = [format_action(action) for action in endpoint.actions]
    row["root_index"] = endpoint.root_index
    return row


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


def repair_summary(found, canon_position: dict) -> dict:
    hits = []
    for hit in found.hits:
        if hit.state is None:
            continue
        h_value = int(hit.h) if hit.h is not None else int(admissible_remaining(hit.state))
        hits.append({"g": int(hit.g), "h": h_value, "f": int(hit.g) + h_value, "actions": hit.public()["actions"]})
    best = None if not hits else min(hits, key=lambda row: (row["f"], row["g"]))
    caught = bool(best is not None and int(best["g"]) <= CANONICAL_ASSEMBLY_G)
    if found.met and best is not None:
        label = "caught_up" if caught else "later_than_canonical_g"
    elif found.stop_reason in {"time limit", "unique limit", "rss abort"}:
        label = "inconclusive"
    else:
        label = "inconclusive"
    return {
        "label": label,
        "caught_up_by_canonical_g": caught,
        "best": best,
        "canonical_assembly": {
            "g": canon_position["g"],
            "h": canon_position["h"],
            "f": canon_position["f"],
            "bonds": canon_position["bonds"],
            "mixed_joins": canon_position["mixed_joins"],
            "open_columns": canon_position["open_columns"],
            "mobility": canon_position["mobility"],
            "face_down": canon_position["face_down"],
            "foundations": canon_position["foundations"],
        },
        "search": found.public(),
        "proof": False,
    }


def main() -> None:
    before = hashes()
    if before != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the heart-run search: {before}")
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    canonical = parse_moves_file(CANONICAL)
    canonical_label = replay_label(CANONICAL, opening)
    autonomous = replay_label(AUTONOMOUS, opening)
    if not canonical_label["solved"] or canonical_label["mobilityware_moves"] != 172:
        raise SystemExit("canonical 172 route did not replay")
    if not autonomous["solved"] or autonomous["mobilityware_moves"] != 185:
        raise SystemExit("autonomous 185 route did not replay")
    _early, table, _targets, checkpoints = load_verified_bridge_inputs(opening, canonical)
    start = checkpoints[HEART_START]
    post = checkpoints[POST_SD5]
    prep = checkpoints[CHECKPOINT_PREP]
    oracle = oracle_window(checkpoints, canonical)
    oracle_check = require_oracle(oracle)
    short_state, short_g = replay_shortcut(post.state, int(post.g))
    short_pos = describe_position(short_state, short_g)
    short_pos["top_heart_run"] = top_run_length(short_state, HEART_SUIT)
    short_pos["heart_goal"] = heart_goal(short_state)
    print(
        f"ORACLE mode={oracle['obligation_mode']} start_g={oracle['start_g']} "
        f"end_g={oracle['replay_end_g']} top {oracle['top_length_before']}->{oracle['top_length_after']} "
        f"shortcut_g={short_g} shortcut_h={short_pos['h']} shortcut_f={short_pos['f']} "
        f"shortcut_goal={short_pos['heart_goal']}",
        flush=True,
    )
    blocked = exhausted_identities(load_json(PREVIOUS_MILESTONE), load_json(PREVIOUS_PHASE))
    control = None
    repair = None
    repair_row = None
    discovery = None
    tactic_rows = []
    endpoints = []
    kept = []
    dominated = []
    selection_info = {}
    screens = []
    opened = []
    fair = None
    verification = None
    full_actions = []
    provenance = None
    if not oracle_check["ok"]:
        outcome = "observation_mismatch"
        gate = "A"
        print(f"ORACLE mismatch {oracle_check['problems']}", flush=True)
    else:
        goal = heart_goal
        control = search_milestone(
            start.state,
            g0=int(start.g),
            suit=HEART_SUIT,
            paid_moves=CONTROL_PAID,
            max_depth=CONTROL_DEPTH,
            max_unique=CONTROL_UNIQUE,
            time_limit_s=CONTROL_TIME_S,
            rss_abort_mb=CONTROL_RSS_MB,
            proof_ceiling=CONTROL_PROOF,
            terminal_fn=goal,
            stop_on_first=True,
        )
        print(
            f"GATE_A met={control.met} replay={control.replay_ok} stop={control.stop_reason} "
            f"g={control.g} paid={control.paid} unique={control.unique} "
            f"expanded={control.expanded} elapsed={control.elapsed_s:.3f}s "
            f"cpu={control.cpu_s:.3f}s actions={control.public()['actions']}",
            flush=True,
        )
        if short_pos["heart_goal"]:
            repair_row = {
                "label": "already_present",
                "caught_up_by_canonical_g": int(short_g) <= CANONICAL_ASSEMBLY_G,
                "best": {"g": int(short_g), "h": short_pos["h"], "f": short_pos["f"], "actions": []},
                "position": short_pos,
                "proof": False,
            }
        else:
            repair = search_milestone(
                short_state,
                g0=int(short_g),
                suit=HEART_SUIT,
                paid_moves=REPAIR_PAID,
                max_depth=REPAIR_DEPTH,
                max_unique=REPAIR_UNIQUE,
                time_limit_s=REPAIR_TIME_S,
                rss_abort_mb=REPAIR_RSS_MB,
                proof_ceiling=REPAIR_PROOF,
                terminal_fn=goal,
                stop_on_first=False,
                hit_policy="lower_f",
            )
            repair_row = repair_summary(repair, oracle["end_position"])
            if repair.met and repair.actions:
                played = short_state.clone()
                spent = 0
                for action in repair.actions:
                    spent += int(apply_action(played, action))
                repair_row["replay_position"] = describe_position(played, int(short_g) + spent)
                repair_row["replay_position"]["top_heart_run"] = top_run_length(played, HEART_SUIT)
                repair_row["replay_goal"] = heart_goal(played)
            print(
                f"GATE_B label={repair_row['label']} met={repair.met} stop={repair.stop_reason} "
                f"unique={repair.unique} expanded={repair.expanded} "
                f"elapsed={repair.elapsed_s:.3f}s min_f={repair.min_f}",
                flush=True,
            )
        if not control_succeeded(control):
            outcome = "positive_control_failed"
            gate = "A"
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
                    suit=HEART_SUIT,
                    paid_moves=TACTIC_PAID,
                    max_depth=TACTIC_DEPTH,
                    max_unique=TACTIC_UNIQUE,
                    time_limit_s=TACTIC_TIME_S,
                    rss_abort_mb=TACTIC_RSS_MB,
                    proof_ceiling=TACTIC_PROOF,
                    terminal_fn=goal,
                    stop_on_first=False,
                    hit_policy="lower_f",
                )
                print(
                    f"TACTIC {index} g0={root.g} met={found.met} stop={found.stop_reason} "
                    f"hits={len(found.hits)} first_g={found.first_g} unique={found.unique} "
                    f"elapsed={found.elapsed_s:.3f}s min_f={found.min_f} "
                    f"top={top_run_length(root.state, HEART_SUIT)}",
                    flush=True,
                )
                tactic_rows.append(
                    {
                        "root_index": index,
                        "g0": int(root.g),
                        "h0": root.h,
                        "f0": root.f,
                        "pre_deal_macro": [format_action(action) for action in root.macro],
                        "source_top_heart_run": top_run_length(root.state, HEART_SUIT),
                        "source_heart_goal": heart_goal(root.state),
                        "first_hit_paid": None if found.first_g is None else int(found.first_g) - int(root.g),
                        "first_hit_s": found.first_s,
                        "search": found.public(),
                    }
                )
                for hit in found.hits:
                    if hit.state is None or not hit.replay_ok or not heart_goal(hit.state):
                        continue
                    if int(hit.g) != int(root.g) + int(hit.paid):
                        continue
                    endpoints.append(endpoint_from_hit(index, int(root.g), root.macro, hit))
            kept, dominated, selection_info = select_heart_endpoints(endpoints, goal=goal)
            for item in kept:
                row = screen_heart_endpoint(
                    item,
                    ceiling=CEILING,
                    excluded_packs=blocked["packs"],
                    excluded_symmetries=blocked["symmetries"],
                    goal=goal,
                )
                screens.append(row)
                if row["accepted"]:
                    opened.append(item)
            print(
                f"ENDPOINTS candidates={len(endpoints)} kept={len(kept)} "
                f"opened={len(opened)} dominated={len(dominated)}",
                flush=True,
            )
            if not opened:
                outcome = "bounded_planning_miss" if not kept else "screening_miss"
                gate = "C"
            else:
                gate = "D"
                fair = search_origin_fair(
                    as_heart_roots(opened[:8]),
                    references=table,
                    ceiling=CEILING,
                    max_unique=CONTINUATION_UNIQUE,
                    time_limit_s=CONTINUATION_TIME_S,
                    rss_abort_mb=CONTINUATION_RSS_MB,
                    progress=True,
                )
                print(
                    f"GATE_D accepted={fair.accepted} stop={fair.stop_reason} "
                    f"unique={fair.unique} expanded={fair.expanded} min_f={fair.min_f} "
                    f"elapsed={fair.elapsed_s:.3f}s",
                    flush=True,
                )
                if fair.accepted:
                    endpoint = match_endpoint(opened, fair)
                    if endpoint is None or tuple(fair.macro) != tuple(endpoint.pre_deal_macro):
                        outcome = "provenance_mismatch"
                        provenance = {"ok": False, "origin": fair.origin}
                    else:
                        full_actions = heart_route_actions(
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
                            "heart_run": [format_action(action) for action in endpoint.actions],
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
        raise SystemExit(f"solution hash mismatch after the heart-run search: {after}")
    macro_artifact = load_json(PREVIOUS_MACROS)
    fair_artifact = load_json(PREVIOUS_FAIR)
    live_rows = [] if discovery is None else [item.public() for item in discovery.portfolio]
    paired_v0134 = bool(live_rows) and same_portfolio(live_rows, portfolio_rows(macro_artifact))
    paired_v0135 = bool(live_rows) and same_portfolio(live_rows, portfolio_rows(fair_artifact))
    if paired_v0134 or paired_v0135:
        portfolio_comparison = "paired"
    elif discovery is None:
        portfolio_comparison = "not run"
    else:
        portfolio_comparison = "historical only"
    best = None if not kept else min(kept, key=lambda item: (item.f, item.g, item.pack))
    payload = {
        "schema": DRIVER_SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/heart-run-followthrough-v0-138",
        "outcome": outcome,
        "gate_stopped": gate,
        "workers": WORKERS,
        "heart_run": HEART_RUN,
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "exhausted_v0136_endpoint_rerun": False,
        "caps_raised": False,
        "v0_139_started": False,
        "reference_actions_seeded": False,
        "heart_run_is_not_a_complete_game": True,
        "f_screen_is_not_a_proof": True,
        "obligation": {
            "mode": oracle["obligation_mode"],
            "buried_run_already_true_at_checkpoint_160": oracle["buried_before"],
            "top_run_false_until_the_window": not oracle["top_before"] and oracle["top_after"],
            "suit": HEART_SUIT,
            "min_len": HEART_RUN,
        },
        "oracle_check": oracle_check,
        "oracle": oracle,
        "shortcut": {
            "g": int(short_g),
            "position": short_pos,
            "heart_goal_already": bool(short_pos["heart_goal"]),
            "seeded_into_search": False,
        },
        "exhausted_packs_excluded": blocked["packs"],
        "exhausted_symmetries_excluded": blocked["symmetries"],
        "control_limits": {
            "paid_moves": CONTROL_PAID,
            "max_depth": CONTROL_DEPTH,
            "max_unique": CONTROL_UNIQUE,
            "time_limit_s": CONTROL_TIME_S,
            "rss_abort_mb": CONTROL_RSS_MB,
            "proof_ceiling": CONTROL_PROOF,
            "ran": control is not None,
        },
        "repair_limits": {
            "paid_moves": REPAIR_PAID,
            "max_depth": REPAIR_DEPTH,
            "max_unique": REPAIR_UNIQUE,
            "time_limit_s": REPAIR_TIME_S,
            "rss_abort_mb": REPAIR_RSS_MB,
            "proof_ceiling": REPAIR_PROOF,
            "canonical_assembly_g": CANONICAL_ASSEMBLY_G,
            "ran": repair is not None,
        },
        "tactic_limits": {
            "paid_moves": TACTIC_PAID,
            "max_depth": TACTIC_DEPTH,
            "max_unique": TACTIC_UNIQUE,
            "time_limit_s": TACTIC_TIME_S,
            "rss_abort_mb": TACTIC_RSS_MB,
            "proof_ceiling": TACTIC_PROOF,
            "hit_policy": "lower_f",
            "ran": discovery is not None,
        },
        "continuation_limits": {
            "max_unique": CONTINUATION_UNIQUE,
            "time_limit_s": CONTINUATION_TIME_S,
            "rss_abort_mb": CONTINUATION_RSS_MB,
            "ceiling": CEILING,
            "ran": fair is not None,
        },
        "control": None if control is None else control.public(),
        "repair": repair_row,
        "portfolio_comparison": portfolio_comparison,
        "paired_with_v0134": paired_v0134,
        "paired_with_v0135": paired_v0135,
        "discovery": None if discovery is None else discovery.public(),
        "tactics": tactic_rows,
        "endpoint_candidates": len(endpoints),
        "selection": selection_info,
        "kept_endpoints": [item.public() for item in kept],
        "kept_positions": [position_of(item) for item in kept],
        "best_kept": None if best is None else best.public(),
        "screen": screens,
        "opened_endpoints": [item.public() for item in opened],
        "dominated_endpoints": dominated,
        "continuation": None if fair is None else fair.public(),
        "provenance": provenance,
        "verification": verification,
        "full_route": [format_action(action) for action in full_actions] if outcome == "improvement" else [],
        "canonical_replay": canonical_label,
        "autonomous_replay": autonomous,
        "hashes_before": before,
        "hashes_after": after,
        "solution_files_unchanged": before == after,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"OUTCOME {outcome} GATE {gate}", flush=True)
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
