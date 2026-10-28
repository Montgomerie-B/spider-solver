"""Phase-aware ordering for one reveal and one club foundation.

The recorded five-move tableau is replayed only as a comparison. It is not
a search seed. Later gates stay behind the positive control and the screen.
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
    describe_position,
    retain_endpoints,
    route_for_endpoint,
    screening_milestone,
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
PREVIOUS_MILESTONE = ROOT / "artifacts" / "post_deal_milestone_v0_136" / "results.json"
OUT = ROOT / "artifacts" / "phase_aware_milestone_v0_137" / "results.json"
MILESTONE_END = 160
DRIVER_SCHEMA = "spider-phase-aware-milestone-0.137"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

# Recorded v0.136 discovery. Forensic comparison only.
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


def compare_shortcut(checkpoints, canonical) -> dict:
    """Replay both tableaux from checkpoint 152. No search and no remap."""

    post = checkpoints[POST_SD5]
    source = post.state.clone()
    canon = source.clone()
    g_canon = int(post.g)
    for action in canonical[POST_SD5:MILESTONE_END]:
        g_canon += int(apply_action(canon, action))
    short = source.clone()
    g_short = int(post.g)
    legal = True
    error = ""
    try:
        for action in RECORDED_SHORTCUT:
            g_short += int(apply_action(short, action))
    except ValueError as exc:
        legal = False
        error = str(exc)
    canon_pos = describe_position(canon, g_canon)
    short_pos = describe_position(short, g_short) if legal else None
    failure = None
    if legal:
        probe = short.clone()
        for index, action in enumerate(canonical[MILESTONE_END:]):
            try:
                apply_action(probe, action)
            except ValueError as exc:
                failure = {
                    "suffix_index": index,
                    "action": format_action(action),
                    "error": str(exc),
                }
                break
    saved = None if short_pos is None else int(canon_pos["g"]) - int(short_pos["g"])
    f_delta = None if short_pos is None else int(short_pos["f"]) - int(canon_pos["f"])
    if short_pos is None or saved is None or f_delta is None:
        reading = "The shortcut did not replay, so no tableau comparison is available."
    elif failure is None:
        reading = (
            f"The shortcut is {saved} corrected moves shorter and its residual "
            f"bound differs by {f_delta}. The canonical suffix replayed on it. "
            "That diagnostic is not a stored solution."
        )
    else:
        reading = (
            f"The shortcut is {saved} corrected moves shorter. Its admissible "
            f"bound differs by {f_delta} from the canonical milestone at "
            f"f={canon_pos['f']}. The canonical suffix is illegal at "
            f"{failure['action']}: {failure['error']}. The shorter action "
            "count does not carry the reference continuation."
        )
    return {
        "legal": legal,
        "error": error,
        "canonical": canon_pos,
        "shortcut": short_pos,
        "packs_differ": bool(short_pos and short_pos["pack"] != canon_pos["pack"]),
        "symmetries_differ": bool(short_pos and short_pos["symmetry"] != canon_pos["symmetry"]),
        "saved_corrected_moves": saved,
        "f_delta_shortcut_minus_canonical": f_delta,
        "blind_projection_g": None if short_pos is None else int(short_pos["g"]) + (172 - int(canon_pos["g"])),
        "suffix_transfers": bool(legal and failure is None),
        "first_illegal_suffix_action": failure,
        "reading": reading,
        "speculative": "No other winning line from the shortcut was searched here.",
        "seeded_into_search": False,
        "checkpoint_h_is_not_search_telemetry": True,
    }


def oracle_window(checkpoints, canonical) -> dict:
    """Record the canonical window. Those actions are not a seed."""

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
        "source_index": int(post.index),
        "source_g": int(post.g),
        "source_h": int(post.admissible_remaining),
        "source_f": int(post.g) + int(post.admissible_remaining),
        "source_stock": int(post.stock_cards),
        "source_face_down": hidden_before,
        "source_club_foundations": clubs_before,
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
        "both_three_of_clubs_in_final_stock_row": buried_threes == 2 and len(row) == 10,
        "seeded_into_search": False,
    }


def require_oracle(oracle: dict, comparison: dict) -> None:
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
    }
    mismatches = {key: oracle.get(key) for key, value in expected.items() if oracle.get(key) != value}
    if mismatches:
        raise SystemExit(f"canonical milestone facts did not recompute: {mismatches}")
    if not comparison["legal"]:
        raise SystemExit(f"recorded shortcut did not replay: {comparison['error']}")
    canon = comparison["canonical"]
    short = comparison["shortcut"]
    if canon["g"] != 158 or canon["f"] != 169 or short["g"] != 155:
        raise SystemExit(f"forensic costs did not recompute: canonical={canon} shortcut={short}")
    if not comparison["packs_differ"] or not comparison["symmetries_differ"]:
        raise SystemExit("shortcut tableau matched the canonical milestone")


def exhausted_packs(payload: dict) -> list:
    packs = []
    for row in payload.get("kept_endpoints") or []:
        pack = str(row.get("pack") or "")
        if pack:
            packs.append(pack)
    return packs


def historical_tactics(payload: dict) -> list:
    rows = []
    for item in payload.get("tactics") or []:
        search = item.get("search") or {}
        rows.append(
            {
                "root_index": item.get("root_index"),
                "met": search.get("met"),
                "g": search.get("g"),
                "paid": search.get("paid"),
                "unique": search.get("unique"),
                "expanded": search.get("expanded"),
                "elapsed_s": search.get("elapsed_s"),
                "min_f": search.get("min_f"),
                "min_h": search.get("min_h"),
                "max_h": search.get("max_h"),
                "diagnostics": search.get("diagnostics"),
                "policy_rerun": False,
            }
        )
    return rows


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
    comparison = compare_shortcut(checkpoints, canonical)
    oracle = oracle_window(checkpoints, canonical)
    require_oracle(oracle, comparison)
    print(comparison["reading"], flush=True)
    previous_milestone = load_json(PREVIOUS_MILESTONE)
    blocked_packs = exhausted_packs(previous_milestone)
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
        phase_aware=True,
    )
    print(
        f"GATE_B met={control.met} replay={control.replay_ok} stop={control.stop_reason} "
        f"g={control.g} h_telemetry={control.min_h} paid={control.paid} "
        f"unique={control.unique} expanded={control.expanded} "
        f"elapsed={control.elapsed_s:.3f}s cpu={control.cpu_s:.3f}s "
        f"phases_expanded={control.phases_expanded}",
        flush=True,
    )
    discovery = None
    tactic_rows = []
    endpoints = []
    kept = []
    dominated = []
    screens = []
    opened = []
    fair = None
    verification = None
    full_actions = []
    provenance = None
    outcome = "positive_control_failed"
    gate = "B"
    if not control_succeeded(control):
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
                phase_aware=True,
                hit_policy="lower_f",
            )
            print(
                f"TACTIC {index} g0={root.g} met={found.met} stop={found.stop_reason} "
                f"hits={len(found.hits)} first_g={found.first_g} "
                f"unique={found.unique} expanded={found.expanded} "
                f"elapsed={found.elapsed_s:.3f}s cpu={found.cpu_s:.3f}s "
                f"min_f={found.min_f} phases_admitted={found.phases_admitted} "
                f"phases_expanded={found.phases_expanded}",
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
                    "first_hit_paid": None if found.first_g is None else int(found.first_g) - int(root.g),
                    "first_hit_s": found.first_s,
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
        kept, dominated = retain_endpoints(endpoints, order="f")
        for item in kept:
            row = screening_milestone(item, ceiling=CEILING, excluded_packs=blocked_packs)
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
                as_continuation_roots(opened[:8]),
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
        portfolio_comparison = "paired"
    elif discovery is None:
        portfolio_comparison = "not run"
    else:
        portfolio_comparison = "historical only"
    best = None if not kept else min(kept, key=lambda item: (item.f, item.g, item.pack))
    historical = historical_tactics(previous_milestone)
    payload = {
        "schema": DRIVER_SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/phase-aware-milestone-v0-137",
        "outcome": outcome,
        "gate_stopped": gate,
        "workers": WORKERS,
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "exhausted_v0136_endpoint_rerun": False,
        "v0136_policy_rerun": False,
        "caps_raised": False,
        "v0_138_started": False,
        "reference_actions_seeded": False,
        "milestone_is_not_a_complete_game": True,
        "f_screen_is_not_a_proof": True,
        "ordering": {
            "phase_aware": True,
            "legacy_default_unchanged": True,
            "hit_policy": "lower_f",
            "endpoint_order": "f",
            "priorities_are_not_proof_bounds": True,
        },
        "forensic": comparison,
        "oracle": oracle,
        "exhausted_packs_excluded": blocked_packs,
        "exhausted_pack_loaded": bool(blocked_packs),
        "control_limits": {
            "paid_moves": CONTROL_PAID,
            "max_depth": CONTROL_DEPTH,
            "max_unique": CONTROL_UNIQUE,
            "time_limit_s": CONTROL_TIME_S,
            "rss_abort_mb": CONTROL_RSS_MB,
            "proof_ceiling": CONTROL_PROOF,
            "phase_aware": True,
        },
        "tactic_limits": {
            "paid_moves": TACTIC_PAID,
            "max_depth": TACTIC_DEPTH,
            "max_unique": TACTIC_UNIQUE,
            "time_limit_s": TACTIC_TIME_S,
            "rss_abort_mb": TACTIC_RSS_MB,
            "proof_ceiling": TACTIC_PROOF,
            "phase_aware": True,
            "hit_policy": "lower_f",
            "ran": discovery is not None,
        },
        "continuation_limits": {
            "max_unique": CONTINUATION_UNIQUE,
            "time_limit_s": CONTINUATION_TIME_S,
            "rss_abort_mb": CONTINUATION_RSS_MB,
            "ceiling": CEILING,
            "ran": fair is not None,
            "roots": "screened new milestone endpoints" if fair is not None else None,
        },
        "discovery_limits": {
            "depth": DISCOVERY_DEPTH,
            "paid_moves": DISCOVERY_PAID,
            "max_unique": DISCOVERY_UNIQUE,
            "time_limit_s": DISCOVERY_TIME_S,
            "rss_abort_mb": DISCOVERY_RSS_MB,
        },
        "control": control.public(),
        "portfolio_comparison": portfolio_comparison,
        "paired_with_v0134": paired_v0134,
        "paired_with_v0135": paired_v0135,
        "discovery": None if discovery is None else discovery.public(),
        "tactics": tactic_rows,
        "endpoint_candidates": len(endpoints),
        "kept_endpoints": [item.public() for item in kept],
        "best_kept": None if best is None else best.public(),
        "screen": screens,
        "opened_endpoints": [item.public() for item in opened],
        "dominated_endpoints": dominated,
        "historical_v0136_tactics": historical,
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
