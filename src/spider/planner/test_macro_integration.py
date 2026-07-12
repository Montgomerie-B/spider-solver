"""
First 'layered-assisted' end-to-end test (per baselined plan Phase 6 direction).

Uses the Layer 5 minimal plan beam (or controller) to shape the first round (pre first deal) from the initial layout or a checkpoint, producing a 'layered-shaped' state.

Then falls back to the legacy _beam_to_next_deal or macro machinery for the remaining rounds/finisher.

Records solve/cost/nodes for comparison to pure legacy runs.

This is the first concrete step toward integrating the new planner as a drop-in shaper in the old macro/harness, while keeping everything non-destructive.

Run with: PYTHONPATH=src python -m spider.planner.test_macro_integration
"""

from __future__ import annotations

from pathlib import Path

from spider.deal import load_deal
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.macro import _beam_to_next_deal, macro_solve_with_restarts, MacroConfig
from spider.planner.plan_search import minimal_plan_beam_search
from spider.planner.dependency import DynamicDependencyAnalyser
from spider.metrics import export_actions_to_moves_file, replay_actions, mw_cost_for_actions  # for replay-valid candidate export from layered+legacy


def test_layered_first_round_then_legacy(
    deal_path: str = "deals/4925153.txt",
    use_checkpoint: bool = False,  # False = from initial (full), True = from human checkpoint for partial
    checkpoint_moves: str = "solutions/4925153_canonical.moves",
    high_budget: bool = False,  # for the higher-budget hunt per plan
    medium_budget: bool = False,  # observable medium (deeper early beams than modest, faster than full high)
    use_shaper: bool = False,  # NEW: use layered_shape_round helper instead of full beam (simpler for exposure)
):
    print("=== Layered First Round + Legacy Rest Test (early integration) ===")

    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    if use_checkpoint:
        from spider.planner.dependency import load_human_pre_deal1_state
        state, applied = load_human_pre_deal1_state(deal_path, checkpoint_moves)
        print(f"Starting from human checkpoint after {applied} moves (partial layered assist).")
        start_round = 0  # still pre first deal in this checkpoint
    else:
        state = SpiderState.from_cards(cards)
        print("Starting from initial layout (full layered assist for round 0).")
        start_round = 0

    initial_sw = sum(len(c.face_up) for c in state.columns if c.face_down)
    initial_spaces = len(analyser.analyze(state).space_opportunities)
    print(f"Start: spaces={initial_spaces}, sw={initial_sw}")

    # 1. Use Layer 5 beam (or shaper helper) to 'shape' the current round
    if use_shaper:
        print("\nUsing layered_shape_round helper for shaping (Phase 6 exposure)...")
        from spider.planner.controller import layered_shape_round
        shaper_steps = 12 if medium_budget or high_budget else 8
        shaped_state, shape_cost, shape_moves, _unlock_earned = layered_shape_round(state, analysis, max_realize_steps=shaper_steps)  # realizer now returns park unlock count for L4; ignored here for candidate export compat
        print(f"Shaper: cost={shape_cost}, final spaces={len(analyser.analyze(shaped_state).space_opportunities)}, shape_moves={len(shape_moves)} (steps={shaper_steps})")
    else:
        print("\nRunning Layer 5 beam for shaping (plan choices + realization)...")
        beam_nodes = minimal_plan_beam_search(deal_path, checkpoint_moves if use_checkpoint else "solutions/4925153_canonical.moves", beam_width=2, max_steps=2)
        if beam_nodes:
            best_node = beam_nodes[0]
            shaped_state = best_node.state
            print(f"Beam best: {best_node.active_plan.name}, steps={best_node.steps_taken}, cost={best_node.total_cost}, final spaces={len(analyser.analyze(shaped_state).space_opportunities)}")
        else:
            shaped_state = state.clone()
            print("No beam nodes, using start state.")

    shaped_sw = sum(len(c.face_up) for c in shaped_state.columns if c.face_down)
    shaped_spaces = len(analyser.analyze(shaped_state).space_opportunities)
    print(f"After layered shaping: spaces={shaped_spaces}, sw={shaped_sw}")

    # 2. Fall back to legacy for the rest (subsequent rounds + finisher)
    print("\nFalling back to legacy macro for remaining rounds/finisher...")
    # For simplicity, continue from shaped_state with legacy _beam for next rounds, or full macro_solve
    # To simulate 'one layered round + legacy rest', we can call the legacy beam for round 0 equivalent or continue the macro.
    # Here: use legacy _beam_to_next_deal for the current 'round' if needed, then macro for rest.
    # But since we already shaped with beam, call macro_solve_with_restarts from here (it will do deals + beams).
    # To keep it 'layered for first, legacy for rest', we can manually do one legacy beam then deal etc, but for first test use full legacy from shaped.
    if high_budget:
        cfg = MacroConfig(per_round_secs=35, beam_width=6000, max_expansions=50000, finish_secs=70, finish_beam=1000, restarts=2)
        print("Using HIGH budget cfg for hunt (35s/6000/50k like old vN).")
    elif medium_budget:
        cfg = MacroConfig(per_round_secs=12, beam_width=2500, max_expansions=12000, finish_secs=20, finish_beam=600, restarts=1)
        print("Using MEDIUM budget cfg (12s/2500/12k, restarts=1) for observable deeper early beams + candidate.")
    else:
        cfg = MacroConfig(per_round_secs=8, beam_width=800, max_expansions=4000, finish_secs=5, finish_beam=400, restarts=1)
    res = macro_solve_with_restarts(shaped_state, tokens, config=cfg, progress=True, start_round=start_round)
    print(f"Legacy rest result: solved={res.solved}, mw_cost={res.mw_cost}, nodes={res.nodes}")

    # Phase 6/7: if we used the shaper, capture full replay-valid action list (shape prefix moves + legacy .actions)
    # and export a .moves file + validate with metrics replay (first such artifact from layered+legacy).
    if use_shaper:
        post_shaper_actions = list(shape_moves) + list(getattr(res, "actions", []))
        kind = "full_from_initial" if not use_checkpoint else "from_human_checkpoint"
        if high_budget:
            budget_tag = "high"
        elif medium_budget:
            budget_tag = "medium"
        else:
            budget_tag = "modest"
        cand_path = Path("src/spider/planner/diagnostics") / f"planner_shaper_{kind}_{budget_tag}.moves"
        header = (
            f"Layered planner shaper (L2-5 via layered_shape_round) + legacy macro_solve_with_restarts rest.\n"
            f"Deal {deal_path} {'from human 51-move checkpoint' if use_checkpoint else 'from initial layout'}.\n"
            f"Shaper cost={shape_cost} | legacy mw_cost={res.mw_cost} | approx total={shape_cost + res.mw_cost}.\n"
            f"Solved={res.solved} nodes={res.nodes}. This is a replay-valid candidate path from the new architecture (compare to canonical 163)."
        )
        try:
            export_actions_to_moves_file(post_shaper_actions, cand_path, header=header)
            print(f"\n[Candidate] Exported replay-valid .moves to {cand_path}")
            if not use_checkpoint:
                # Full from initial: safe to replay the complete action list from fresh initial
                initial_for_replay = SpiderState.from_cards(load_deal(Path(deal_path)))
                replayed_cost = replay_actions(initial_for_replay.clone(), post_shaper_actions)
                expected = shape_cost + res.mw_cost
                print(f"[Candidate] Replay-validated MW cost: {replayed_cost} (expected {expected}) match={replayed_cost == expected}")
                check_cost = mw_cost_for_actions(SpiderState.from_cards(load_deal(Path(deal_path))), post_shaper_actions)
                print(f"[Candidate] mw_cost_for_actions check: {check_cost}")
            else:
                print("[Candidate] (from checkpoint) Exported delta actions only (shaper+rest from human 51-move point); prepend canonical prefix for full replay validation.")
        except Exception as e:
            print(f"[Candidate] Export/validation failed: {e}")

    print("\n=== Summary ===")
    print(f"Layered assist for first round + legacy rest: cost={res.mw_cost}, solved={res.solved}")
    print("(Compare to pure legacy runs on same deal/budget for whether the campaign-shaped start helps.)")

    return res


if __name__ == "__main__":
    test_layered_first_round_then_legacy(use_checkpoint=False)  # full from initial
    print("\n--- Also test from human checkpoint (partial assist) ---")
    test_layered_first_round_then_legacy(use_checkpoint=True)

# Note for higher-budget hunt (as next best per plan):
# To hunt for solve/cost improvement vs pure legacy:
# - Edit the cfg in the test to higher per_round_secs/beam (e.g. 35s, beam=6000, max_exp=50000, restarts=2) like the old high-budget vN runs.
# - Or call with the old run_until_improved style from macro.
# - Compare the final mw_cost/nodes/solved to pure legacy with same cfg on the same start.
# - The layered beam provides the campaign-shaped start; legacy does the heavy lifting for later rounds.
# This would be the first measurable 'does explicit human-campaign shaping for early rounds help the overall solve on this deal?' data point.
# Run and append result to the diagnostics artifact.