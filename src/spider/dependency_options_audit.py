"""Offline replay of committed routes and published fifth-deal lines.

Macro discovery and the solver are not called. A portfolio file is not
read and is not regenerated. ``f`` here is ``g + admissible_remaining``.
The dependency penalty is not added.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from spider.cards import rank_str
from spider.deal import load_deal
from spider.dependency_options import (
    AncestorClaim,
    OptionContractError,
    build_option,
    diversity_signature,
    outcome_signature,
    rebuild_obligations,
    select_dependency_portfolio,
)
from spider.engine import SpiderState
from spider.human_strategy.evaluation import admissible_remaining, same_suit_bonds
from spider.metrics import parse_moves_file
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import (
    apply_action,
    empty_column_indices,
    face_down_count,
    foundation_suits,
    is_deal,
    tableau_actions,
)

CHECKPOINT_PREP = 140
POST_SD5 = 152
FIFTH_DEAL_INDEX = 151

# Published in docs/reveal_aware_heart_macros_v0_139.md. These are replayed.
# They are not rediscovered.
_PUBLISHED_MACROS = (
    (0, "move 2 5 1, move 8 1 3, move 10 8 2, move 1 10 3, move 3 1 2, move 9 2 1", 142, 24, 166, 3),
    (1, "move 2 1 1, move 9 2 1, move 1 5 1, move 3 1 2, move 3 10 2", 143, 24, 167, 3),
    (2, "move 2 1 1, move 10 5 2, move 1 10 1, move 3 1 2, move 9 2 1, move 7 10 1, move 7 8 2", 144, 24, 168, 3),
    (3, "move 2 1 1, move 9 2 1, move 1 5 1, move 3 1 2, move 3 4 5, move 8 4 2", 144, 25, 169, 3),
    (4, "move 2 1 1, move 9 2 1, move 1 5 1, move 3 1 2, move 3 10 2, move 9 4 7", 144, 25, 169, 3),
    (5, "move 2 1 1, move 9 2 1, move 1 5 1, move 3 1 2, move 9 4 7", 143, 25, 168, 3),
    (6, "move 2 1 1, move 8 5 3, move 1 8 1, move 9 2 1, move 3 1 2, move 3 10 2", 143, 24, 167, 3),
    (7, "move 2 1 1, move 9 2 1, move 1 5 1, move 3 1 2, move 3 10 2, move 7 5 1", 144, 24, 168, 3),
)
_ROOT0_TERMINAL = (
    "move 3 1 1, move 8 1 1, move 8 2 2, move 7 2 1, move 3 8 7, move 10 8 1, "
    "move 4 10 1, move 10 6 4, move 4 10 3, move 2 4 5, move 4 2 7, move 4 10 1"
)
_PUBLISHED_HEARTS = "5h 4h 3h"

# Named in the v0.133–v0.136 reports. ``artifacts/`` is gitignored.
# Absence is reported. The files are not rebuilt.
_GITIGNORED_PORTFOLIOS = (
    "artifacts/stock_boundary_v0_133/results.json",
    "artifacts/purposeful_macro_v0_134/results.json",
    "artifacts/origin_fair_v0_135/results.json",
    "artifacts/post_deal_milestone_v0_136/results.json",
)

V132_CITATION = (
    "docs/pre_sd5_backward_preparation_v0_132.md records a checkpoint-140 "
    "probe that retained 20,000 identities and did not reach checkpoint 151. "
    "This audit does not rerun that probe and does not treat its frontier "
    "as a second ancestor."
)


@dataclass(frozen=True)
class RouteSample:
    route: str
    label: str
    actions_applied: int
    g: int
    h: int
    f: int
    stock: int
    face_down: int
    foundations: int
    foundation_suits: tuple
    empty_columns: int
    two_spaces: bool
    bonds: int
    legal_tableau: int
    signature: tuple
    pack_hex: str


@dataclass(frozen=True)
class EpochContrast:
    stock: int
    canonical: RouteSample
    autonomous: RouteSample
    same_pack: bool
    same_signature: bool


@dataclass(frozen=True)
class PublishedRoot:
    index: int
    macro_text: str
    actions: tuple
    published_g: int
    published_h: int
    published_f: int
    published_face_down: int
    replay_ok: bool
    discrepancy: str
    g: int
    h: int
    f: int
    face_down: int
    stock: int
    foundations: int
    foundation_suits: tuple
    empty_columns: int
    bonds: int
    legal_tableau: int
    heart_runs: tuple
    source_signature: tuple
    outcome_signature: tuple
    source_pack: str
    target_pack: str
    option_cost: int
    option_target_g: int
    option_h: int
    option_f: int
    matches_published: bool


@dataclass(frozen=True)
class TerminalReplay:
    replay_ok: bool
    discrepancy: str
    g: int
    h: int
    f: int
    face_down: int
    foundations: int
    foundation_suits: tuple
    bonds: int
    empty_columns: int
    legal_tableau: int
    heart_runs: tuple
    stock: int


@dataclass(frozen=True)
class AncestryReading:
    status: str
    diverse: bool
    verified_checkpoints: int
    rejected_claims: int
    distinct_source_packs: int
    obligations_status: str


@dataclass(frozen=True)
class OfflineAudit:
    canonical_sha256: str
    autonomous_sha256: str
    canonical_actions: int
    autonomous_actions: int
    canonical_deals: tuple
    autonomous_deals: tuple
    canonical_terminal: RouteSample
    autonomous_terminal: RouteSample
    canonical_solved: bool
    autonomous_solved: bool
    samples: tuple
    contrasts: tuple
    checkpoint_140: RouteSample
    checkpoint_151: RouteSample
    checkpoint_152: RouteSample
    roots: tuple
    root0_terminal: TerminalReplay
    macro_ancestry: AncestryReading
    macro_ancestry_without_claims: AncestryReading
    post_deal_ancestry: AncestryReading
    post_deal_ancestry_without_claims: AncestryReading
    route_pair_ancestry: AncestryReading
    route_pair_depths: tuple
    shared_macro_source_signature: bool
    distinct_macro_outcome_signatures: int
    distinct_macro_target_packs: int
    portfolio_files_present: tuple
    portfolio_files_missing: tuple
    portfolio_files_opened: tuple
    v132_citation: str


def parse_move_list(text: str) -> tuple:
    """Parse a comma-separated published ``move`` list into 0-based actions."""

    actions = []
    for chunk in text.split(","):
        parts = chunk.strip().split()
        if len(parts) != 4 or parts[0] != "move":
            raise ValueError(f"bad published move: {chunk!r}")
        actions.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
    return tuple(actions)


def heart_top_runs(state: SpiderState) -> tuple:
    """Column-top heart runs, each written high rank through the top card."""

    found = []
    for column in state.columns:
        up = column.face_up
        if not up or up[-1].suit != "h":
            continue
        index = len(up) - 1
        ranks = [int(up[index].rank)]
        while (
            index > 0
            and up[index - 1].suit == "h"
            and up[index - 1].rank == up[index].rank + 1
        ):
            index -= 1
            ranks.append(int(up[index].rank))
        high_through_top = reversed(ranks)
        found.append(" ".join(f"{rank_str(rank).lower()}h" for rank in high_through_top))
    return tuple(found)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _sample(route: str, label: str, applied: int, g: int, state: SpiderState) -> RouteSample:
    height = int(admissible_remaining(state))
    empties = empty_column_indices(state)
    return RouteSample(
        route=route,
        label=label,
        actions_applied=applied,
        g=int(g),
        h=height,
        f=int(g) + height,
        stock=len(state.stock),
        face_down=face_down_count(state),
        foundations=len(state.foundations),
        foundation_suits=tuple(foundation_suits(state)),
        empty_columns=len(empties),
        two_spaces=len(empties) >= 2,
        bonds=int(same_suit_bonds(state)),
        legal_tableau=len(tableau_actions(state)),
        signature=diversity_signature(state),
        pack_hex=pack_state(state).hex(),
    )


def _replay_route(route: str, opening: SpiderState, actions: Sequence):
    state = opening.clone()
    g = 0
    samples = [_sample(route, "opening", 0, 0, state)]
    marked = {}
    deal_number = 0
    deal_indexes = []
    checkpoint_140 = None
    for index, action in enumerate(actions):
        if is_deal(action):
            deal_number += 1
            deal_indexes.append(index)
            samples.append(_sample(route, f"before-deal-{deal_number}", index, g, state))
        g += int(apply_action(state, action))
        applied = index + 1
        if is_deal(action):
            samples.append(_sample(route, f"after-deal-{deal_number}", applied, g, state))
        if applied in (CHECKPOINT_PREP, FIFTH_DEAL_INDEX, POST_SD5):
            marked[applied] = _sample(route, f"checkpoint-{applied}", applied, g, state)
            if applied == CHECKPOINT_PREP:
                checkpoint_140 = state.clone()
    terminal = _sample(route, "terminal", len(actions), g, state)
    samples.append(terminal)
    return samples, marked, terminal, tuple(deal_indexes), checkpoint_140, g


def _play(state: SpiderState, actions: Sequence) -> Tuple[SpiderState, int, str]:
    cursor = state.clone()
    spent = 0
    try:
        for action in actions:
            spent += int(apply_action(cursor, action))
    except (ValueError, TypeError) as exc:
        return cursor, spent, str(exc)
    return cursor, spent, ""


def _published_roots(checkpoint: SpiderState, checkpoint_g: int) -> Tuple[PublishedRoot, ...]:
    source_pack = pack_state(checkpoint).hex()
    source_signature = diversity_signature(checkpoint)
    obligations = rebuild_obligations(checkpoint)
    roots = []
    for index, text, published_g, published_h, published_f, published_fd in _PUBLISHED_MACROS:
        actions = parse_move_list(text) + (("deal",),)
        total = checkpoint_g
        cursor = checkpoint.clone()
        replay_error = ""
        for action in actions:
            try:
                total += int(apply_action(cursor, action))
            except (ValueError, TypeError) as exc:
                replay_error = str(exc)
                break
        if replay_error:
            roots.append(
                _empty_root(
                    index, text, actions, published_g, published_h, published_f, published_fd,
                    source_pack, source_signature, replay_error,
                )
            )
            continue
        height = int(admissible_remaining(cursor))
        hearts = heart_top_runs(cursor)
        target_pack = pack_state(cursor).hex()
        option_cost = option_g = option_h = option_f = -1
        try:
            option = build_option(
                checkpoint,
                actions,
                source_g=checkpoint_g,
                structural_name=f"published-root-{index}",
                obligations=obligations,
                provenance="published-v0.139-line",
            )
        except OptionContractError as exc:
            discrepancy = f"option contract: {exc}"
        else:
            option_cost = int(option.cost)
            option_g = int(option.target_g)
            option_h = int(option.h_target)
            option_f = int(option.f_target)
            signature = outcome_signature(option)
            discrepancy = ""
            if signature != diversity_signature(cursor):
                discrepancy = "outcome signature disagrees with the replayed target"
            if option_g != total or option_h != height or option_f != total + height:
                discrepancy = (
                    f"option g/h/f {option_g}/{option_h}/{option_f} "
                    f"disagrees with replay {total}/{height}/{total + height}"
                )
        matches = (
            not discrepancy
            and total == published_g
            and height == published_h
            and total + height == published_f
            and face_down_count(cursor) == published_fd
            and _PUBLISHED_HEARTS in hearts
        )
        if not matches and not discrepancy:
            discrepancy = (
                f"replay g={total} h={height} f={total + height} "
                f"face_down={face_down_count(cursor)} hearts={hearts}"
            )
        roots.append(
            PublishedRoot(
                index=index,
                macro_text=text,
                actions=actions,
                published_g=published_g,
                published_h=published_h,
                published_f=published_f,
                published_face_down=published_fd,
                replay_ok=not discrepancy,
                discrepancy=discrepancy,
                g=total,
                h=height,
                f=total + height,
                face_down=face_down_count(cursor),
                stock=len(cursor.stock),
                foundations=len(cursor.foundations),
                foundation_suits=tuple(foundation_suits(cursor)),
                empty_columns=len(empty_column_indices(cursor)),
                bonds=int(same_suit_bonds(cursor)),
                legal_tableau=len(tableau_actions(cursor)),
                heart_runs=hearts,
                source_signature=source_signature,
                outcome_signature=diversity_signature(cursor),
                source_pack=source_pack,
                target_pack=target_pack,
                option_cost=option_cost,
                option_target_g=option_g,
                option_h=option_h,
                option_f=option_f,
                matches_published=matches,
            )
        )
    return tuple(roots)


def _empty_root(index, text, actions, published_g, published_h, published_f, published_fd, source_pack, source_signature, error):
    return PublishedRoot(
        index=index,
        macro_text=text,
        actions=actions,
        published_g=published_g,
        published_h=published_h,
        published_f=published_f,
        published_face_down=published_fd,
        replay_ok=False,
        discrepancy=error,
        g=-1,
        h=-1,
        f=-1,
        face_down=-1,
        stock=-1,
        foundations=-1,
        foundation_suits=(),
        empty_columns=-1,
        bonds=-1,
        legal_tableau=-1,
        heart_runs=(),
        source_signature=source_signature,
        outcome_signature=(),
        source_pack=source_pack,
        target_pack="",
        option_cost=-1,
        option_target_g=-1,
        option_h=-1,
        option_f=-1,
        matches_published=False,
    )


def _root0_terminal(checkpoint: SpiderState, checkpoint_g: int, root_actions: Sequence) -> TerminalReplay:
    actions = tuple(root_actions) + parse_move_list(_ROOT0_TERMINAL)
    final, spent, error = _play(checkpoint, actions)
    if error:
        return TerminalReplay(False, error, -1, -1, -1, -1, -1, (), -1, -1, -1, (), -1)
    height = int(admissible_remaining(final))
    g = checkpoint_g + spent
    return TerminalReplay(
        replay_ok=True,
        discrepancy="",
        g=g,
        h=height,
        f=g + height,
        face_down=face_down_count(final),
        foundations=len(final.foundations),
        foundation_suits=tuple(foundation_suits(final)),
        bonds=int(same_suit_bonds(final)),
        empty_columns=len(empty_column_indices(final)),
        legal_tableau=len(tableau_actions(final)),
        heart_runs=heart_top_runs(final),
        stock=len(final.stock),
    )


def _reading(pick, source_packs: Sequence[str]) -> AncestryReading:
    return AncestryReading(
        status=pick.ancestor_status,
        diverse=bool(pick.diverse_ancestor_available),
        verified_checkpoints=len(pick.verified_checkpoint_packs),
        rejected_claims=int(pick.rejected_ancestor_claims),
        distinct_source_packs=len(set(source_packs)),
        obligations_status=pick.obligations_status,
    )


def _macro_options(checkpoint: SpiderState, checkpoint_g: int, roots: Sequence[PublishedRoot]):
    obligations = rebuild_obligations(checkpoint)
    options = []
    for root in roots:
        if not root.replay_ok:
            continue
        options.append(
            build_option(
                checkpoint,
                root.actions,
                source_g=checkpoint_g,
                structural_name=f"published-root-{root.index}",
                obligations=obligations,
                provenance="published-v0.139-line",
            )
        )
    return tuple(options), obligations


def _post_deal_option(root: PublishedRoot):
    if not root.replay_ok:
        return None
    state = _unpack_hex(root.target_pack)
    legal = tableau_actions(state)
    if not legal:
        return None
    action = tuple(legal[0])
    return build_option(
        state,
        (action,),
        source_g=root.g,
        structural_name=f"post-deal-root-{root.index}",
        obligations=rebuild_obligations(state),
        provenance="published-v0.139-line",
    )


def _unpack_hex(hex_text: str) -> SpiderState:
    return unpack_state(bytes.fromhex(hex_text))


def _route_pair_options(opening: SpiderState, canonical_actions, autonomous_actions, canonical_at: int, autonomous_at: int):
    """One legal step at two later states, both claimed from the opening."""

    def at(actions, count):
        state = opening.clone()
        g = 0
        for action in actions[:count]:
            g += int(apply_action(state, action))
        return state, g

    built = []
    claims = []
    opening_pack = pack_state(opening).hex()
    for name, actions, count in (
        ("canonical-checkpoint-140", canonical_actions, canonical_at),
        ("autonomous-paired-index", autonomous_actions, autonomous_at),
    ):
        state, g = at(actions, count)
        legal = tableau_actions(state)
        if not legal:
            continue
        option = build_option(
            state,
            (tuple(legal[0]),),
            source_g=g,
            structural_name=name,
            obligations=rebuild_obligations(state),
            provenance="verified-route-prefix",
        )
        built.append(option)
        claims.append(
            AncestorClaim(
                checkpoint_pack=opening_pack,
                continuation=tuple(actions[:count]),
                source_pack=option.source_pack,
                label=name,
            )
        )
    return tuple(built), tuple(claims)


def audit_verified_routes(root: Optional[Path] = None) -> OfflineAudit:
    """Replay the 172 and 185 files and the published v0.139 root lines.

    Stock length is not an ancestor. A checkpoint counts only when a claim
    replays to the option source.
    """

    root = Path(__file__).resolve().parents[2] if root is None else Path(root)
    deal_path = root / "deals" / "4925153.txt"
    canonical_path = root / "solutions" / "4925153_canonical.moves"
    autonomous_path = root / "solutions" / "4925153_autonomous_185.moves"
    opening = SpiderState.from_cards(load_deal(deal_path))
    canonical_actions = tuple(parse_moves_file(canonical_path))
    autonomous_actions = tuple(parse_moves_file(autonomous_path))
    canonical_samples, canonical_marks, canonical_terminal, canonical_deals, checkpoint, canonical_g = _replay_route(
        "canonical-172", opening, canonical_actions
    )
    autonomous_samples, autonomous_marks, autonomous_terminal, autonomous_deals, _unused, autonomous_g = _replay_route(
        "autonomous-185", opening, autonomous_actions
    )
    del canonical_g, autonomous_g, _unused
    if checkpoint is None:
        raise RuntimeError("canonical checkpoint 140 was not reached by replay")

    contrasts = []
    for stock, canonical_label, autonomous_label in (
        (50, "opening", "opening"),
        (40, "after-deal-1", "after-deal-1"),
        (30, "after-deal-2", "after-deal-2"),
        (20, "after-deal-3", "after-deal-3"),
        (10, "after-deal-4", "after-deal-4"),
        (0, "after-deal-5", "after-deal-5"),
    ):
        left = next(sample for sample in canonical_samples if sample.label == canonical_label)
        right = next(sample for sample in autonomous_samples if sample.label == autonomous_label)
        contrasts.append(
            EpochContrast(
                stock=stock,
                canonical=left,
                autonomous=right,
                same_pack=left.pack_hex == right.pack_hex,
                same_signature=left.signature == right.signature,
            )
        )

    checkpoint_g = canonical_marks[CHECKPOINT_PREP].g
    roots = _published_roots(checkpoint, checkpoint_g)
    terminal = _root0_terminal(checkpoint, checkpoint_g, roots[0].actions if roots else ())
    options, obligations = _macro_options(checkpoint, checkpoint_g, roots)
    checkpoint_pack = pack_state(checkpoint).hex()
    macro_claims = tuple(
        AncestorClaim(checkpoint_pack, (), option.source_pack, option.structural_name)
        for option in options
    )
    macro_pick = select_dependency_portfolio(options, obligations, limit=8, ancestor_claims=macro_claims)
    macro_without = select_dependency_portfolio(options, obligations, limit=8)
    post_options = tuple(
        option for option in (_post_deal_option(item) for item in roots) if option is not None
    )
    post_claims = []
    post_by_pack = {option.source_pack: option for option in post_options}
    for item in roots:
        option = post_by_pack.get(item.target_pack)
        if option is None:
            continue
        post_claims.append(
            AncestorClaim(
                checkpoint_pack,
                item.actions,
                option.source_pack,
                f"post-deal-{item.index}",
            )
        )
    post_obligations = obligations
    post_pick = select_dependency_portfolio(
        post_options,
        post_obligations,
        limit=8,
        ancestor_claims=tuple(post_claims),
    )
    post_without = select_dependency_portfolio(post_options, post_obligations, limit=8)
    pair_depth = autonomous_deals[4] if len(autonomous_deals) >= 5 else len(autonomous_actions)
    pair_options, pair_claims = _route_pair_options(
        opening,
        canonical_actions,
        autonomous_actions,
        CHECKPOINT_PREP,
        pair_depth,
    )
    if pair_options:
        pair_pick = select_dependency_portfolio(
            pair_options,
            rebuild_obligations(_unpack_hex(pair_options[0].source_pack)),
            limit=2,
            ancestor_claims=pair_claims,
        )
        pair_reading = _reading(pair_pick, [option.source_pack for option in pair_options])
    else:
        pair_reading = AncestryReading("not_established", False, 0, 0, 0, "not_applied")

    present = tuple(path for path in _GITIGNORED_PORTFOLIOS if (root / path).is_file())
    missing = tuple(path for path in _GITIGNORED_PORTFOLIOS if path not in present)
    outcome_signatures = {item.outcome_signature for item in roots if item.replay_ok}
    source_signatures = {item.source_signature for item in roots if item.replay_ok}
    solved_canonical = _unpack_hex(canonical_terminal.pack_hex)
    solved_autonomous = _unpack_hex(autonomous_terminal.pack_hex)
    return OfflineAudit(
        canonical_sha256=_file_sha256(canonical_path),
        autonomous_sha256=_file_sha256(autonomous_path),
        canonical_actions=len(canonical_actions),
        autonomous_actions=len(autonomous_actions),
        canonical_deals=canonical_deals,
        autonomous_deals=autonomous_deals,
        canonical_terminal=canonical_terminal,
        autonomous_terminal=autonomous_terminal,
        canonical_solved=bool(solved_canonical.is_solved()),
        autonomous_solved=bool(solved_autonomous.is_solved()),
        samples=tuple(canonical_samples + autonomous_samples),
        contrasts=tuple(contrasts),
        checkpoint_140=canonical_marks[CHECKPOINT_PREP],
        checkpoint_151=canonical_marks[FIFTH_DEAL_INDEX],
        checkpoint_152=canonical_marks[POST_SD5],
        roots=roots,
        root0_terminal=terminal,
        macro_ancestry=_reading(macro_pick, [option.source_pack for option in options]),
        macro_ancestry_without_claims=_reading(macro_without, [option.source_pack for option in options]),
        post_deal_ancestry=_reading(post_pick, [option.source_pack for option in post_options]),
        post_deal_ancestry_without_claims=_reading(
            post_without, [option.source_pack for option in post_options]
        ),
        route_pair_ancestry=pair_reading,
        route_pair_depths=(CHECKPOINT_PREP, pair_depth),
        shared_macro_source_signature=len(source_signatures) == 1,
        distinct_macro_outcome_signatures=len(outcome_signatures),
        distinct_macro_target_packs=len({item.target_pack for item in roots if item.replay_ok}),
        portfolio_files_present=present,
        portfolio_files_missing=missing,
        portfolio_files_opened=(),
        v132_citation=V132_CITATION,
    )
