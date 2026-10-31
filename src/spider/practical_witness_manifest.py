"""Frozen inputs for the deal 4925153 witness-play trial.

Offline preparation only. The canonical route is replayed to authenticate
the true opening and the first three stock-deal boundaries, then the
reference suffix is discarded. Policy code receives a state and the generic
limits below. It does not receive future reference actions.

The budgets and the progress rule in this module are the predeclared
specification. They are fixed before either play arm runs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Optional, Sequence, Tuple

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import CANONICAL_MOBILITYWARE_MOVES
from spider.packed_state import pack_state
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    face_down_count,
    is_deal,
    step_cost,
)
from spider.solution_archive import validate_solution

DEAL_ID = "4925153"
DEAL_RELATIVE = "deals/4925153.txt"
CANONICAL_RELATIVE = "solutions/4925153_canonical.moves"
EXPECTED_CANONICAL_SHA256 = (
    "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
)
EXPECTED_DEAL_SHA256 = (
    "C0B70979B3E6B90E266691DF956026629C890F49C12ED519801D6779434734DF"
)
ROOT_IDS = ("opening", "after-deal-1", "after-deal-2", "after-deal-3")

PREPARATION_BUDGET_S = 30.0
PROBE_MAX_UNIQUE = 20
PROBE_TIME_LIMIT_S = 2.0
PROBE_RSS_ABORT_MB = 512.0
PROBE_COST_CEILING = 4
PROBE_MAX_DEPTH = None
PROBE_HARVEST_SLACK = None
PROBE_STOP_ON_FIRST_TERMINAL = False
PROBE_SLOTS = 8
REVEAL_GOAL = 2
WORKERS = 1
EPISODE_WALL_S = 60.0
EPISODE_ADDITIONAL_PAID = 12
EPISODE_PRIMITIVE_ACTIONS = 64
EPISODE_PLANNING_DECISIONS = 8
EPISODE_PROBE_IDENTITIES = 1280
EPISODE_RSS_MB = 512.0
INDEPENDENT_COLD_COMPLETE = False

REPO_ROOT = Path(__file__).resolve().parents[2]


class ProvenanceBlocker(RuntimeError):
    """A root could not be authenticated. Do not substitute another state."""


@dataclass(frozen=True)
class FrozenRoot:
    """One authenticated source. ``prefix_actions`` ends at this root.

    The prefix is an audit trail from the opening. It is not a plan, and it
    is not a search frontier. Warm roots are imported verified prefixes.
    """

    root_id: str
    deal_ordinal: int
    prefix_actions: Tuple
    corrected_cost: int
    pack_hex: str
    stock: int
    foundations: int
    hidden: int
    duplicate_of: Optional[str]
    counts_as_evidence: bool

    @property
    def imported_prefix(self) -> bool:
        return self.deal_ordinal > 0


@dataclass(frozen=True)
class PlayManifest:
    """Authenticated roots plus the hashes that justify them."""

    roots: Tuple[FrozenRoot, ...]
    deal_sha256: str
    canonical_sha256: str
    canonical_mw: int
    canonical_foundations: int
    canonical_stock_remaining: int
    canonical_tableau_empty: bool
    canonical_action_count: int
    retained_action_count: int
    suffix_discarded: bool
    preparation_s: float
    preparation_budget_s: float


def policy_specification() -> dict:
    """Limits and the progress rule. Plain values only, safe to serialise."""

    return {
        "deal_id": DEAL_ID,
        "roots": list(ROOT_IDS),
        "preparation_budget_s": PREPARATION_BUDGET_S,
        "identity": "pack_state",
        "actions": "all_legal_actions",
        "lower_bound": None,
        "workers": WORKERS,
        "reveal_goal": REVEAL_GOAL,
        "reveal_phase_complete_is_solved": False,
        "witness_upper_bound_is_admissible": False,
        "independent_cold_complete": INDEPENDENT_COLD_COMPLETE,
        "probe": {
            "max_unique": PROBE_MAX_UNIQUE,
            "time_limit_s": PROBE_TIME_LIMIT_S,
            "rss_abort_mb": PROBE_RSS_ABORT_MB,
            "cost_ceiling": PROBE_COST_CEILING,
            "cost_ceiling_scope": "total corrected moves from the decision source",
            "local_g": "replayed candidate prefix cost from the decision state",
            "max_depth": PROBE_MAX_DEPTH,
            "harvest_slack": PROBE_HARVEST_SLACK,
            "stop_on_first_terminal": PROBE_STOP_ON_FIRST_TERMINAL,
            "slots": PROBE_SLOTS,
            "deal_slot": (
                "reserve the eighth slot when Deal is legal and outside the first eight"
            ),
            "unfinished_witness": (
                "executable as ordering evidence, not a minimum certificate"
            ),
        },
        "episode": {
            "wall_s": EPISODE_WALL_S,
            "additional_paid": EPISODE_ADDITIONAL_PAID,
            "primitive_actions": EPISODE_PRIMITIVE_ACTIONS,
            "planning_decisions": EPISODE_PLANNING_DECISIONS,
            "probe_identities": EPISODE_PROBE_IDENTITIES,
            "rss_mb": EPISODE_RSS_MB,
            "workers": WORKERS,
            "alternation": (
                "even root index baseline then witness; "
                "odd root index witness then baseline"
            ),
            "one_run_per_mode": True,
        },
        "metric": {
            "dominance": (
                "at least as many foundations AND no more hidden cards, "
                "with one strict improvement"
            ),
            "complete_solution": (
                "a full independently replayed eight-foundation solution "
                "outranks an incomplete position"
            ),
            "stock_alone": "fewer stock cards alone is not a win",
            "mixed": "mixed foundation and reveal changes are tradeoffs",
            "trajectory": (
                "equal reveal-count milestone costs are observed trajectory "
                "costs, not optimal costs"
            ),
            "signal": (
                "at least two nonduplicate roots favour witness mode; "
                "no paired root is dominated by baseline; "
                "legality, cost, and provenance checks pass"
            ),
            "signal_scope": (
                "within-deal practical-play signal only; no generalisation, "
                "finishability, or complete-solve claim"
            ),
            "no_clear_benefit": (
                "insufficient wins, ties, tradeoffs, capped runs, or baseline regressions"
            ),
            "correctness_blocker": (
                "illegal execution, source or witness mismatch, broken accounting, "
                "or a false provenance or certainty claim"
            ),
        },
    }


def mode_order(root_index: int) -> Tuple[str, str]:
    """Which arm runs first. Fixed by manifest order, not by outcomes."""

    if int(root_index) % 2 == 0:
        return ("baseline", "witness")
    return ("witness", "baseline")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _normalize(action) -> tuple:
    if is_deal(action):
        return ("deal",)
    return (int(action[0]), int(action[1]), int(action[2]))


def _opening() -> SpiderState:
    return SpiderState.from_cards(load_deal(REPO_ROOT / DEAL_RELATIVE))


def _card_count(state: SpiderState) -> int:
    tableau = sum(len(column.face_down) + len(column.face_up) for column in state.columns)
    foundations = sum(len(seq) for seq in state.foundations)
    return tableau + len(state.stock) + foundations


def _guard(started: float, budget_s: float) -> None:
    if perf_counter() - started > budget_s:
        raise ProvenanceBlocker(
            "preparation budget exceeded; this is a provenance blocker, not an unsolvable deal"
        )


def _step(state: SpiderState, action) -> int:
    normalized = _normalize(action)
    if normalized not in all_legal_actions(state):
        raise ProvenanceBlocker(f"illegal authenticated action {normalized!r}")
    priced = int(step_cost(state, normalized))
    applied = int(apply_action(state, normalized))
    if applied != priced:
        raise ProvenanceBlocker(
            f"engine cost {applied} disagrees with step cost {priced} for {normalized!r}"
        )
    return priced


def _facts(state: SpiderState, prefix: Sequence, cost: int, ordinal: int) -> dict:
    if _card_count(state) != 104:
        raise ProvenanceBlocker("root does not conserve the two-deck inventory")
    return {
        "deal_ordinal": ordinal,
        "prefix_actions": tuple(_normalize(action) for action in prefix),
        "corrected_cost": int(cost),
        "pack_hex": pack_state(state).hex(),
        "stock": len(state.stock),
        "foundations": len(state.foundations),
        "hidden": face_down_count(state),
    }


def materialize_root(root: FrozenRoot) -> SpiderState:
    """Replay the stored prefix from the opening and require the saved pack."""

    state = _opening()
    paid = 0
    for action in root.prefix_actions:
        paid += _step(state, action)
    if paid != int(root.corrected_cost):
        raise ProvenanceBlocker(
            f"{root.root_id} replay cost {paid} != recorded {root.corrected_cost}"
        )
    if pack_state(state).hex() != root.pack_hex:
        raise ProvenanceBlocker(f"{root.root_id} replay pack does not match the manifest")
    if (
        len(state.stock) != root.stock
        or len(state.foundations) != root.foundations
        or face_down_count(state) != root.hidden
    ):
        raise ProvenanceBlocker(f"{root.root_id} inventory does not match the manifest")
    if _card_count(state) != 104:
        raise ProvenanceBlocker(f"{root.root_id} dropped or invented a card")
    return state


def prepare_manifest(*, budget_s: float = PREPARATION_BUDGET_S) -> PlayManifest:
    """Authenticate four roots. Raise rather than return a partial manifest."""

    started = perf_counter()
    _guard(started, budget_s)
    deal_path = REPO_ROOT / DEAL_RELATIVE
    canonical_path = REPO_ROOT / CANONICAL_RELATIVE
    deal_sha = _sha256(deal_path)
    canonical_sha = _sha256(canonical_path)
    _guard(started, budget_s)
    if deal_sha != EXPECTED_DEAL_SHA256:
        raise ProvenanceBlocker("deal file hash does not match the frozen reference")
    if canonical_sha != EXPECTED_CANONICAL_SHA256:
        raise ProvenanceBlocker("canonical route hash does not match the frozen reference")

    verified = validate_solution(
        DEAL_ID,
        canonical_path,
        claimed_mobilityware_moves=CANONICAL_MOBILITYWARE_MOVES,
    )
    _guard(started, budget_s)
    if not verified.valid or not verified.solved:
        raise ProvenanceBlocker(
            f"canonical route failed the full-game verifier: {verified.failure_reason}"
        )
    if (
        int(verified.mobilityware_moves) != CANONICAL_MOBILITYWARE_MOVES
        or int(verified.foundations) != 8
        or int(verified.stock_remaining) != 0
    ):
        raise ProvenanceBlocker("canonical accounting is not 172 moves, 8 foundations, empty stock")

    actions = tuple(_normalize(action) for action in verified.actions)
    state = _opening()
    paid = 0
    prefix: list = []
    snapshots = [_facts(state, (), 0, 0)]
    deals = 0
    for action in actions:
        _guard(started, budget_s)
        paid += _step(state, action)
        prefix.append(action)
        if action == ("deal",):
            deals += 1
            if deals <= 3:
                snapshots.append(_facts(state, prefix, paid, deals))
    if (
        paid != CANONICAL_MOBILITYWARE_MOVES
        or not state.is_solved()
        or len(state.foundations) != 8
        or state.stock
        or not all(column.is_empty() for column in state.columns)
    ):
        raise ProvenanceBlocker("independent full replay did not finish with an empty tableau")
    if deals < 3 or len(snapshots) != 4:
        raise ProvenanceBlocker("the canonical replay does not contain three stock deals")
    full_count = len(actions)
    retained = max(len(item["prefix_actions"]) for item in snapshots)
    # The suffix past the third deal authenticated the roots and is not retained.
    del actions, prefix, state

    seen = {}
    roots = []
    for root_id, facts in zip(ROOT_IDS, snapshots):
        _guard(started, budget_s)
        earlier = seen.get(facts["pack_hex"])
        root = FrozenRoot(
            root_id=root_id,
            deal_ordinal=facts["deal_ordinal"],
            prefix_actions=facts["prefix_actions"],
            corrected_cost=facts["corrected_cost"],
            pack_hex=facts["pack_hex"],
            stock=facts["stock"],
            foundations=facts["foundations"],
            hidden=facts["hidden"],
            duplicate_of=earlier,
            counts_as_evidence=earlier is None,
        )
        materialize_root(root)
        if earlier is None:
            seen[root.pack_hex] = root.root_id
        roots.append(root)
        if root.deal_ordinal > 0 and root.prefix_actions[-1] != ("deal",):
            raise ProvenanceBlocker(f"{root.root_id} does not end on its stock deal")
        if root.deal_ordinal == 0 and root.prefix_actions:
            raise ProvenanceBlocker("the opening root must not carry a played prefix")

    elapsed = perf_counter() - started
    if elapsed > budget_s:
        raise ProvenanceBlocker(
            "preparation budget exceeded; this is a provenance blocker, not an unsolvable deal"
        )
    return PlayManifest(
        roots=tuple(roots),
        deal_sha256=deal_sha,
        canonical_sha256=canonical_sha,
        canonical_mw=CANONICAL_MOBILITYWARE_MOVES,
        canonical_foundations=8,
        canonical_stock_remaining=0,
        canonical_tableau_empty=True,
        canonical_action_count=full_count,
        retained_action_count=retained,
        suffix_discarded=retained < full_count,
        preparation_s=elapsed,
        preparation_budget_s=float(budget_s),
    )
