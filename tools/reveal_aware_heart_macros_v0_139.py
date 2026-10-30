"""Reveal-aware heart-run macros after the fifth deal.

The canonical five-action window is a feasibility oracle. It is not a
search seed. Portfolio search stays behind the positive control. A
continuation stays behind the compound screen. Solution files are not
rewritten. v0.138 left its unverified terminals in an aggregate report
only; those node graphs are not replayed here.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.heart_run_followthrough import heart_goal, screen_heart_endpoint, select_heart_endpoints
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
from spider.research_actions import apply_action, face_down_count
from spider.reveal_aware_heart import (
    CONTROL_DEPTH,
    CONTROL_END,
    CONTROL_INDEX,
    CONTROL_PAID,
    CONTROL_PROOF,
    CONTROL_RSS_MB,
    CONTROL_TIME_S,
    CONTROL_UNIQUE,
    HEART_RUN,
    TACTIC_DEPTH,
    TACTIC_PAID,
    TACTIC_PROOF,
    TACTIC_RSS_MB,
    TACTIC_TIME_S,
    TACTIC_UNIQUE,
    WORKERS,
    as_compound_roots,
    compound_heart_reveal,
    compound_route_actions,
    top_heart_span,
)
from spider.stock_boundary_bridge import load_verified_bridge_inputs

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
PREVIOUS_MACROS = ROOT / "artifacts" / "purposeful_macro_v0_134" / "results.json"
PREVIOUS_FAIR = ROOT / "artifacts" / "origin_fair_v0_135" / "results.json"
PREVIOUS_MILESTONE = ROOT / "artifacts" / "post_deal_milestone_v0_136" / "results.json"
PREVIOUS_PHASE = ROOT / "artifacts" / "phase_aware_milestone_v0_137" / "results.json"
PREVIOUS_HEART = ROOT / "artifacts" / "heart_run_followthrough_v0_138" / "results.json"
OUT = ROOT / "artifacts" / "reveal_aware_heart_macros_v0_139" / "results.json"
DRIVER_SCHEMA = "spider-reveal-aware-heart-macros-0.139"

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


def oracle_window(checkpoints, canonical) -> dict:
    """Replay checkpoint 158 through 163. The actions are not a seed."""

    start = checkpoints[CONTROL_INDEX]
    end = checkpoints[CONTROL_END]
    state = start.state.clone()
    g = int(start.g)
    costs = []
    hidden = []
    for action in canonical[CONTROL_INDEX:CONTROL_END]:
        hidden.append(face_down_count(state))
        cost = int(apply_action(state, action))
        g += cost
        costs.append(cost)
    position = describe_position(state, g)
    position.update(top_heart_span(state))
    return {
        "start_index": int(start.index),
        "start_g": int(start.g),
        "start_h": int(start.admissible_remaining),
        "start_f": int(start.g) + int(start.admissible_remaining),
        "start_face_down": face_down_count(start.state),
        "start_top_heart": top_heart_span(start.state)["length"],
        "start_heart_goal": heart_goal(start.state),
        "window_actions": CONTROL_END - CONTROL_INDEX,
        "window_paid": sum(costs),
        "costs": costs,
        "face_down_before_each_action": hidden,
        "end_index": int(end.index),
        "end_g": int(end.g),
        "replay_end_g": g,
        "end_face_down": face_down_count(state),
        "end_heart_goal": heart_goal(state),
        "end_top_heart": top_heart_span(state)["length"],
        "pack_matches_checkpoint": position["pack"] == describe_position(end.state, end.g)["pack"],
        "end_position": position,
        "seeded_into_search": False,
    }


def require_oracle(oracle: dict) -> dict:
    problems = []
    if oracle["start_g"] != 156 or oracle["start_face_down"] != 1 or oracle["start_heart_goal"]:
        problems.append("checkpoint 158")
    if oracle["replay_end_g"] != 161 or oracle["end_g"] != 161:
        problems.append("checkpoint 163 cost")
    if oracle["window_paid"] != 5 or oracle["costs"] != [1, 1, 1, 1, 1]:
        problems.append("window costs")
    if oracle["end_face_down"] != 0 or not oracle["end_heart_goal"] or oracle["end_top_heart"] < HEART_RUN:
        problems.append("compound facts")
    if not oracle["pack_matches_checkpoint"]:
        problems.append("checkpoint pack")
    return {"ok": not problems, "problems": problems}


def exhausted_identities(*payloads: dict) -> dict:
    """Packs and symmetries already continued. Roots that produced them stay."""

    packs = []
    symmetries = []
    for payload in payloads:
        rows = list(payload.get("kept_endpoints") or [])
        rows.extend(payload.get("opened_endpoints") or [])
        for row in rows:
            pack = str(row.get("pack") or "")
            symmetry = str(row.get("symmetry") or "")
            if pack:
                packs.append(pack)
            if symmetry:
                symmetries.append(symmetry)
    return {"packs": packs, "symmetries": symmetries}


def control_ready(result) -> bool:
    return bool(
        control_succeeded(result)
        and result.verification == "complete"
        and result.actions
    )


def endpoint_from_hit(index: int, macro, hit, root_face_down: int) -> MilestoneEndpoint:
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
        face_down_drop=int(root_face_down) - face_down_count(hit.state),
        zero_cost=int(hit.zero_cost),
        paid=int(hit.paid),
        replay_ok=True,
    )


def position_of(endpoint: MilestoneEndpoint, root_face_down: int) -> dict:
    row = describe_position(endpoint.state, endpoint.g)
    row.update(top_heart_span(endpoint.state))
    row["heart_goal"] = heart_goal(endpoint.state)
    row["face_down_before"] = int(root_face_down)
    row["revealed"] = face_down_count(endpoint.state) < int(root_face_down)
    row["compound"] = bool(row["heart_goal"] and row["revealed"])
    row["actions"] = [format_action(action) for action in endpoint.actions]
    row["pre_deal_macro"] = [format_action(action) for action in endpoint.pre_deal_macro]
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


def discovery_limit(rows: list) -> str:
    """Which part of the compound search left no screened endpoint."""

    if any(row["search"].get("verification") != "complete" for row in rows):
        return "terminal verification"
    both = 0
    run_only = 0
    reveal_only = 0
    for row in rows:
        diagnostics = row["search"].get("diagnostics") or {}
        both += int(diagnostics.get("run_and_reveal") or 0)
        run_only += int(diagnostics.get("run_without_reveal") or 0)
        reveal_only += int(diagnostics.get("reveal_without_run") or 0)
    if both == 0 and run_only > reveal_only:
        return "heart construction"
    if both == 0 and reveal_only > run_only:
        return "reveal search"
    if both == 0:
        return "heart construction"
    return "screen"


def main() -> None:
    before = hashes()
    if before != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the compound search: {before}")
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    canonical = parse_moves_file(CANONICAL)
    canonical_label = replay_label(CANONICAL, opening)
    autonomous = replay_label(AUTONOMOUS, opening)
    if not canonical_label["solved"] or canonical_label["mobilityware_moves"] != 172:
        raise SystemExit("canonical 172 route did not replay")
    if not autonomous["solved"] or autonomous["mobilityware_moves"] != 185:
        raise SystemExit("autonomous 185 route did not replay")
    _early, table, _targets, checkpoints = load_verified_bridge_inputs(opening, canonical)
    start = checkpoints[CONTROL_INDEX]
    prep = checkpoints[CHECKPOINT_PREP]
    oracle = oracle_window(checkpoints, canonical)
    oracle_check = require_oracle(oracle)
    print(
        f"ORACLE ok={oracle_check['ok']} start_g={oracle['start_g']} fd={oracle['start_face_down']} "
        f"top={oracle['start_top_heart']} end_g={oracle['replay_end_g']} "
        f"end_fd={oracle['end_face_down']} end_top={oracle['end_top_heart']}",
        flush=True,
    )
    blocked = exhausted_identities(
        load_json(PREVIOUS_MILESTONE),
        load_json(PREVIOUS_PHASE),
        load_json(PREVIOUS_HEART),
    )
    goal = compound_heart_reveal(face_down_count(start.state))
    control = None
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
    limit_reason = ""
    if not oracle_check["ok"]:
        outcome = "observation_mismatch"
        gate = "B"
        print(f"ORACLE mismatch {oracle_check['problems']}", flush=True)
    else:
        control = search_milestone(
            start.state,
            g0=int(start.g),
            suit="h",
            paid_moves=CONTROL_PAID,
            max_depth=CONTROL_DEPTH,
            max_unique=CONTROL_UNIQUE,
            time_limit_s=CONTROL_TIME_S,
            rss_abort_mb=CONTROL_RSS_MB,
            proof_ceiling=CONTROL_PROOF,
            terminal_fn=goal,
            stop_on_first=True,
            hit_policy="lower_f",
            run_reveal=True,
            run_min=HEART_RUN,
        )
        print(
            f"GATE_B met={control.met} replay={control.replay_ok} "
            f"verification={control.verification} stop={control.stop_reason} "
            f"g={control.g} paid={control.paid} unique={control.unique} "
            f"expanded={control.expanded} elapsed={control.elapsed_s:.3f}s "
            f"cpu={control.cpu_s:.3f}s verify={control.verify_wall_s:.3f}s "
            f"actions={control.public()['actions']}",
            flush=True,
        )
        if not control_ready(control):
            outcome = "positive_control_failed"
            gate = "B"
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
                root_hidden = face_down_count(root.state)
                root_goal = compound_heart_reveal(root_hidden)
                found = search_milestone(
                    root.state,
                    g0=int(root.g),
                    suit="h",
                    paid_moves=TACTIC_PAID,
                    max_depth=TACTIC_DEPTH,
                    max_unique=TACTIC_UNIQUE,
                    time_limit_s=TACTIC_TIME_S,
                    rss_abort_mb=TACTIC_RSS_MB,
                    proof_ceiling=TACTIC_PROOF,
                    terminal_fn=root_goal,
                    stop_on_first=False,
                    hit_policy="lower_f",
                    run_reveal=True,
                    run_min=HEART_RUN,
                )
                print(
                    f"TACTIC {index} g0={root.g} fd={root_hidden} met={found.met} "
                    f"verification={found.verification} stop={found.stop_reason} "
                    f"hits={len(found.hits)} terminals={found.hit_truncation.get('terminals')} "
                    f"unique={found.unique} elapsed={found.elapsed_s:.3f}s "
                    f"verify={found.verify_wall_s:.3f}s min_f={found.min_f}",
                    flush=True,
                )
                tactic_rows.append(
                    {
                        "root_index": index,
                        "g0": int(root.g),
                        "h0": root.h,
                        "f0": root.f,
                        "face_down": root_hidden,
                        "pre_deal_macro": [format_action(action) for action in root.macro],
                        "source_top_heart": top_heart_span(root.state),
                        "first_hit_paid": None if found.first_g is None else int(found.first_g) - int(root.g),
                        "first_hit_s": found.first_s,
                        "search": found.public(),
                    }
                )
                if found.verification != "complete":
                    continue
                for hit in found.hits:
                    if hit.state is None or not hit.replay_ok or not root_goal(hit.state):
                        continue
                    if int(hit.g) != int(root.g) + int(hit.paid):
                        continue
                    endpoints.append(endpoint_from_hit(index, root.macro, hit, root_hidden))
            kept, dominated, selection_info = select_heart_endpoints(
                endpoints,
                ceiling=170,
                goal=heart_goal,
            )
            # select_heart_endpoints sees the run only. The reveal is the
            # drop against that endpoint's own post-deal root.
            kept = [item for item in kept if int(item.face_down_drop) >= 1 and heart_goal(item.state)]
            for item in kept:
                row = screen_heart_endpoint(
                    item,
                    ceiling=CEILING,
                    excluded_packs=blocked["packs"],
                    excluded_symmetries=blocked["symmetries"],
                    goal=lambda state, hidden=item.face_down_drop: heart_goal(state) and hidden >= 1,
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
                outcome = "inconclusive"
                gate = "C"
                limit_reason = discovery_limit(tactic_rows)
            else:
                gate = "D"
                fair = search_origin_fair(
                    as_compound_roots(opened[:8]),
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
                        full_actions = compound_route_actions(
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
                            "compound": [format_action(action) for action in endpoint.actions],
                            "milestone_g": endpoint.g,
                            "milestone_h": endpoint.h,
                            "milestone_f": endpoint.f,
                            "source": "incumbent-guided",
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
        raise SystemExit(f"solution hash mismatch after the compound search: {after}")
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
    hidden_by_root = {row["root_index"]: row["face_down"] for row in tactic_rows}
    best = None if not kept else min(kept, key=lambda item: (item.f, item.g, item.pack))
    payload = {
        "schema": DRIVER_SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/reveal-aware-heart-macros-v0-139",
        "outcome": outcome,
        "gate_stopped": gate,
        "limit_reason": limit_reason,
        "workers": WORKERS,
        "heart_run": HEART_RUN,
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "exhausted_endpoints_rerun": False,
        "caps_raised": False,
        "v0_140_started": False,
        "reference_actions_seeded": False,
        "compound_is_not_a_complete_game": True,
        "f_screen_is_not_a_proof": True,
        "v0138_unverified_terminals": (
            "not revalidated; the v0.138 node graphs were not stored, "
            "and this release does not rerun that search"
        ),
        "oracle_check": oracle_check,
        "oracle": oracle,
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
        "tactic_limits": {
            "paid_moves": TACTIC_PAID,
            "max_depth": TACTIC_DEPTH,
            "max_unique": TACTIC_UNIQUE,
            "time_limit_s": TACTIC_TIME_S,
            "rss_abort_mb": TACTIC_RSS_MB,
            "proof_ceiling": TACTIC_PROOF,
            "hit_policy": "lower_f",
            "run_reveal": True,
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
        "portfolio_comparison": portfolio_comparison,
        "paired_with_v0134": paired_v0134,
        "paired_with_v0135": paired_v0135,
        "discovery": None if discovery is None else discovery.public(),
        "tactics": tactic_rows,
        "endpoint_candidates": len(endpoints),
        "selection": selection_info,
        "kept_endpoints": [item.public() for item in kept],
        "kept_positions": [
            position_of(item, hidden_by_root.get(item.root_index, 0)) for item in kept
        ],
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
    print(f"OUTCOME {outcome} GATE {gate} LIMIT {limit_reason}", flush=True)
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
