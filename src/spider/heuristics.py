"""Search heuristics: admissible lower bounds and beam priority keys."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .deal_analysis import DealAnalysis
from .engine import Column, SpiderState
from .cards import Card
from .hash import zobrist

_EVAL_CACHE: Dict[Tuple[int, int], Tuple] = {}


def clear_eval_cache() -> None:
    _EVAL_CACHE.clear()


def same_suit_tail_len(col: Column) -> int:
    run = col.face_up
    if not run:
        return 0
    suit = run[-1].suit
    n = 1
    for i in range(len(run) - 1, 0, -1):
        if run[i - 1].suit == suit and run[i - 1].rank == run[i].rank + 1:
            n += 1
        else:
            break
    return n


def king_pressure(state: SpiderState) -> int:
    p = 0
    for col in state.columns:
        up = col.face_up
        for i, c in enumerate(up):
            if c.rank == 13 and i != len(up) - 1:
                p += 1
    return p

def space_creation_potential(state: SpiderState) -> int:
    """Progress toward creating net new spaces from columns that still have face-down.
    Rewards *low* current face-up on fd columns (closer to being able to clear them by moving the small run off, using parks/builds).
    High fu on fd col means more work to clear for the space. This better captures the 'ready to clear' state for space gold.
    Boosted in priority to push the beam to clear the critical fd cols (only 2 in the prefix state) before dealing.
    """
    pot = 0
    for col in state.columns:
        if col.face_down:  # this column can yield a new space if fully cleared
            fu_len = len(col.face_up)
            pot += max(0, 10 - fu_len)  # higher for low fu (close to clear)
            if fu_len == 0:
                pot += 5  # ready to flip/clear
    return pot


def reception_fitness(state: SpiderState, next_round_cards: List) -> int:
    hooks = [col.top() for col in state.columns]
    score = 0
    for c in next_round_cards:
        best = -2
        for h in hooks:
            if h is None:
                v = 2 if c.rank == 13 else 0
            elif h.suit == c.suit and h.rank == c.rank + 1:
                v = 3
            elif h.rank == c.rank + 1:
                v = 1
            else:
                v = -1
            if v > best:
                best = v
        score += best
    score += sum(1 for col in state.columns if col.is_empty())
    return score


def lower_bound_mw(state: SpiderState) -> int:
    """Admissible-ish lower bound on remaining MW cost to win."""
    deals_left = len(state.stock) // 10
    clears_needed = max(0, 8 - len(state.foundations))
    face_down = sum(len(c.face_down) for c in state.columns)
    # Each deal costs 1; each foundation needs at least one paid move in practice.
    return deals_left + clears_needed + max(0, face_down // 13)


def deal_aware_score(
    state: SpiderState,
    analysis: DealAnalysis,
    round_index: int,
    last_assign_bonus: int = 0,
) -> Tuple:
    key = (round_index, zobrist(state))
    cached = _EVAL_CACHE.get(key)
    if cached is not None:
        return cached
    next_cards = (
        analysis.incoming_by_round[round_index]
        if round_index < len(analysis.incoming_by_round)
        else []
    )
    spaces = sum(1 for c in state.columns if c.is_empty())
    cleared = len(state.foundations)
    tails = sum(same_suit_tail_len(c) for c in state.columns)
    kp = king_pressure(state)
    rec = reception_fitness(state, next_cards) if next_cards else 0
    plan_bonus = plan_eligibility_score(state, analysis, round_index) if analysis is not None else 0
    sp_pot = space_creation_potential(state)
    # Direct space work left on columns that can still produce a space. Penalize heavily in main beam priority
    # so expansions prefer states that move visible runs off the fd columns (the catalytic work for "gold" spaces).
    sw = sum(len(c.face_up) for c in state.columns if c.face_down)
    score = (
        -plan_bonus * 10,  # global plan progress FIRST and strong
        -8 * cleared,
        -4 * spaces,
        -12 * sp_pot,  # progress on columns that can create net new spaces
        -30 * sw,      # v34 bump (early boost era): even stronger heap bias on sw for r0/r1 (and all) so the extra shaping budget actually finds pre paths that reduce visible fu on fd columns. Combined with early effective_time/exp *1.6 and strict guard, targets final_sw <<21 for r0 pre (human invests in catalytic work to get low sw + spaces pre-deal1).
        -2 * tails,
        -5 * rec,
        +6 * kp,
        -last_assign_bonus,
        sum(len(c.face_down) for c in state.columns),
    )
    _EVAL_CACHE[key] = score
    return score


def finisher_heuristic(state: SpiderState) -> Tuple:
    spaces = sum(1 for c in state.columns if c.is_empty())
    cleared = len(state.foundations)
    kp = king_pressure(state)
    sp_pot = space_creation_potential(state)
    return (-8 * cleared, -4 * spaces, -8 * sp_pot, +6 * kp)  # even stronger sp_pot: reward low sw states in finisher too


def hungarian(cost: List[List[int]]) -> Tuple[int, List[int]]:
    n = len(cost)
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
            while True:
                j1 = way[j0]
                p[j0] = p[j1]
                j0 = j1
                if j0 == 0:
                    break
    assignment = [0] * n
    for j in range(1, n + 1):
        assignment[p[j] - 1] = j - 1
    return int(-v[0]), assignment


def last_deal_assignment_bonus(state: SpiderState, last_round: List) -> int:
    cost = [[5] * 10 for _ in range(10)]
    hooks = [c.top() for c in state.columns]
    for i, card in enumerate(last_round):
        for j, h in enumerate(hooks):
            if h is None:
                cost[i][j] = 0 if card.rank == 13 else 3
            elif h.rank == card.rank + 1 and h.suit == card.suit:
                cost[i][j] = 0
            elif h.rank == card.rank + 1:
                cost[i][j] = 1
            elif h.rank > card.rank:
                cost[i][j] = 4
            else:
                cost[i][j] = 5
    _, assign = hungarian(cost)
    hooks = [c.top() for c in state.columns]
    bonus = 0
    for i, j in enumerate(assign):
        card = last_round[i]
        h = hooks[j]
        if h is None and card.rank == 13:
            bonus += 2
        elif h and h.rank == card.rank + 1 and h.suit == card.suit:
            bonus += 3
        elif h and h.rank == card.rank + 1:
            bonus += 1
    return bonus


def pre_deal_readiness(
    state: SpiderState, analysis: DealAnalysis, round_index: int, g: int = 0
) -> Tuple:
    """Multi-objective score for selecting best pre-deal shaped state (higher better).

    Prioritizes human strategies from strategy_insights.md + global clearance plan:
    - Primary: more empty columns (spaces are "gold").
    - High reception fitness for the specific upcoming deal round.
    - Low path cost (g) to reach the shape.
    - Long same-suit tails, low king pressure, fewer face-down, more cleared.
    - Plan progress on early-eligible suits (from upfront reverse-engineering of
      which suits can be cleared when, and which columns/cards are critical to expose).
    Used by beam to pick among explored states instead of first rec>=thresh.
    Tuple now has 8 elements (plan_bonus appended).
    """
    spaces = sum(1 for c in state.columns if c.is_empty())
    next_cards = (
        analysis.incoming_by_round[round_index]
        if round_index < len(analysis.incoming_by_round)
        else []
    )
    rec = reception_fitness(state, next_cards) if next_cards else 0
    tails = sum(same_suit_tail_len(c) for c in state.columns)
    kp = king_pressure(state)
    fd = sum(len(c.face_down) for c in state.columns)
    cleared = len(state.foundations)
    plan_bonus = plan_eligibility_score(state, analysis, round_index) if analysis is not None else 0
    sp_pot = space_creation_potential(state)
    # Higher tuple wins; plan progress FIRST and amplified...
    # sp_pot promoted earlier (after spaces) to strongly reward progress toward creating spaces during pre-deal shaping.
    return (plan_bonus * 5, spaces, sp_pot, rec, -g, tails, -kp, -fd, cleared)


def plan_eligibility_score(state: SpiderState, plan: "DealAnalysis", round_index: int) -> int:
    """Bonus for current state progress on suits that are 'eligible' (have enough cards
    available) for completion around the current or near-future round per the global
    pre-computed clearance plan.

    This captures the human 'reverse-engineering' of which suits can/should be targeted
    early vs. must wait for later stock. Early-eligible suits (per plan.eligible_suits_by_round
    and priority_clearance_order) get their current same-suit tails heavily rewarded,
    biasing the beam to build them before dealing (and to expose their buried cards).
    """
    if plan is None or not plan.eligible_suits_by_round or round_index >= len(plan.eligible_suits_by_round):
        return 0
    eligible = plan.eligible_suits_by_round[round_index] or set()
    if not eligible:
        eligible = set(plan.priority_clearance_order[:2]) if plan.priority_clearance_order else set("shdc")

    score = 0
    for col in state.columns:
        if not col.face_up:
            continue
        tail_len = same_suit_tail_len(col)
        if tail_len > 1 and col.face_up[-1].suit in eligible:
            # Reward longer runs on currently eligible/priority suits (the ones humans would
            # prioritize for early clearance to free spaces for the plan).
            score += (tail_len - 1) * 3
    # Small bonus for any exposed top of priority early suits (even single cards help future builds).
    priority = set(plan.priority_clearance_order[:2]) if plan.priority_clearance_order else set()
    for col in state.columns:
        top = col.top()
        if top and top.suit in (eligible | priority):
            score += 1
    return score


def card_exposure_value(card: "Card", plan: "DealAnalysis", current_round: int = 0) -> int:
    """Static strategic value of exposing/revealing this particular card (used in move
    ordering bonus for reveals of high-plan-value buried cards).

    High if the card's suit is early-eligible per the plan (humans would dig specifically
    to get these cards into play for the suits they can clear soon).
    """
    if plan is None or not plan.eligible_suits_by_round:
        return 1
    try:
        elig_rounds = [r for r, sset in enumerate(plan.eligible_suits_by_round) if card.suit in sset]
        if not elig_rounds:
            return 0
        first_eligible = min(elig_rounds)
        if first_eligible <= current_round + 1:
            return 5  # high value for soon/now eligible suit
        if first_eligible <= current_round + 2:
            return 2
        return 1
    except Exception:
        return 1


def count_valuable_pre_deal_moves(state: SpiderState) -> int:
    """Count currently legal moves that represent 'high value' work that should
    typically be completed before dealing the next known stock round.

    High-value categories (per strategy_insights.md and user feedback):
    - Same-suit attachments (permanent progress toward K->A foundations; less likely
      to need undoing than off-suit parking).
    - Any move to an empty column (creates space, which is "gold"; when the source
      face-up run is the entire column it is a 0-cost MW move under the rules, allowing
      free relocation of long runs or kings).
    - "Enabling park" moves: temporary off-suit (non-same, non-to-empty) placements that,
      when performed, immediately increase the number of same-suit or 0-cost moves
      available (the "X factor" quantified by the human solution analyzer on
      canonical.moves: many parks produce +30..+41 delta_valuable by unlocking the
      cascades and gold 0-cost to-empties/spaces). These get counted as setup work
      so we don't deal while unresolved unlocking opportunities remain.

    A low value here, combined with decent reception_fitness for the upcoming deal,
    is a strong signal that it is a good moment to deal: the valuable same-suit / free
    space / setup work has been done and we avoid the rookie mistake of exhausting low-value
    off-suit shuffles before injecting the next 10 cards.

    The count is cheap (reuses enumerate_moves which already enforces descending runs).
    Same-suit to empty is counted twice (both categories) — intentionally high value.
    Enabling parks are counted once each (if they unlock net new valuable work).
    """
    if state is None:
        return 0
    valuable = 0
    for src, dst, k in state.enumerate_moves():
        run = state.columns[src].face_up[-k:]
        dst_col = state.columns[dst]
        top = dst_col.top()
        if dst_col.is_empty():
            valuable += 1
        if top is not None and top.suit == run[0].suit:
            valuable += 1
    # Count enabling parks: current legal off-suit moves that unlock additional
    # valuable (same-suit or to-empty) work. This directly scores the future value
    # of the temporary parks the human uses.
    base = valuable
    for src, dst, k in state.enumerate_moves():
        run = state.columns[src].face_up[-k:]
        dst_col = state.columns[dst]
        top = dst_col.top()
        if dst_col.is_empty():
            continue
        if top is not None and top.suit == run[0].suit:
            continue
        # only revealing parks for perf (most unlocks in analyzer came from reveals;
        # non-revealing parks rarely unlock net new valuable in practice)
        if not (len(state.columns[src].face_up) == k and state.columns[src].face_down):
            continue
        # This is a revealing park (off-suit, non-empty dest)
        try:
            st = state.clone()
            st.move(src, dst, k)
            new_base = 0
            for s2, d2, k2 in st.enumerate_moves():
                r2 = st.columns[s2].face_up[-k2:]
                dc2 = st.columns[d2]
                t2 = dc2.top()
                if dc2.is_empty():
                    new_base += 1
                if t2 is not None and t2.suit == r2[0].suit:
                    new_base += 1
            if new_base > base:
                valuable += 1
        except Exception:
            pass
    # Space work left: direct measure of visible runs sitting on columns that still have face-down cards.
    # These are the columns that can yield new spaces ("gold") once their current face-up is moved off
    # (via parks, builds, cascades). This is the precise "setup work" the human does before dealing.
    # Parks that unlock moves reducing fu on these specific columns drop this number sharply.
    # Scaled to be dominant in pending until the visible blockers on fd-cols are cleared.
    space_work_left = sum(len(c.face_up) for c in state.columns if c.face_down)
    valuable += space_work_left * 3.5  # v27: keep dominant; the new best_deal_key sw_term + final space_gate are the primary levers now (human chooses at pre_valuable~23 incl this term)
    return valuable


def evaluate_post_deal(state: SpiderState, next_ten: List[Card], plan: "DealAnalysis" = None, round_index: int = 0) -> Tuple:
    """Simulate dealing the known next 10 cards (in MW left-to-right order) onto
    the current tableau and return a rich quality score for the *resulting* state.

    This is the direct implementation of the user's request:
    "score the state of the tableau and assess what the score would be if a stock
    deal was taken at that point."

    Because the solver has full stock visibility (unlike a human), we can cheaply
    clone + actually land the exact cards, run the auto check_seq (which may create
    new same-suit runs or clear foundations immediately), then score the post-deal
    tableau.

    The returned tuple is designed to be used as a "higher is better" key when
    choosing which pre-deal state in the beam is the best point at which to stop
    shaping and actually take the deal.

    Components (first elements have higher priority in comparisons):
    - foundations made by this deal itself (huge value if the deal completes runs)
    - post spaces (still gold after the injection)
    - post same-suit tails
    - low king pressure after
    - low remaining face-down after
    - post_plan bonus (advance on global clearance plan for eligible suits)
    - post_sp_pot (space creation potential after the landing — helps choose states good for future space creation)
    - (the pre g to reach this state is combined by the caller)

    The simulation exactly mirrors engine.SpiderState.deal() landing logic but
    without touching the real stock.
    """
    if not next_ten or len(next_ten) != 10:
        # No deal or wrong size — fall back to a neutral/poor score based on pre state
        spaces = sum(1 for c in state.columns if c.is_empty())
        tails = sum(same_suit_tail_len(c) for c in state.columns)
        kp = king_pressure(state)
        fd = sum(len(c.face_down) for c in state.columns)
        cleared = len(state.foundations)
        post_plan = plan_eligibility_score(state, plan, round_index) if plan is not None else 0
        post_sp_pot = space_creation_potential(state)
        return (0, spaces, tails, -kp, -fd, cleared, post_plan, post_sp_pot)  # 0 foundations gained

    st = state.clone()
    foundations_before = len(st.foundations)

    for c in range(10):
        card = next_ten[c]
        st.columns[c].face_up.append(card)
        st.check_seq(c)

    foundations_made = len(st.foundations) - foundations_before

    post_spaces = sum(1 for col in st.columns if col.is_empty())
    post_tails = sum(same_suit_tail_len(col) for col in st.columns)
    post_kp = king_pressure(st)
    post_fd = sum(len(col.face_down) for col in st.columns)
    post_cleared = len(st.foundations)
    post_plan = plan_eligibility_score(st, plan, round_index) if plan is not None else 0
    post_sp_pot = space_creation_potential(st)

    # Order chosen so that "deal caused good things" (clears, spaces, tails) win.
    # foundations_made is first because a deal that completes a foundation is
    # exceptionally valuable. Include post_plan so landing cards that advance the
    # global clearance plan (eligible suits) is rewarded.
    # Added post_sp_pot at end to let the deal choice key prefer states whose post after landing has strong space creation potential (helps the beam choose pre-deal states that set up future spaces even if immediate post_spaces=0).
    return (foundations_made, post_spaces, post_tails, -post_kp, -post_fd, post_cleared, post_plan, post_sp_pot)


def _card_label(c: Card) -> str:
    return str(c)


def evaluate_first_foundation_readiness(
    state: SpiderState,
    analysis: DealAnalysis,
    deals_used: int,
) -> Dict:
    """Evaluate first-foundation gates with minimal post-completion handling."""
    from spider.planner.dependency import DynamicDependencyAnalyser

    foundations = len(state.foundations)
    if foundations > 0:
        return {
            "first_foundation_stage": "complete",
            "not_applicable": True,
            "pass": True,
            "reason": "first_foundation_already_complete",
            "foundations": foundations,
            "immediate_pass": True,
            "immediate_reason": "first_foundation_already_complete",
            "stock_assisted_pass": None,
            "stock_assisted_reason": "first_foundation_already_complete",
            "best_suit": None,
            "gates": {},
            "stock_assisted": None,
            "completing_merge": False,
            "merge_details": None,
        }

    analyser = DynamicDependencyAnalyser(analysis)
    suits = "schd"
    gates = {s: analyser.compute_executable_foundation_gate(state, s) for s in suits}

    def _score(g: Dict) -> int:
        return (
            (100 if g["passes_gate"] else 0)
            + g["main_chain"] * 2
            + (5 if g["actual_top_blocker_safe_first"] else 0)
            - g["connector_grounded_debt"] * 3
            - g.get("exposure_depth", 0)
        )

    best_suit = max(suits, key=lambda s: _score(gates[s]))
    any_imm = any(g["passes_gate"] for g in gates.values())
    imm_reason = gates[best_suit]["gate_reason"] if any_imm else gates[best_suit]["gate_reason"]

    sag = stock_assisted_executable_gate(state, analysis, round_index=deals_used, lookahead=1)

    merge_any = detect_foundation_completing_merge(state)
    if not merge_any["found"]:
        for s in suits:
            m = detect_foundation_completing_merge(state, s)
            if m["found"]:
                merge_any = m
                break

    merge_from_gate = gates[best_suit].get("merge_details")
    if merge_from_gate and merge_from_gate.get("found"):
        merge_any = merge_from_gate

    return {
        "first_foundation_stage": "pending",
        "not_applicable": False,
        "pass": any_imm or sag["pass"],
        "reason": imm_reason if any_imm else sag["reason"],
        "foundations": 0,
        "immediate_pass": any_imm,
        "immediate_reason": imm_reason,
        "stock_assisted_pass": sag["pass"],
        "stock_assisted_reason": sag["reason"],
        "best_suit": best_suit if any_imm else sag.get("best_suit", best_suit),
        "gates": gates,
        "stock_assisted": sag,
        "completing_merge": bool(merge_any.get("found")),
        "merge_details": merge_any if merge_any.get("found") else None,
    }


def classify_anchor_verdict(
    sw: int,
    spaces: int,
    eval_result: Dict,
) -> str:
    """Map improved-gate evaluation to a diagnostic verdict label."""
    if eval_result.get("not_applicable"):
        return "first foundation already complete"
    if eval_result.get("immediate_pass"):
        return "immediately executable"
    sag = eval_result.get("stock_assisted") or {}
    if sag.get("pass"):
        if sag.get("near_pass"):
            return "stock-assisted near-pass"
        return "stock-assisted executable"
    g = eval_result.get("gates", {}).get(eval_result.get("best_suit", "s"), {})
    if g.get("main_chain", 0) >= 3 and (
        g.get("actual_top_blocker_safe_first")
        or g.get("exposure_depth", 99) <= 2
        or spaces > 0
    ):
        return "promising but still needs prep"
    if sw <= 15 and not eval_result.get("pass"):
        return "low-sw but under-resourced"
    return "reject"


def old_classify_verdict(sw: int, spaces: int, any_pass: bool, best_gate: Dict) -> str:
    """Replicate pre-merge gate verdict logic from prefix_anchor_audit."""
    g = best_gate
    if any_pass:
        return "executable first-foundation candidate"
    if g.get("main_chain", 0) >= 3 and (
        g.get("actual_top_blocker_safe_first")
        or g.get("exposure_depth", 99) <= 2
        or spaces > 0
    ):
        return "promising anchor, needs small prep"
    if sw <= 15 and not any_pass:
        return "low-sw but under-resourced"
    if spaces >= 2 and g.get("main_chain", 0) <= 2:
        return "high-space but low progress"
    return "reject"


def detect_foundation_completing_merge(
    state: SpiderState,
    suit: str | None = None,
) -> Dict:
    """Find a legal one-move merge that completes a K->A same-suit foundation.

    Uses engine move legality and ``check_seq`` foundation removal (not static-only).
    """
    empty: Dict = {
        "found": False,
        "suit": suit,
        "source_col": None,
        "dest_col": None,
        "move_count": 0,
        "source_run_high": None,
        "source_run_low": None,
        "dest_card": None,
        "completes_foundation": False,
        "legal": False,
        "reason": "no foundation-completing merge found",
        "validation": "engine",
    }
    suits = [suit] if suit else list("schd")
    candidates: List[Dict] = []

    for s in suits:
        for src in range(10):
            up = state.columns[src].face_up
            for k in range(1, len(up) + 1):
                run = up[-k:]
                if not state.is_desc_run(run):
                    continue
                for dst in range(10):
                    if src == dst:
                        continue
                    if not state.can_move(src, dst, k):
                        continue
                    dest_top = state.columns[dst].top()
                    sim = state.clone()
                    f_before = len(sim.foundations)
                    sim.move(src, dst, k)
                    if len(sim.foundations) <= f_before:
                        continue
                    fund = sim.foundations[-1]
                    if len(fund) != 13 or fund[0].suit != s or fund[0].rank != 13:
                        continue
                    candidates.append(
                        {
                            "found": True,
                            "suit": s,
                            "source_col": src + 1,
                            "dest_col": dst + 1,
                            "move_count": k,
                            "source_run_high": _card_label(run[0]),
                            "source_run_low": _card_label(run[-1]),
                            "dest_card": _card_label(dest_top) if dest_top else None,
                            "completes_foundation": True,
                            "legal": True,
                            "reason": "engine-validated foundation-completing merge",
                            "validation": "engine",
                        }
                    )

    if not candidates:
        return empty

    # Prefer merges onto an exposed K (canonical pattern), then longer runs.
    def _rank(c: Dict) -> Tuple[int, int]:
        dest_k = 1 if c["dest_card"] and c["dest_card"][0] == "K" else 0
        return (dest_k, c["move_count"])

    best = max(candidates, key=_rank)
    return best


def _pattern_label(high: int, low: int) -> str:
    hi = {13: "K", 12: "Q", 11: "J", 10: "10"}.get(high, str(high))
    lo = "A" if low == 1 else str(low)
    return f"{hi}->{lo}"


def _same_suit_desc_fragments_in_column(
    state: SpiderState, col_idx: int, suit: str
) -> List[Dict]:
    """All maximal contiguous same-suit descending fragments in a column's face_up."""
    up = state.columns[col_idx].face_up
    n = len(up)
    found: List[Dict] = []
    seen: set = set()
    for start in range(n):
        for end in range(start, n):
            sub = up[start : end + 1]
            if not all(c.suit == suit for c in sub):
                continue
            if not state.is_desc_run(sub):
                continue
            key = (start, end)
            if key in seen:
                continue
            # Maximal extension within same-suit descending bounds
            while start > 0 and up[start - 1].suit == suit and state.is_desc_run(up[start - 1 : end + 1]):
                start -= 1
            sub = up[start : end + 1]
            if not state.is_desc_run(sub):
                continue
            seen.add((start, end))
            high, low = sub[0].rank, sub[-1].rank
            length = len(sub)
            suffix_aligned = end == n - 1
            k = n - start
            movable = suffix_aligned and state.can_move(col_idx, col_idx, k) is False
            # Movable as unit: suffix of face_up is this fragment and is a legal descending run
            if suffix_aligned:
                run = up[-k:]
                movable = (
                    len(run) == length
                    and state.is_desc_run(run)
                    and all(c.suit == suit for c in run)
                )
            else:
                movable = False
            dest_cols = []
            if movable:
                for dst in range(10):
                    if dst != col_idx and state.can_move(col_idx, dst, k):
                        dest_cols.append(dst + 1)
            found.append(
                {
                    "col": col_idx + 1,
                    "high": high,
                    "low": low,
                    "length": length,
                    "pattern": _pattern_label(high, low),
                    "movable": movable,
                    "move_count": k if movable else 0,
                    "dest_cols": dest_cols,
                    "high_card": _card_label(sub[0]),
                    "low_card": _card_label(sub[-1]),
                }
            )
    # Deduplicate: keep longest per (col, low)
    best_by_col: Dict[int, Dict] = {}
    for f in found:
        c = f["col"]
        if c not in best_by_col or f["length"] > best_by_col[c]["length"]:
            best_by_col[c] = f
    return sorted(found, key=lambda x: (-x["length"], -x["high"]))


def _rank_status_in_tableau(state: SpiderState, suit: str, rank: int) -> str:
    for col_idx, col in enumerate(state.columns):
        for i, c in enumerate(col.face_up):
            if c.suit == suit and c.rank == rank:
                if i == len(col.face_up) - 1:
                    return f"visible_top_col{col_idx + 1}"
                blockers = [str(x) for x in col.face_up[i + 1 :]]
                return f"blocked_col{col_idx + 1}_by_{blockers[0] if blockers else '?'}"
        for c in col.face_down:
            if c.suit == suit and c.rank == rank:
                return f"buried_col{col_idx + 1}"
    return "absent"


def _ranks_in_stock_wave(analysis: DealAnalysis, round_index: int, suit: str) -> List[int]:
    if round_index is None or round_index >= len(analysis.incoming_by_round):
        return []
    return [c.rank for c in analysis.incoming_by_round[round_index] if c.suit == suit]


def _missing_for_k_a_completion(high: int, low: int) -> List[int]:
    """Ranks needed beyond fragment to complete K->A (13..1)."""
    missing = []
    if low > 1:
        missing.append(1)
    if high < 13:
        missing.append(13)
    return missing


def _score_fragment_potential(
    frag: Dict,
    missing: List[int],
    missing_in_stock: List[int],
    k_status: str,
    a_status: str,
    exact_now: bool,
    exact_after: bool,
    damaged_after_deal: bool,
) -> Tuple[int, str]:
    score = 0
    reasons: List[str] = []
    length = frag["length"]
    low, high = frag["low"], frag["high"]

    if exact_now:
        return 1000, "exact completing merge now"
    if exact_after:
        return 900, "exact completing merge after next stock"

    score += length * 15
    reasons.append(f"len={length}")

    if low == 1:
        score += 40
        reasons.append("ends_at_A")
    if high == 12 and low == 1:
        score += 120
        reasons.append("Q_to_A")
    elif high == 11 and low == 1:
        score += 90
        reasons.append("J_to_A")
    elif high == 10 and low == 1:
        score += 70
        reasons.append("10_to_A")
    elif high == 12 and low == 2:
        score += 60
        reasons.append("Q_to_2_missing_A")
    elif high == 13 and low == 2:
        score += 50
        reasons.append("K_to_2_missing_A")

    if frag["movable"]:
        score += 35
        reasons.append("movable")
    else:
        score -= 20
        reasons.append("not_movable")

    if 13 in missing and 13 in missing_in_stock:
        score += 100
        reasons.append("K_in_next_stock")
    elif k_status.startswith("visible"):
        score += 60
        reasons.append("K_visible")
    elif k_status.startswith("blocked"):
        score += 15
        reasons.append("K_blocked")
    elif k_status.startswith("buried"):
        score += 5
        reasons.append("K_buried")

    if 1 in missing and 1 in missing_in_stock:
        score += 40
        reasons.append("A_in_next_stock")
    elif a_status.startswith("visible") or low == 1:
        score += 25
        reasons.append("A_available")

    if damaged_after_deal:
        score -= 80
        reasons.append("fragment_damaged_by_next_deal")

    if length >= 10 and low == 1 and (13 in missing_in_stock or k_status.startswith("visible")):
        score += 50
        reasons.append("long_A_fragment_plus_K_path")

    return score, "; ".join(reasons)


def _completed_foundation_suits(state: SpiderState) -> set:
    return {pile[0].suit for pile in state.foundations if pile}


def _foundation_completion_potential_for_suits(
    state: SpiderState,
    suits: List[str],
    analysis: DealAnalysis | None = None,
    round_index: int | None = None,
    lookahead: int = 1,
) -> Dict:
    """Core potential scorer for a specific suit list (shared by first/next wrappers)."""
    per_suit: Dict[str, Dict] = {}
    for s in suits:
        merge_now = detect_foundation_completing_merge(state, s)
        merge_after = {"found": False}
        damaged = False
        if analysis is not None and round_index is not None and len(state.stock) >= 10:
            sim = state.clone()
            for _ in range(lookahead):
                if len(sim.stock) < 10:
                    break
                sim.deal()
            merge_after = detect_foundation_completing_merge(sim, s)
            all_frags_pre = []
            for ci in range(10):
                all_frags_pre.extend(_same_suit_desc_fragments_in_column(state, ci, s))
            if all_frags_pre:
                best_f = max(all_frags_pre, key=lambda x: x["length"])
                col_idx = best_f["col"] - 1
                frags_post = _same_suit_desc_fragments_in_column(sim, col_idx, s)
                post_len = max((f["length"] for f in frags_post), default=0)
                if best_f["length"] >= 6 and post_len < best_f["length"]:
                    damaged = True

        all_frags: List[Dict] = []
        for ci in range(10):
            all_frags.extend(_same_suit_desc_fragments_in_column(state, ci, s))
        if not all_frags:
            per_suit[s] = {
                "score": 0,
                "best_fragment": None,
                "reason": "no_same_suit_fragment",
            }
            continue

        k_status = _rank_status_in_tableau(state, s, 13)
        a_status = _rank_status_in_tableau(state, s, 1)
        stock_ranks = _ranks_in_stock_wave(analysis, round_index, s) if analysis else []

        if merge_now["found"]:
            mf = merge_now
            per_suit[s] = {
                "score": 1000,
                "best_fragment": f"{mf['source_run_high']}->{mf['source_run_low']}",
                "fragment_col": mf["source_col"],
                "fragment_high": mf["source_run_high"],
                "fragment_low": mf["source_run_low"],
                "fragment_length": mf["move_count"],
                "movable": True,
                "missing_cards": [],
                "missing_cards_in_next_stock": [],
                "anchor_status": f"K:{k_status};A:{a_status}",
                "exact_merge_now": True,
                "exact_merge_after_stock": False,
                "merge_now_details": mf,
                "merge_after_details": None,
                "fragment_damaged_by_next_deal": damaged,
                "reason": "exact completing merge now",
                "all_fragments": all_frags,
            }
            continue
        if merge_after["found"]:
            mf = merge_after
            per_suit[s] = {
                "score": 900,
                "best_fragment": f"{mf['source_run_high']}->{mf['source_run_low']}",
                "fragment_col": mf["source_col"],
                "fragment_high": mf["source_run_high"],
                "fragment_low": mf["source_run_low"],
                "fragment_length": mf["move_count"],
                "movable": True,
                "missing_cards": ["13"] if mf.get("dest_card", "").startswith("K") else [],
                "missing_cards_in_next_stock": [
                    c for c in (_card_label(x) for x in analysis.incoming_by_round[round_index] if x.suit == s)  # type: ignore
                ] if analysis and round_index is not None else [],
                "anchor_status": f"K:{k_status};A:{a_status}",
                "exact_merge_now": False,
                "exact_merge_after_stock": True,
                "merge_now_details": None,
                "merge_after_details": mf,
                "fragment_damaged_by_next_deal": damaged,
                "reason": "exact completing merge after next stock",
                "all_fragments": all_frags,
            }
            continue

        best_entry = None
        best_score = -999
        for frag in all_frags:
            missing = _missing_for_k_a_completion(frag["high"], frag["low"])
            missing_in_stock = [r for r in missing if r in stock_ranks]
            sc, rsn = _score_fragment_potential(
                frag,
                missing,
                missing_in_stock,
                k_status,
                a_status,
                False,
                False,
                damaged,
            )
            if sc > best_score:
                best_score = sc
                best_entry = {
                    "score": sc,
                    "best_fragment": frag["pattern"],
                    "fragment_col": frag["col"],
                    "fragment_high": frag["high_card"],
                    "fragment_low": frag["low_card"],
                    "fragment_length": frag["length"],
                    "movable": frag["movable"],
                    "missing_cards": [str(r) for r in missing],
                    "missing_cards_in_next_stock": [
                        _card_label(Card(s, r)) for r in missing_in_stock
                    ],
                    "anchor_status": f"K:{k_status};A:{a_status}",
                    "exact_merge_now": False,
                    "exact_merge_after_stock": False,
                    "merge_now_details": None,
                    "merge_after_details": None,
                    "fragment_damaged_by_next_deal": damaged,
                    "reason": rsn,
                    "all_fragments": all_frags,
                }
        per_suit[s] = best_entry or {"score": 0, "reason": "no_scored_fragment"}

    if not per_suit:
        return {
            "score": 0,
            "best_suit": suits[0] if suits else None,
            "reason": "no_eligible_suits",
            "exact_merge_now": False,
            "exact_merge_after_stock": False,
            "per_suit": {},
        }

    best_suit = max(suits, key=lambda ss: per_suit.get(ss, {}).get("score", 0))
    result = dict(per_suit[best_suit])
    result["best_suit"] = best_suit
    result["per_suit"] = per_suit
    return result


def foundation_completion_potential(
    state: SpiderState,
    suit: str | None = None,
    analysis: DealAnalysis | None = None,
    round_index: int | None = None,
    lookahead: int = 1,
) -> Dict:
    """Diagnostic score for proximity to stock-assisted foundation-completing merge."""
    if len(state.foundations) > 0:
        return {
            "score": 0,
            "best_suit": suit,
            "reason": "foundation_already_complete",
            "exact_merge_now": False,
            "exact_merge_after_stock": False,
            "not_applicable": True,
        }
    suits = [suit] if suit else list("schd")
    return _foundation_completion_potential_for_suits(
        state, suits, analysis=analysis, round_index=round_index, lookahead=lookahead
    )


def next_foundation_completion_potential(
    state: SpiderState,
    suit: str | None = None,
    analysis: DealAnalysis | None = None,
    round_index: int | None = None,
    lookahead: int = 1,
) -> Dict:
    """Stage-aware potential for the next foundation when one or more are already cleared."""
    completed = _completed_foundation_suits(state)
    if suit:
        suits = [suit] if suit not in completed else []
    else:
        suits = [s for s in "schd" if s not in completed]
    if not suits:
        return {
            "score": 0,
            "best_suit": None,
            "reason": "all_foundations_complete",
            "exact_merge_now": False,
            "exact_merge_after_stock": False,
            "completed_foundations": len(state.foundations),
            "completed_suits": sorted(completed),
            "per_suit": {},
        }
    result = _foundation_completion_potential_for_suits(
        state, suits, analysis=analysis, round_index=round_index, lookahead=lookahead
    )
    result["completed_foundations"] = len(state.foundations)
    result["completed_suits"] = sorted(completed)
    return result


def stock_assisted_executable_gate(
    state: SpiderState,
    analysis: DealAnalysis,
    round_index: int,
    lookahead: int = 1,
) -> Dict:
    """Stock-assisted ExecutableFoundationGate: immediate gate plus post-known-deal preview.

    Evaluates per-suit ExecutableFoundationGate now, simulates the next ``lookahead``
    known stock wave(s) via ``SpiderState.deal()``, then re-evaluates.  Reports whether
    any suit becomes executable or materially closer because of the known stock.
    """
    from spider.planner.dependency import DynamicDependencyAnalyser

    analyser = DynamicDependencyAnalyser(analysis)
    suits = "schd"

    def _all_gates(st: SpiderState) -> Dict[str, Dict]:
        return {s: analyser.compute_executable_foundation_gate(st, s) for s in suits}

    def _gate_score(g: Dict) -> int:
        return (
            (100 if g["passes_gate"] else 0)
            + g["main_chain"] * 2
            + (5 if g["actual_top_blocker_safe_first"] else 0)
            - g["connector_grounded_debt"] * 3
            - g.get("exposure_depth", 0)
        )

    before_gate = _all_gates(state)
    before_merges = {s: detect_foundation_completing_merge(state, s) for s in suits}
    before_best_suit = max(suits, key=lambda s: _gate_score(before_gate[s]))
    before_best = before_gate[before_best_suit]

    work = state.clone()
    wave_cards: List[Card] = []
    deal_ok = True
    failure_reason = None
    for _ in range(lookahead):
        if len(work.stock) < 10:
            deal_ok = False
            failure_reason = "insufficient stock for simulated deal"
            break
        ri = round_index + _
        if ri < len(analysis.incoming_by_round):
            wave_cards.extend(analysis.incoming_by_round[ri])
        try:
            work.deal()
        except Exception as exc:
            deal_ok = False
            failure_reason = f"deal simulation failed: {exc}"
            break

    after_gate = _all_gates(work) if deal_ok else before_gate
    after_merges = (
        {s: detect_foundation_completing_merge(work, s) for s in suits}
        if deal_ok
        else before_merges
    )
    after_best_suit = max(suits, key=lambda s: _gate_score(after_gate[s]))
    after_best = after_gate[after_best_suit]

    stock_merge_suits = [
        s
        for s in suits
        if after_merges[s]["found"] and not before_merges[s]["found"]
    ]
    merge_details = after_merges[stock_merge_suits[0]] if stock_merge_suits else None

    improved_suits: List[str] = []
    key_stock_cards: List[str] = []
    for s in suits:
        bg, ag = before_gate[s], after_gate[s]
        material = (
            (not bg["passes_gate"] and ag["passes_gate"])
            or ag["main_chain"] > bg["main_chain"]
            or (
                ag.get("foundation_distance") is not None
                and bg.get("foundation_distance") is not None
                and ag["foundation_distance"] < bg["foundation_distance"]
            )
            or ag["connector_grounded_debt"] < bg["connector_grounded_debt"]
            or (
                bg["target_status"] in ("buried", "future_stock", "unavailable")
                and ag["target_status"] in ("visible_free", "visible_blocked")
            )
            or (not bg["actual_top_blocker_safe_first"] and ag["actual_top_blocker_safe_first"])
        )
        if material:
            improved_suits.append(s)
            if wave_cards and deal_ok:
                for c in wave_cards:
                    if c.suit == s and str(c) not in key_stock_cards:
                        key_stock_cards.append(str(c))

    any_before_pass = any(g["passes_gate"] for g in before_gate.values())
    any_after_pass = any(g["passes_gate"] for g in after_gate.values())
    best_improved = _gate_score(after_best) > _gate_score(before_best)
    near_pass = (
        not any_before_pass
        and not any_after_pass
        and not stock_merge_suits
        and (best_improved or len(improved_suits) > 0)
        and after_best["main_chain"] >= 3
        and after_best["connector_grounded_debt"] <= 2
    )

    if stock_merge_suits:
        passes = True
        best_suit_for_merge = stock_merge_suits[0]
        merge_details = after_merges[best_suit_for_merge]
        reason = "stock_assisted_foundation_completing_merge"
        for c in wave_cards:
            cs = str(c)
            if c.suit == best_suit_for_merge and c.rank in (13, 1) and cs not in key_stock_cards:
                key_stock_cards.append(cs)
    else:
        passes = any_after_pass and (not any_before_pass or best_improved)

    if stock_merge_suits:
        pass  # reason already set
    elif any_after_pass and not any_before_pass:
        reason = f"stock wave enables executable route for {after_best_suit}"
    elif any_after_pass and best_improved:
        reason = f"stock wave strengthens executable route ({before_best_suit}->{after_best_suit})"
    elif near_pass:
        reason = f"stock wave materially improves near-pass suits: {','.join(improved_suits) or after_best_suit}"
    elif improved_suits:
        reason = f"stock wave improves {','.join(improved_suits)} but no suit passes gate yet"
    else:
        reason = "no material improvement from known stock wave"
        if not deal_ok:
            failure_reason = failure_reason or "deal simulation did not complete"

    if stock_merge_suits:
        reported_best_suit = stock_merge_suits[0]
    elif passes or near_pass or improved_suits:
        reported_best_suit = after_best_suit
    else:
        reported_best_suit = before_best_suit

    return {
        "pass": passes,
        "near_pass": near_pass,
        "best_suit": reported_best_suit,
        "before_gate": before_gate,
        "after_gate": after_gate,
        "before_merges": before_merges,
        "after_merges": after_merges,
        "stock_merge_suits": stock_merge_suits,
        "merge_details": merge_details,
        "before_best_suit": before_best_suit,
        "after_best_suit": after_best_suit,
        "improved_suits": improved_suits,
        "key_stock_cards": key_stock_cards,
        "wave_cards": [str(c) for c in wave_cards],
        "round_index": round_index,
        "lookahead": lookahead,
        "deal_simulated": deal_ok,
        "reason": reason,
        "failure_reason": failure_reason,
    }
