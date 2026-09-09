# Exact-State Project Intent Coalescing v0.1

## 1. Verdict

`PROJECT_INTENT_LOSS_CONFIRMED_NOT_SUFFICIENT`

Yes: exact-state deduplication was discarding StrategicProject purpose.
The bounded repair attaches that purpose to the surviving canonical
registry request. It is **not sufficient** for first-foundation conversion.

Baseline (CURRENT_FUNNEL) classified 11 F7→F8 suppressions:

* 5 `TRANSFERABLE_PROJECT_INTENT_LOST`
* 6 `STATE_ALREADY_HAS_PROJECT_INTENT`
* 0 `NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS`
* 0 `TRUE_RETENTION_LOSS`

Treatment recovered 7 project candidates (2 later serviced on the **same
request**). Funnel ceilings did not move: P0 remains F7, P2/P7 remain F9.
Zero F10–F14. Zero foundations. Do not add a project allocator or retune
retention in this sequence.

## 2. Existing F7 loss anatomy

Previous funnel (`FOUNDATION_RETENTION_LOSS_CONFIRMED`) observed 17
replayable F7 successors and 12 TT/dedup drops. This panel reproduces
the same F7 family under CURRENT_FUNNEL plus live classification.

| Deal | F7 | F8 retained | TT-dominated | Dedup-dropped | Transferable | Already has intent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 | 2 | 0 | 2 | 0 | 2 | 0 |
| P2 | 9 | 3 | 3 | 3 | 2 | 4 |
| P7 | 6 | 3 | 2 | 1 | 1 | 2 |
| **Total** | **17** | **6** | **7** | **4** | **5** | **6** |

Every suppressed F7 child still had a registry arrival. Exact TT
dominance is correct: the cheaper/equal canonical state remains.

## 3. TT loss classification

7 TT-dominated F7 successors.

* P0 both D#1 closures (`5ecbdcb5c3251d92`, `8856ac9d8986e512`) were
  transferable: surviving request did not already carry D#1.
* P2/P7 mixed: some TT hits already had the project candidate (idempotent);
  others were transferable.

No TT hit was context-only. No TT hit lacked a canonical survivor.

## 4. Child-dedup loss classification

4 same-expansion exact-child dedup drops on CURRENT_FUNNEL (P2: 3, P7: 1).

These are **not** true retention losses. The canonical child remains as
another successor kind/action identity. Funnel F8 counts physical
admission of that exact successor identity; purpose coalescing is the
separate question.

Treatment additionally recovered 3 P7 dedup intents.

## 5. Project-intent coalescing contract

When a replayable same-campaign successor is suppressed by TT or exact
child dedup:

1. Keep TT/dedup dominance unchanged.
2. Locate the surviving registry arrival and its existing service request.
3. Fresh check: named campaign `{SUIT}#{COPY}` is still the next outstanding
   foundation on that exact state (no provenance).
4. If already a candidate of that StrategicProject: no-op.
5. If unsupported: do not transfer.
6. If supported and a live continuation credit exists: `attach_continuation`
   onto the surviving request. Normal candidate selection / subscriber
   sharing follows. No new state, no extra coverage identity, no priority
   bump, no forced service, no proof authority.

## 6. Deterministic C1–C8 tests

`tests/test_project_intent_coalescing_v0_1.py`

| ID | Result |
| --- | --- |
| C1 TT transfer | best cost/witness unchanged; project gains candidate |
| C2 non-transferable | completed C#1 on survivor; no attach |
| C3 already represented | idempotent; one candidate |
| C4 two projects one child | C#1 and D#1 share one request |
| C5 same project twice | one candidate |
| C6 cheaper arrival | version updates; one project |
| C7 subscribers | ORDINARY + project; one handle |
| C8 proof | `proof_pruning_allowed is False`; coalescer never calls TT |

## 7. Natural A/B funnel

Envelope: 400 expansions, 300k tactical, 900s, frontier 256, successor
cap 10, credit 0–4, COMMON_STAGE0, STATE_LOCAL, registry, subscribers,
StrategicProject, scheduler, tactical allocation, foundation-demand
bridge, no workspace-service policy, no stock guard, no resource
planner, `target_foundation_count=1`.

| Deal | Arm | Deepest | F7 | F8 | F9 | Recovered | Later same-request service |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| P0 | A | F7 | 2 | 0 | 0 | 0 | 0 |
| P0 | B | F7 | 4 | 0 | 0 | 2 | 0 |
| P2 | A | F9 | 9 | 3 | 3 | 0 | 0 |
| P2 | B | F9 | 9 | 3 | 3 | 2 | 2 |
| P7 | A | F9 | 6 | 3 | 2 | 0 | 0 |
| P7 | B | F9 | 8 | 3 | 2 | 3 | 0 |

Physical F8 is unchanged on P2/P7. P0 still retains no F7 child.
Purpose recovery is therefore **not** the same as successor retention.

## 8. Recovered project continuations

Treatment attached 7 candidates onto surviving canonical requests
(P0: 2 TT, P2: 2 TT, P7: 3 dedup). After the first transfer, later
identical suppressions classify as `STATE_ALREADY_HAS_PROJECT_INTENT`.

## 9. Subsequent service/progress

Same-request later service: 2 (both P2). P0 and P7 recovered candidates
were not later selected for F2/F9 on that request.

Semantic project progress unchanged: P0 0/0, P2 1/1, P7 1/1.
Activity without progress: P0 2→4, P2 9→9, P7 6→8.

Next observed blocker after purpose preservation: selected-project
service still does not convert recovered candidates into deeper funnel
stages or foundations. Do not retune demands, portfolio, or add an
allocator here.

## 10. Foundation result

No F12/F13/F14 on any arm. First foundation count: **0**.

## 11. Integrity/runtime

All six best-progress routes replayed to stored cost and canonical state.
Registry handle-invariant errors: 0. Proof pruning unchanged in contract.

| Deal | Runtime B/A | Tactical B/A |
| --- | ---: | ---: |
| P0 | 0.984 | 1.022 |
| P2 | 0.942 | 1.115 |
| P7 | 1.030 | 0.993 |
| Median | 0.984 | 1.022 |

Full pytest: `2051 passed, 37 xfailed, 2 failed` in 1434s. The two failures
are pre-existing frozen workspace-service panel hash mismatches on
`d4868ce` (reproduced with the coalescing controller reverted). No new
unexpected failures from this change.

This does not change the current 400-expansion v0.8 production trajectory
unless `enable_project_intent_coalescing` is on. Production default is off.

## 12. Exactly one next recommendation

Do not add a project allocator, do not modify portfolio retention, and do
not enlarge search width. The next strategic review should compare this
architecture against a stripped alternative: human-style move ordering +
exact state memory + progressive relaxation + brute-force/backtracking.
