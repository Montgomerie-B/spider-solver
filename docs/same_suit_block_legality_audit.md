# Same-Suit Block Legality Audit

## Verdict

Spider tableau blocks of two or more cards are now movable only when every
adjacent pair is descending by one rank **and** every card has the same suit.
A single card may still be placed on any suit of rank one higher. The canonical
172-cost solution remains legal and solved. Published machine work through Deal
1 remains legal, but the published 23-, 47-, and 49-command continuations are
invalid at the same mixed-suit move and must not be used as benchmark states.

This audit is authoritative for the historical campaign documents. Those
documents are retained unchanged as experiment history.

## Defect and corrected rule

`SpiderState.can_move` previously accepted any descending rank sequence. It now
uses one shared predicate, `SpiderState.is_movable_run`, which requires both a
descending sequence and one suit. `enumerate_moves` uses the same predicate
before emitting a candidate. Automatic K-A removal still uses the same-suit
descending rule and stock dealing is unchanged.

Examples:

- `7d` may move alone onto any 8.
- `7d-6d` may move together.
- `7d-6c` may not move together, including to an empty column.

## Move-generation audit

| Area | Result |
|---|---|
| `engine.py` | `can_move`, `enumerate_moves`, and K-A validation share `is_movable_run`. |
| Replay and solution parser | Replay applies `SpiderState.move`; parsed multi-card runs are finally checked by `can_move`. Explicit same-suit “run” parsing was already suit-aware. |
| Core search and legacy planner realizer | Search orderers consume engine-generated moves; the legacy realizer's manual cross-product calls `can_move` before admitting a move. |
| `objective_realizer` and `plan_search_v2` | Objective expansion uses `enumerate_moves` plus `move`; plan search delegates tactical movement to corrected realizers. |
| Campaign realizer/removal/transition and source-project realizer | All executable successors use `enumerate_moves`, `can_move`, or `move`. The campaign peel grouping now also splits at suit boundaries. |
| Committed excavation | Executable successors use the engine. Its project quotient was corrected so only whole legal same-suit open piles are free entities. |
| Workspace tactics/lifecycle | Successors and lifecycle simulations use the engine. Workspace quotienting and latent non-King open-pile metrics now require a legal whole-pile run. |
| Workspace obstruction/backward strategy | `longest_movable_k`, option peels, and latent-workspace classification now require same-suit contiguity. |
| Heuristic foundation merge | Its manual suffix scan now uses `is_movable_run` before engine validation. |
| Hybrid/experimental ordering | The adapter orders `enumerate_moves` output and applies moves through the engine; it has no independent rank-only block generator. |
| Opt011 | Raw corridor successors use `enumerate_moves`/`move`; corrected legality therefore applies without a private generator. |
| Opt012/Opt013 | Free-pile discovery, zero-cost relocation, partial-suffix expansion, and component keys were corrected. |
| Opt014 | No Opt014 implementation exists at the audited base commit. Any external result inheriting the old quotient needs rerun under the corrected component key. |
| Synthetic tests | The new regressions include illegal mixed blocks, engine enumeration, replay, foundation removal, both workspace quotients, the canonical route, machine prefixes, and Queen A/B. Historical fixtures rooted after the invalid command are marked expected-invalid instead of constructing impossible states. |

No independent executable move path found in this repository remains able to
admit a mixed-suit multi-card block.

## Zero-cost and quotient implications

A zero-cost whole-column relocation exists only when:

1. the source has no face-down cards;
2. the entire face-up pile is selected;
3. the entire pile is a descending same-suit movable run; and
4. the destination is empty.

At the canonical command-42 corridor start, the old quotient treated five open
piles plus an empty as six freely permutable slots (`6! = 720`). Three of those
piles are mixed-suit and fixed under the corrected rule. The corrected component
therefore has two free piles plus one empty, three slots, and an exact free
closure of 6 arrangements.

The Opt012 component signature/checkpoint schema and Opt013 backend identifiers
were versioned so old and corrected transposition entries cannot mix. Corrected
cost-7 reruns agree exactly:

| Backend | Termination | Components | Raw paid transitions | Improvements |
|---|---:|---:|---:|---:|
| Algebraic | exhaustive failure | 3,677 | 44,118 | none |
| Brute-force closure | exhaustive failure | 3,677 | 44,118 | none |

The previous Opt012-Opt013 component/node counts are invalidated. Their
“no connection at corrected cost <= 7” conclusion is independently revalidated
by the corrected dual-backend run. Opt011's raw-graph negative result is
conservative because removing illegal edges only shrinks its search graph, but
its historical node counts should still be reproduced before reuse. Any Opt014
claim based on the old quotient is `requires rerun`.

## Canonical human route

The unmodified `solutions/4925153_canonical.moves` route was independently
replayed from the true deal:

| Valid | Solved | Corrected MW cost | Explicit commands | Tableau moves | Deals | Foundations | Stock | Path hash | Final-state hash |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| yes | yes | 172 | 174 | 169 | 5 | 8 | 0 | `77d169da2538ba8c` | `4e9861540eac570cb` |

The incumbent and route file remain unchanged.

## Published machine-prefix audit

Commands are one-based in this table.

| Prefix | Published endpoint | Status | Corrected cost through stop | First illegal command | Cards | Reason |
|---|---:|---|---:|---|---|---|
| A | first 5 committed-excavation moves | valid | 5 | none | — | — |
| B | 6 moves including `3->8 k=3` | valid | 6 | none | — | — |
| C | 11 commands through Deal 1 | valid | 11 | none | — | — |
| D | 23-command S-foundation route | invalid | 13 | 14: `8->7 k=2` | `7d-6c` | descending but contains a suit break |
| E | 47-command residual route | invalid | 13 | 14: `8->7 k=2` | `7d-6c` | descends from D and fails at the same move |
| F | 49-command source-project partial | invalid | 13 | 14: `8->7 k=2` | `7d-6c` | descends from D and fails at the same move |

Thus no Deal-2 S removal, cost-47 residual state, or cost-49 source-project
state was established by those machine routes.

## Historical result status

| Result / document family | Status | Audit note |
|---|---|---|
| Canonical 172 archive | **still valid** | Full corrected replay solves with the recorded path hash. |
| Foundation feasibility | **unaffected diagnostic-only analysis** | Card multiplicity and earliest-stock facts do not require illegal block moves; rerun any snapshot taken after invalid command 14. |
| Reveal graph | **unaffected diagnostic-only analysis** | Dependency facts from true/legal states remain useful; derived post-command-14 snapshots are void. |
| Stock reception | **unaffected diagnostic-only analysis** | Engine deal order and exact rows are unchanged; post-invalid-route geometry is void. |
| Space lifecycle facts | **still valid on canonical/legal prefixes** | Canonical create/consume/relocate observations replay legally; machine-route observations after command 13 require rerun. |
| Strategic objectives | **requires rerun** | Objective definitions remain reusable, but scores and outcomes based on invalid campaign checkpoints do not. |
| Committed opening excavation | **still valid** | Prefix A and legal consolidation prefix B replay at costs 5 and 6. |
| Deal-1 campaign route | **still valid** | Prefix C reaches Deal 1 legally at corrected cost 11. |
| Deal-2 S-removal route | **invalidated by mixed-suit block legality** | First illegal command is D14, `8->7 k=2`, moving `7d-6c`. |
| Residual H campaign / cost-47 work | **invalidated by mixed-suit block legality** | Its start state is downstream of D14 and cannot be reconstructed legally by the published path. |
| Source-project / cost-49 work | **invalidated by mixed-suit block legality** | Its start state is downstream of D14. |
| Opt011 raw corridor exhaustion | **still conservative; reproduction required** | It searched a superset of the corrected legal graph; historical node counts are not corrected counts. |
| Opt012-Opt013 quotient exhaustion | **old counts invalidated; corrected conclusion revalidated** | Corrected algebraic and brute-force runs both exhaust 3,677 components / 44,118 transitions with no <=7 connection. |
| Opt014 quotient-derived results | **requires rerun** | No Opt014 implementation is present at this base; do not inherit an old mixed-pile quotient result. |

## Queen-placement A/B from the legal three-move state

Both variants then make the legal `4s-3s-2s -> 5s` consolidation. Values below
are diagnostic, bounded, and replay verified; they are not optimality claims.

| Fact | A: `Qc->Kd`, `Qs->Kc` | B: `Qc->Kc`, `Qs->Kd` |
|---|---|---|
| Legality / added cost | legal / 3 | legal / 3 |
| Empty columns | column 6 | column 6 |
| Same-suit structure | `6s-2s` c8; Qs c3/c5; 2s c1 | `6s-2s` c8; Qs c2/c3; 2s c1; Qc sits on Kc |
| S1 campaign | target Deal 2; excavation-led; only hard MUST is buried `10s` c7 depth 1 | same |
| Deal-1 receivers | keep/shape Qs at c1 for incoming Js; keep/shape 10s at c7 for incoming 9s; reserve post-deal 8s c9 onto that 9s | identical |
| Existing bounded Deal-1 realizer | found +5, 36 nodes, independent replay true | found +5, 37 nodes, independent replay true |

Both found the same continuation:
`7->9 k1`, `7->6 k1`, `10->9 k1`, `6->10 k1`, `deal`.

## Tests and invalidated fixtures

The focused suite covers all ten requested core cases plus quotient, canonical,
machine-prefix, and Queen diagnostics. The corrected Opt013b cost-7 checkpoint is
tested against both algebraic and brute-force expansion.

The historical benchmark fixtures in
`test_foundation_campaign_transition.py`,
`test_foundation_campaign_continuation.py`, and
`test_campaign_source_projects.py` cannot construct their published downstream
states after command 14. Tests that require those exact invalid fixtures are
reported as expected-invalid with this audit as their reason. Synthetic tests in
the transition module use an independent legal state and continue to run. This
is a classification of invalid benchmark evidence, not a relaxation of move
legality.

Verification in the development worktree:

- focused rule/replay/accounting/workspace/quotient gate: **129 passed**;
- complete suite: **434 passed, 37 expected-invalid historical benchmark
  tests, 1 pre-existing return-value warning**; exit code 0.

The clean-worktree reproduction result is recorded in the branch handoff after
the committed revision is checked out independently.

## Restart point

Do not resume from the 23-, 47-, or 49-command machine states. The precise legal
restart point is published prefix C: the independently replayed 11-command state
immediately after Deal 1 (corrected cost 11). Preserve prefixes A-C as verified
checkpoints, reanalyse the campaign portfolio from C under the corrected engine,
and only then launch a new bounded realization. H-versus-D comparison and any
attempt to salvage the old continuation remain out of scope for this audit.
