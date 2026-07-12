"""Macro solver: beam shaping between stock deals + bounded finisher.

Deal timing now uses full-stock post-deal simulation (evaluate_post_deal) +
pending high-value work (same-suit + to-empty/0-cost) to choose when to stop
shaping and deal. This improves on pure pre-deal reception and avoids
exhausting low-value moves before dealing (see count_valuable_pre_deal_moves
and the best_deal_path logic in _beam_to_next_deal).
"""

from __future__ import annotations

import heapq
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .deal_analysis import DealAnalysis, build_deal_analysis
from .engine import SpiderState
from .hash import zobrist
from .heuristics import (
    clear_eval_cache,
    count_valuable_pre_deal_moves,
    deal_aware_score,
    evaluate_post_deal,
    last_deal_assignment_bonus,
    pre_deal_readiness,
    reception_fitness,
    space_creation_potential,
)
from .metrics import Action
from .search import (
    SearchResult,
    bounded_finisher,
    clear_search_caches,
    dominance_filter,
    note_progress,
    order_moves,
    step_cost,
)

Move = Tuple[int, int, int]


@dataclass
class MacroConfig:
    per_round_secs: float = 2.0
    beam_width: int = 1200
    max_expansions: int = 4000
    finish_secs: float = 8.0
    finish_beam: int = 900
    jitter: float = 0.12
    restarts: int = 4
    upper_bound: int = 163
    reception_threshold: int = 9


@dataclass
class MacroResult:
    solved: bool
    actions: List[Action]
    mw_cost: int
    nodes: int
    seconds: float
    deals_used: int


def _beam_to_next_deal(
    root: SpiderState,
    analysis: DealAnalysis,
    round_index: int,
    *,
    g_so_far: int,
    upper_bound: int,
    time_limit: float,
    beam_width: int,
    max_expansions: int,
    jitter: float,
    reception_threshold: int = 9,
) -> Tuple[SpiderState, List[Move], int]:
    """Best-first beam to shape tableau before the next stock deal.

    Runs full time/exp budget. In addition to pre_deal_readiness (spaces, rec,
    low g, tails, + plan_eligibility from the global clearance plan...), we also
    evaluate the *actual post-deal* quality (evaluate_post_deal, now including
    post_plan bonus) and pending high-value work.

    The DealAnalysis (analysis) now carries the results of the upfront global
    "reverse-engineering" pass (cumulatives, eligible_suits_by_round, priority
    order, initial buried columns for priority suits). This is used in the
    scoring functions and ordering to identify optimal columns to clear and
    to heavily value exposing/ building for suits that can/should be cleared
    "soon" per the full stock -- the higher-level human planning the user
    described.

    The returned shaping path is chosen preferring the pre-state from which
    actually taking the deal produces the best post-deal outlook *and* where
    most high-value work (and plan-critical exposures) has already been completed.

    Falls back gracefully to older rec-based / pre-only selection.
    """
    start = time.time()
    nodes = 0
    remaining = upper_bound - g_so_far
    if remaining <= 0:
        return root, [], 0

    last_bonus = 0
    if round_index == 4 and len(analysis.incoming_by_round) >= 5:
        last_bonus = last_deal_assignment_bonus(root, analysis.incoming_by_round[4])

    # Early-round extra shaping budget (v35+): r0 (initial layout, sw=10 start) is the root of compounding (v33 baseline r0 final 21-29; v34 boosted sample 30+). Crank the multiplier higher (2.5x time/exp for r0, 1.8x for r1) so the beam has substantially more opportunity to find the net sw-reducing catalytic sequences before the deal choice / gate. Combined with stronger ordering (min20*2.5) and -30*sw heap.
    effective_time_limit = time_limit
    effective_max_exp = max_expansions
    if round_index == 0:
        effective_time_limit = time_limit * 2.5
        effective_max_exp = int(max_expansions * 2.5)
    elif round_index == 1:
        effective_time_limit = time_limit * 1.8
        effective_max_exp = int(max_expansions * 1.8)
    elif round_index == 2:
        # r3-specific extra shaping (v37+): bumped to *2.5 (matching r0 strength) after v36 1.8x gave only marginal r3 improvement (23-24 vs prior 20-26). Goal: push r3 pre final sw into low teens/single digits or surface low-sw best_deal for the known 10, using the same extra runway that got canon r0 to 15.
        effective_time_limit = time_limit * 2.5
        effective_max_exp = int(max_expansions * 2.5)

    score_tt: dict[tuple[int, int], tuple] = {}
    frontier: List[Tuple[Tuple, int, int, SpiderState, List[Move], int]] = []
    root_copy = root.clone()
    heapq.heappush(
        frontier,
        (
            deal_aware_score(root_copy, analysis, round_index, last_bonus),
            id(root_copy),
            0,
            root_copy,
            [],
            0,
        ),
    )
    best_path: List[Move] = []
    best_q = pre_deal_readiness(root_copy, analysis, round_index, 0)
    acceptable_path: List[Move] = []
    acceptable_q = (-999,)

    # New tracking for improved deal-timing strategy (full stock knowledge).
    # We evaluate at states "what would the post-deal tableau actually look like?"
    # (using the exact known next 10 cards) and how much high-value work
    # (same-suit builds + to-empty / 0-cost opportunities) is still pending.
    # The best_deal_path is the pre-deal sequence after which taking the deal
    # produces the strongest result while having cleared most of the valuable work.
    best_deal_path: List[Move] | None = None
    best_deal_key = (-999,)

    while frontier and time.time() - start < effective_time_limit and nodes < effective_max_exp:
        score, _, depth, state, path, g = heapq.heappop(frontier)
        if g >= remaining:
            continue
        tt_key = (round_index, zobrist(state))
        prev = score_tt.get(tt_key)
        if prev is not None and prev <= score:
            continue
        score_tt[tt_key] = score

        q = pre_deal_readiness(state, analysis, round_index, g)
        if q > best_q:
            best_q = q
            best_path = list(path)
        rec = q[1]  # 2nd element is rec
        if rec >= reception_threshold and q > acceptable_q:
            acceptable_q = q
            acceptable_path = list(path)

        # === Core of the requested strategy improvement ===
        # At states with reasonable reception for the *known* next deal, simulate
        # "if I deal right now, what is the quality of the resulting tableau?"
        # (actual landing + auto check_seq, new runs/clears created by the 10 cards,
        # post spaces/tails etc.). Also measure pending high-value moves (same-suit
        # attachments + moves to empty, which include the 0-cost whole-stack cases).
        #
        # This lets us:
        # - Score the pre state by the *post-deal* outcome (what the user asked for).
        # - Prefer to deal after high-value same-suit work is done (avoid "exhaust
        #   every low-value off-suit move before dealing" rookie error).
        # - Naturally value 0-cost whole-column-to-empty moves (they improve the
        #   post-deal outlook for "free" in MW cost, and the -g + post quality
        #   will prefer paths that used them to set up a better receiver).
        if rec >= 0:  # evaluate on all (or raise floor to e.g. 3 to save clones)
            pending = count_valuable_pre_deal_moves(state)
            next_cards = (
                analysis.incoming_by_round[round_index]
                if round_index < len(analysis.incoming_by_round)
                else []
            )
            post_q = evaluate_post_deal(state, next_cards, plan=analysis, round_index=round_index) if next_cards else (0, 0, 0, 0, 0, 0, 0, 0)
            post_plan = post_q[6] if len(post_q) > 6 else 0
            post_sp_pot = post_q[7] if len(post_q) > 7 else 0

            # Cheap future-lookahead for r < last: after landing this deal's cards, how good is the
            # resulting state for the *following* known deal? This addresses myopic per-deal choice
            # (a locally good post for r may leave bad structure/spaces for r+1). Uses full stock.
            future_rec = 0
            if round_index + 1 < len(analysis.incoming_by_round):
                next_next = analysis.incoming_by_round[round_index + 1]
                pst = state.clone()
                for ii in range(min(10, len(next_cards))):
                    pst.columns[ii].face_up.append(next_cards[ii])
                    pst.check_seq(ii)
                future_rec = reception_fitness(pst, next_next)

            # Higher-is-better key for "best moment to stop shaping and deal":
            # foundations created by the deal itself, good post-deal structure,
            # (relaxed) pending high-value work left (now includes enabling parks + space work), plan progress after deal,
            # future_rec (lookahead to next deal's reception after this one), post space potential after landing,
            # low g, ...
            # Direct space work: total visible face-up sitting on columns with remaining face-down (the exact blockers to creating new spaces).
            space_work = sum(len(c.face_up) for c in state.columns if c.face_down)
            # Front-load the space_work term (right after post_found/post_spaces) and make it *dominant* so that even large advantages in post_plan/future_rec/post_sp_pot cannot outweigh high visible work on fd columns.
            # This ensures a "good post for these exact 10" is only considered best_deal if the pre-deal shape has also done the gold space-creation work (human ~23 valuable / low sw at deal decisions).
            sw_term = -space_work * 50
            if space_work > 5:
                sw_term -= 5000  # extra gate: any sw>5 is heavily disfavored for best_deal recording
            if space_work > 10:
                sw_term -= 10000
            if space_work > 15:
                sw_term = -999999  # hard veto
            if space_work >= 8:
                sw_term = -999999  # strengthened hard veto for recording: sw>=8 states (r3's typical best-post candidates at sw9) cannot win best_deal key; search must keep shaping until it finds low-sw (<=7) + competitive post/plan/future for those specific cards
            deal_key = (
                post_q[0],      # foundations_made by landing the known 10
                post_q[1],      # post spaces
                sw_term,        # *dominant* sw penalty (front-loaded + scaled + gated); only low-sw states can win best_deal
                post_plan * 5,  # amplified global plan progress from the upfront eligibility analysis
                -pending * 1.0, # stronger penalty for high pending (incl space_work) to force more shaping before deal
                future_rec * 3, # lookahead: prefer pre-deal states for this round that also leave the post-state well-positioned for the *subsequent* known deal
                post_sp_pot * 25, # further boosted post space creation potential after this deal lands
                -g,
                post_q[2],      # post tails
                post_q[3],      # -kp etc.
            )
            sw_for_veto = sum(len(c.face_up) for c in state.columns if c.face_down)
            if sw_for_veto >= 8:
                # HARD VETO (strengthened): do not record *any* sw>=8 state as best_deal. Only states with space_work <=7 (matching the human target low sw at deal decisions and r2 success) can ever become best_deal for the round. This prevents sw~9 "best post" candidates (r3 etc.) from locking in early and forces the search to keep shaping until it finds a low-sw + competitive post/plan/future state.
                pass
            elif deal_key > best_deal_key:
                best_deal_key = deal_key
                best_deal_path = list(path)
                post_sp = post_q[7] if len(post_q) > 7 else 0
                curr_sp = space_creation_potential(state)
                sw = sw_for_veto
                print(f"[strategy] r{round_index} NEW best_deal pending={pending} post_found={post_q[0]} post_spaces={post_q[1]} post_sp_pot={post_sp} curr_sp_pot={curr_sp} space_work={sw} g={g} rec={rec}")

        moves = dominance_filter(state, state.enumerate_moves())
        moves = order_moves(state, moves, depth, jitter=jitter, plan=analysis, round_index=round_index)

        for m in moves:
            if not state.can_move(*m):
                continue
            step = step_cost(state, m)
            ng = g + step
            if ng >= remaining:
                continue
            st = state.clone()
            st.move(*m)
            nodes += 1
            lm = st.last_move
            if lm and len(lm) >= 5 and (lm[3] or lm[4]):
                note_progress(depth, m)
            heapq.heappush(
                frontier,
                (
                    deal_aware_score(st, analysis, round_index, last_bonus),
                    id(st),
                    depth + 1,
                    st,
                    path + [m],
                    ng,
                ),
            )

        if len(frontier) > beam_width:
            frontier = frontier[:beam_width]

    # Prefer the path chosen by the new "best time to deal" logic (post-deal simulation
    # quality + low pending high-value work + low g). This is the main point of the
    # improvement: the beam now decides *when* to deal by assessing the actual
    # post-deal tableau (using full stock knowledge) and preferring states where
    # the valuable same-suit / 0-cost work has already been done.
    # Falls back to previous acceptable (rec-based) or pure pre readiness.
    # Choose among the three candidates (best_deal from post-sim+key, acceptable rec, or pure pre heap best).
    # *Strongly* bias toward the one with the lowest space_work (visible work on fd columns).
    # If the best_deal path still has high sw (>10), prefer the absolute lowest-sw candidate even if its
    # post-sim key is slightly worse — this forces "only deal the known cards when space creation progress
    # on the critical columns is good" (human chooses at valuable ~23 / low sw; beam was previously choosing
    # at 48-58 / sw 18-22 on reference because a "good post" state won the key).
    candidates = []
    if best_deal_path is not None:
        candidates.append(('best_deal', best_deal_path))
    if acceptable_path:
        candidates.append(('acceptable', acceptable_path))
    if best_path:
        candidates.append(('pre', best_path))
    if not candidates:
        chosen_path = []
        deal_type = 'none'
    else:
        best_sw = 9999
        chosen_path = candidates[0][1]
        deal_type = candidates[0][0]
        best_key_for_sw = None
        for typ, pth in candidates:
            try:
                bs = root.clone()
                for m in pth:
                    if m != ("deal",):
                        bs.move(*m)
                sw = sum(len(c.face_up) for c in bs.columns if c.face_down)
                if sw < best_sw or (sw == best_sw and (best_key_for_sw is None or True)):
                    best_sw = sw
                    chosen_path = pth
                    deal_type = typ
            except Exception:
                pass
        # Stricter override: if the "best" (by previous key) has high sw, force the lowest sw path
        # (this is the "don't declare the pre-deal shape good until the gold spaces are close").
        if best_sw > 0:  # always prefer the absolute lowest sw path (human chooses at very low sw; force the beam to the lowest sw candidate regardless of key)
            # re-pick purely by lowest sw (ignore key differences for high-sw best_deal)
            min_sw = 9999
            min_sw_path = chosen_path
            min_sw_typ = deal_type
            for typ, pth in candidates:
                try:
                    bs = root.clone()
                    for m in pth:
                        if m != ("deal",):
                            bs.move(*m)
                    sw = sum(len(c.face_up) for c in bs.columns if c.face_down)
                    if sw < min_sw:
                        min_sw = sw
                        min_sw_path = pth
                        min_sw_typ = typ
                except Exception:
                    pass
            if min_sw < best_sw:
                chosen_path = min_sw_path
                deal_type = min_sw_typ + "_lowsw_override"
                best_sw = min_sw
    # Space gate (stricter after v26 data): if the lowest-sw candidate among best_deal/acceptable/pre is still >5 (human success at ~7/20.5 for r2, 23.0 valuable at decision),
    # and a pure pre path exists (the beam's best effort under the sw-penalizing deal_aware heap), *force the pre path*.
    # This refuses to "deal the known cards" on a high-sw best_deal (e.g. r3 0-path with sw=21-27); instead return the shaped pre work so the phase invests in space creation first.
    # Only a best_deal (or acceptable) whose simulated ending sw <=5 will be allowed to trigger the deal for that round's known 10.
    if deal_type in ('best_deal', 'best_deal_lowsw_override', 'acceptable') and best_sw >= 8:  # accept best_deal when it reaches the observed human success point (sw=7 / pending~20.5 for r2, pre_valuable=23.0 at analyzer DEAL); only force the pre path for candidates >=8 (worse than the gold low-sw states the search can find)
        pre_cand = next((pth for typ, pth in candidates if typ == 'pre'), None)
        if pre_cand is not None:
            chosen_path = pre_cand
            deal_type = deal_type + '_forced_pre_by_space_gate_sw' + str(best_sw)
            # re-compute best_sw for the forced pre (for the final print)
            try:
                bs = root.clone()
                for m in chosen_path:
                    if m != ("deal",):
                        bs.move(*m)
                best_sw = sum(len(c.face_up) for c in bs.columns if c.face_down)
            except Exception:
                pass
    final_pending = count_valuable_pre_deal_moves(state) if 'state' in locals() else -1
    final_sw = sum(len(c.face_up) for c in state.columns if c.face_down) if 'state' in locals() else -1
    print(f"[strategy] r{round_index} chosen via {deal_type}, path_len={len(chosen_path)} final_pending={final_pending} final_space_work={final_sw}")

    # Reconstruct a state for the (rarely-used) first return value so API stays stable.
    if chosen_path:
        bs = root.clone()
        for m in chosen_path:
            bs.move(*m)
        best_state = bs
    else:
        best_state = root
    return best_state, chosen_path, nodes


def macro_solve(
    state: SpiderState,
    analysis: DealAnalysis,
    *,
    config: MacroConfig | None = None,
    progress: bool = False,
    start_round: int = 0,
) -> MacroResult:
    """Run macro beam-shaping + deals from current state (possibly mid-game).

    start_round allows starting after a scripted human prefix (e.g. after deal #1
    or #2). The round_index selects the correct slice of analysis.incoming_by_round
    for reception and last-deal bonus. If the passed state already has few stock
    cards left, the while loop naturally runs fewer (or zero) deal phases and
    heads straight to the finisher.
    """
    cfg = config or MacroConfig()
    clear_eval_cache()
    clear_search_caches()

    full_path: List[Action] = []
    g = 0
    total_nodes = 0
    round_index = start_round

    while round_index < 5 and len(state.stock) >= 10:
        if g >= cfg.upper_bound:
            break
        shaped, path, nodes = _beam_to_next_deal(
            state,
            analysis,
            round_index,
            g_so_far=g,
            upper_bound=cfg.upper_bound,
            time_limit=cfg.per_round_secs,
            beam_width=cfg.beam_width,
            max_expansions=cfg.max_expansions,
            jitter=cfg.jitter,
            reception_threshold=cfg.reception_threshold,
        )
        for m in path:
            g += state.move(*m)
            full_path.append(m)
        if g >= cfg.upper_bound:
            break
        if progress:
            print(f"[macro] round {round_index + 1} shaped {len(path)} moves, g={g}")
        g += state.deal()
        full_path.append(("deal",))
        round_index += 1
        total_nodes += nodes

    if g < cfg.upper_bound:
        fin = bounded_finisher(
            state,
            upper_bound=cfg.upper_bound,
            time_limit=cfg.finish_secs,
            beam_width=cfg.finish_beam,
            jitter=cfg.jitter,
            progress=progress,
        )
        total_nodes += fin.nodes
        for m in fin.actions:
            if m == ("deal",):
                g += state.deal()
            else:
                g += state.move(*m)
            full_path.append(m)
        if fin.solved:
            return MacroResult(
                True,
                full_path,
                g,
                total_nodes,
                fin.seconds,
                round_index,
            )

    return MacroResult(
        state.is_solved(),
        full_path,
        g if state.is_solved() else 9999,
        total_nodes,
        0.0,
        round_index,
    )


def macro_solve_with_restarts(
    root: SpiderState,
    tokens: List[str],
    *,
    config: MacroConfig | None = None,
    progress: bool = False,
    start_round: int = 0,
) -> MacroResult:
    cfg = config or MacroConfig()
    analysis = build_deal_analysis(tokens)  # now includes the global suit clearance / exposure plan
    print(f'[global-plan] priority={analysis.priority_clearance_order} elig_after_r0={analysis.eligible_suits_by_round[0]} buried_priority={ {s: analysis.initial_buried_columns_by_suit.get(s) for s in analysis.priority_clearance_order[:2]} }')
    best = MacroResult(False, [], 9999, 0, 0.0, 0)
    last = best

    for r in range(cfg.restarts):
        random.seed(1000 + r)
        st = root.clone()
        res = macro_solve(st, analysis, config=cfg, progress=progress, start_round=start_round)
        last = res
        if res.solved and res.mw_cost < best.mw_cost:
            best = res
        if res.solved and res.mw_cost < cfg.upper_bound:
            return best
    return best if best.solved else last


def run_until_improved(
    root: SpiderState,
    tokens: List[str],
    *,
    initial_bound: int,
    aspire: int = 119,
    on_save: Optional[Callable[[int, List[Action]], None]] = None,
    progress: bool = True,
    start_round: int = 0,
) -> MacroResult:
    """Long-running loop: escalate budgets and tighten bound on improvements."""
    upper_bound = initial_bound
    global_best = MacroResult(False, [], 9999, 0, 0.0, 0)

    secs = 2.0
    beam = 1200
    finish = 8.0
    growth = 1.35
    attempt = 0

    while upper_bound > aspire:
        attempt += 1
        cfg = MacroConfig(
            per_round_secs=secs,
            beam_width=beam,
            finish_secs=finish,
            upper_bound=upper_bound,
            restarts=6,
        )
        if progress:
            print(
                f"\n=== Attempt {attempt} | bound={upper_bound} | "
                f"secs={secs:.1f} beam={beam} finish={finish:.1f} ==="
            )
        res = macro_solve_with_restarts(root, tokens, config=cfg, progress=progress, start_round=start_round)
        if res.solved and res.mw_cost < upper_bound:
            upper_bound = res.mw_cost
            global_best = res
            if progress:
                print(f"*** NEW BEST: {res.mw_cost} MW moves (target {aspire}) ***")
            if on_save:
                on_save(res.mw_cost, res.actions)
            # Durable external archive on every verified complete improvement.
            try:
                from spider.solution_archive import record_solution_if_better

                arch = record_solution_if_better(
                    "4925153",
                    res.actions,
                    source="macro_solve_with_restarts",
                    experiment_id="macro_solve",
                )
                if arch.current_best_updated and progress:
                    print(
                        f"*** EXTERNAL ARCHIVE mw={arch.candidate_mobilityware_moves} "
                        f"→ {arch.parser_ready_path} ***"
                    )
                if arch.candidate_mobilityware_moves is not None:
                    upper_bound = min(upper_bound, int(arch.candidate_mobilityware_moves))
            except Exception as _arch_exc:  # noqa: BLE001
                if progress:
                    print(f"EXTERNAL ARCHIVE error: {_arch_exc}")
            if res.mw_cost <= aspire:
                break
        secs = min(60.0, secs * growth)
        beam = min(4000, int(beam * growth))
        finish = min(300.0, finish * growth)

    return global_best