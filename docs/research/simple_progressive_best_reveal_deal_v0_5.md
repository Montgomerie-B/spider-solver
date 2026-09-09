# Simple Progressive Search v0.5: Best-Reveal Deal Probe

## 1. Verdict

`BEST_REVEAL_DEAL_PROBE_RECONNECTS_PROGRESS` — reveal quality survives into later stock depth vs control.

## 2. Exact treatment rule

At each stock depth, the first expanded state establishes the face-down
record and does not probe. A later expanded state with a **strictly smaller**
face-down count is a checkpoint. If `enumerate_legal_actions(MW_RULES)`
contains Deal, Deal is moved to the front of that node's children even in
Pass 0. Equal or worse face-down does not retrigger. After the probe the
search stays in the same pass. Default OFF.

## 3. Rules-contract compliance

Deal legality is `state.can_deal(MW_RULES)` plus engine legal-action
enumeration. Unrestricted Deal: empties and remaining tableau moves do not
make Deal illegal. Tiers still classify Deal; the probe is permission/order
only. No empty-column qualification. No 1-ply preparation in the probe.

## 4. Control reproduction

- Control nodes=800000 unique=155653 deals=15925 fnd=0 stop=node limit.
- Stock-0 best FD=16; lineage_dealt=False; deal_in_pass=False; later_dealt_fd=31.

## 5. Probe frequency

- Records by stock depth: [31, 30, 29, 28, 27, 26]
- Fires: [30, 29, 28, 27, 26, 0]
- Entered: [30, 29, 28, 27, 26, 0]
- TT-suppressed: [0, 0, 0, 0, 0, 0]

## 6. fd-16 causal lineage

- Strongest stock-0 checkpoint: pre_fd=14 post_fd=14 pass=0 depth=38 n_tableau=0 legal=True novel=True tt_skip=False expanded=True descendants=21 best_desc_fd=14 deepest_dealt=1 fnd=0 second_deal=True.

## 7. Coupled reveal/stock progression

| Deals completed | Best FD — control | Best FD — probe |
| ---: | ---: | ---: |
| 0 | 16 | 14 |
| 1 | 29 | 14 |
| 2 | 29 | 14 |
| 3 | 23 | 14 |
| 4 | 23 | 14 |
| 5 | 23 | 14 |

| Probe originating at stock depth | Pre-Deal FD | Post-Deal FD | Best descendant FD | Deepest deals | Foundation |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 14 | 14 | 14 | 1 | 0 |
| 1 | 14 | 14 | 14 | 2 | 0 |
| 2 | 14 | 14 | 14 | 3 | 0 |
| 3 | 14 | 14 | 14 | 4 | 0 |
| 4 | 14 | 14 | 14 | 5 | 0 |
| 5 | — | — | — | — | — |

## 8. Foundation result

Control foundations=0; treatment=0; first treatment node=None.

## 9. Complete-solution result

No complete solution.

## 10. Search/runtime effects

| | Control | Treatment |
| --- | ---: | ---: |
| Expanded | 800000 | 1000000 |
| Unique | 155653 | 286853 |
| Unique/exp | 0.1946 | 0.2869 |
| States/s | 844.8 | 1016.8 |
| TT hits | 2609963 | 1819094 |
| Reopens | 643825 | 712625 |
| Max depth | 610 | 365 |
| Deals executed | 15925 | 16065 |
| RSS MiB | 261.39453125 | 262.16015625 |
| Time s | 947.0 | 983.5 |

## 11. Interpretation

Control reproduced v0.4: stock-0 FD 16 never Deals (later_dealt 31, Pass 0, deal_in_pass false). Treatment fired 140 probes (one per strict uncover at each stock depth, as bounded by remaining face-down) and entered all of them; TT suppressed 0. The strongest stock-0 checkpoint was fd 14 in Pass 0 with no other Pass-0 tableau children — the starvation node — and Deal-now kept fd 14. Best exact FD is 14 at every stock depth 0–5 versus control 16/29/29/23/23/23. No foundation. 3M skipped: 1M already shows coupling without a foundation, so the next question is post-Deal stall, not more nodes.

## 12. Exactly one next recommendation

Keep the probe and measure post-Deal continuation next; do not add preparation-before-Deal yet.

## Integrity

Base SHA `e43c80040063d27fc2fec5d01221be6f2a8826bf`. Deal `deals/4925153.txt`.
Probe default OFF. Engine `enumerate_legal_actions` / `can_deal(MW_RULES)`
are the Deal authority. Canonical 4925153 route was not used to guide search.

