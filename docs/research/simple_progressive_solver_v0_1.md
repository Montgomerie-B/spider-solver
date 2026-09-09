# Simple Progressive Search Baseline v0.1

## 1. Verdict

`SIMPLE_SOLVER_NO_FOUNDATION_BUT_DEEPER`

No foundation on P0/P2/P7. Cheap ordering plus exact memory plus
backtracking plus relaxation **does** uncover far deeper than the
strategic controller's recent 0-foundation ceiling, but it does not
convert that uncovering into a completed suit in this envelope.

This is a competing solver, not a patch to the strategic controller.

## 2. Solver contract

Reuses only:

* engine / cards / rules;
* legal move generation, apply, flip, K-A removal;
* stock Deal legality (Unrestricted Deal);
* `canonical_state_key`;
* `replay_actions`.

Does **not** import `anytime_controller`, scheduler, campaigns, registry,
StrategicProject, or the resource planner.

Relaxation stages (equal node/time slices):

| Stage | Allowed |
| --- | --- |
| STRICT | same-suit extend, uncover (no join-break) |
| BUILD | + mixed descending, king-to-empty |
| SPACE | + create empty, non-king empty park |
| DEAL | + stock deal |
| ANY | + same-suit join-breaks |

Exact TT stores `(g, expanded_stage)` and re-expands only when g improves
or the stage is strictly looser.

## 3. Envelope

200,000 nodes, 180s wall, target 1 foundation, all five stages.
Deals: frozen P0 (`4925153`), P2, P7.

## 4. Natural results (joint trajectories)

Replay of the single best progress path per deal — not mixed extrema.

| Deal | Foundations | Path fd (from 44) | Path stock rows | Cost | Length | Nodes | Time | Stage | Replay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| P0 | 0 | **11** | 5 | 40 | 40 | 197282 | 178.8s | 4 | OK |
| P2 | 0 | **7** | 5 | 158 | 171 | 195423 | 166.9s | 4 | OK |
| P7 | 0 | **23** | 5 | 49 | 49 | 183242 | 130.3s | 4 | OK |

Search-wide minima (different states, not combined with the path above):
P0/P2/P7 also visited stock-row 0 positions.

## 5. Comparison to strategic controller

Recent 400-expansion 4-suit strategic runs, including project-intent
coalescing, still report **0 foundations**. Typical early strategic
face-down on 4925153 remained in the high 30s when first fully-revealed
columns appeared.

This baseline, with no campaign analysis, reached **11 / 7 / 23**
face-down on a replayable path while still holding all 5 stock rows.
That supports “simple ordering increases useful density” and does **not**
yet support “brute-force finishes a foundation in this budget.”

## 6. Integrity

* Source states unmodified (cloned).
* Paths replay through `replay_actions`; cost matches.
* Solver source does not import the strategic controller.
* Controller does not import this solver.
* Production default of the anytime controller is unchanged.

Full pytest: `2060 passed, 37 xfailed, 2 failed` in 1351s. The two failures are
the pre-existing frozen workspace-service panel hash mismatches.

## 7. Exactly one next recommendation

Give the **same** isolated solver a larger node/time envelope (and/or
iterative deepening on path length) before judging the hypothesis
settled. Do not merge it into the strategic controller.
