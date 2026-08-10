# Opt013A — Algebraic zero-cost component expansion

## Status

**ALGEBRAIC EXPANDER VALIDATED** against the Opt012 free-closure brute-force oracle.

- Branch: `opt013/algebraic-quotient-expansion`
- Base: Opt012 tip `a667eb3` (`opt012/compact-free-quotient`)
- Production expand backend: `expand_component_algebraic`
- Oracle: `expand_component_bruteforce` (full free-closure enumeration)

## Goal

Replace full free-closure walks for paid-edge expansion with an algebraic planner that:

1. Builds a legal zero-cost free rearrangement between any two labelled arrangements in the same free component (`plan_free_rearrangement`).
2. Enumerates every distinct paid successor component reachable from *any* free arrangement **without** traversing the entire free orbit for production search.

## Free orbit rule

| `n_empty` | Free-closure size | Algebraic behaviour |
|-----------|-------------------|---------------------|
| 0 | 1 (singleton) | Expand paid moves **only** from the representative. Inventing permutations would leave the free component. |
| ≥ 1 | multiset permutations of free piles on free slots | Empty-buffer free moves generate the full orbit. Materialise a covering set of labelled witnesses; enumerate paid moves from each. |

This rule was the critical correctness fix: early drafts over-generated successors from unreachable rearrangements when `n_empty == 0` (e.g. 91 algebraic vs 15 brute).

## APIs

```text
plan_free_rearrangement(source_arrangement, target_arrangement) -> List[Action]
expand_component_bruteforce(representative, members=None) -> List[record]   # oracle
expand_component_algebraic(representative) -> List[record]                # production
differential_expand(representative) -> {equal, brute_n, alg_n, ...}
prove_all_arrangements_reachable(start) -> {n_members, fails, ok}
collect_components_through_ceiling(ceiling, expand_mode)
differential_corpus_through_ceiling(ceiling)
```

Each transition record includes:

- `action`, `from_key`, `paid_cost`, `succ_state`, `succ_component_key`
- `free_path` (algebraic): reconstructible zero-cost prefix from the component representative
- `backend` id

## Coverage (symbolic transitions)

For `n_empty ≥ 1` the witness set covers:

- fixed → fixed (from canonical arrangement)
- fixed → free-pile destination
- fixed → empty free slot
- free-pile → fixed
- free-pile → free-pile / empty
- partial suffix from free pile
- whole free pile onto non-empty destination
- reveal moves (fixed source with face-down)
- successors that change which columns are free

Column labels are retained until after the paid engine replay; source/destination positions can affect successor free structure.

`plan_free_rearrangement` is deterministic (unique instance ids for multiset piles, blank-following). It does **not** use zero-cost BFS for production planning.

## Differential proof (deal 4925153 corridor)

| Ceiling | Quotient components | Algebraic ≡ brute | Notes |
|---------|---------------------|-------------------|--------|
| 0 (cmd42) | 1 | yes (42 paid outs) | 720 free members = 6!; `prove_all_arrangements_reachable` ok |
| 5 | 5 | yes (0 mismatches) | reveal-bound pruning |
| 6 | 121 | yes (0 mismatches) | matches Opt012 exhaustive count |

Pruning (target-monotonic face-down / foundation / stock / reveal bound) and minimum paid cost identity agree because successor **component key sets** match exactly.

## Wiring

`search_quotient(..., expand_mode="algebraic"|"bruteforce")` defaults to algebraic.
`ALGORITHM_ID = "opt013_algebraic_quotient"`.

Representatives for successor components:

- `n_empty == 0` → concrete post-paid state (singleton orbit)
- `n_empty ≥ 1` → canonical free arrangement

## Explicit non-goals (this phase)

- Do **not** launch cost-7 search.
- Do **not** claim a solver improvement over the 172-move archive path.
- Do **not** merge Opt012/Opt013 PRs in this phase.

## Tests

`tests/test_opt013_algebraic_expansion.py` fixtures:

- empty / two piles; multiple empties; duplicate free piles
- non-movable open column; partial suffix; fixed-source reveal
- whole free pile onto non-empty; `n_empty==0` singleton
- automatic-foundation boundary; forced key-identity (byte keys)
- real command-42 component; corpus through ceilings 5 and 6

## Files

- `src/spider/planner/diagnostics/opt013_algebraic_expansion.py`
- `src/spider/planner/diagnostics/opt012_compact_search.py` (algebraic production path)
- `src/spider/planner/diagnostics/opt012_free_quotient.py` (`expand_component_bruteforce` alias)
- `tests/test_opt013_algebraic_expansion.py`
- `docs/opt013_algebraic_expansion.md`
