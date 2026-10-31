# Cycle escape on deal 4925153

## Verdict

**ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT**

Recovery worked. The play-benefit rule did not.

The opt-in arm replaced each repeated warm-root fallback with another legal action and kept playing. One warm root then revealed two more cards. The other two warm roots, and the opening, ended on the same foundation and hidden-card counts as the frozen witness control. That is one improvement, and the rule requires two. No pair got worse. No episode solved the deal.

Recommendation: Leave the default cycle guard unchanged. The opt-in escape did not show a clear foundation or hidden-card benefit.

## Two conclusions

Recovery correctness is separate from game progress.

The recovery check passed. On the three recorded warm-root stop states, the default guard still refuses the repeated fallback, and the opt-in scan selects another affordable legal action whose destination is unseen or cheaper. The official episodes did the same thing in play: each warm root matched the control actions through the old stop, then played the next action in the existing PR3 order. Those choices are recorded as `unknown-legal-fallback`. They are not witnesses, not lower bounds, and not a proved strategy. Preview steps were not added to the kernel identity count. Independent replay of every played action matched the stored packs and corrected costs.

The benefit check failed. `PROGRESS_AFTER_ESCAPE` needs at least two warm roots to gain foundations or reveal hidden cards without making the other measure worse, and it needs all four pairs to avoid a regression or a tradeoff. Only `after-deal-1` improved. A lower stock count did not occur, and it would not have counted. Extra actions did not count either.

## What was fixed before the episodes

Parent: `6a469a5aa10058423d98be57fecd057071023774`.

Specification and implementation, committed before the official arm: `7a48471f0eb14223bbde582b558f386a5dd48b6b`.

The pre-run manifest is `docs/cycle_escape_play_manifest.json`. It pins the four root packs, the opt-in flag, the budgets, the metric, and the control-file hash. The default episode flag stays off. The official arm sets it on and runs witness mode once per root.

| File | Raw SHA-256 actually read | Authorised LF | Authorised CRLF |
| --- | --- | --- | --- |
| `deals/4925153.txt` | `C0B70979B3E6B90E266691DF956026629C890F49C12ED519801D6779434734DF` | `1F99DD116590757E607A7112F09A2247BCA4B34D3AE91659E55646BCE370C943` | `C0B70979B3E6B90E266691DF956026629C890F49C12ED519801D6779434734DF` |
| `solutions/4925153_canonical.moves` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` | `B4B7E3FCC957CA7D8B1AFEB9A5DB0BAC8FB6DD96443780B5727180CE55BF4A4E` | `18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33` |

This checkout is CRLF, so the recorded hashes are the CRLF digests. The LF digests are the Git blobs of the same card tokens and move tokens. Preparation accepts only those four digests and records the hash of the bytes it read. The four roots, prefixes, and corrected costs match across both representations. The source files were not rewritten.

The control is the witness half of `docs/practical_witness_play_pilot.json`. Its SHA-256 is `CB3679168F2E90F3D24D870AA060300CD5B8D6292335B0C491460B7ECEA39BB6`. Its verdict remains `NO_CLEAR_BENEFIT`. Those episodes were not rerun.

Budgets are the #23 limits: 60 seconds, 12 additional corrected moves, 64 primitive actions, 8 decisions, 1,280 probe identities, 512 MB, one worker. Each probe is still at most 20 identities, 2 seconds, and 4 corrected moves, with no depth cap and no harvest. The selector, witness ranking, and probe procedure were not changed.

## Invocation

Working directory: the repository root. Interpreter: `py -3`. Tree clean at `7a48471f0eb14223bbde582b558f386a5dd48b6b`. One worker. One launch.

```python
from spider.practical_witness_manifest import prepare_manifest
from spider.practical_witness_play import run_cycle_escape_trial

manifest = prepare_manifest()
run_cycle_escape_trial(
    manifest,
    confirm_official=True,
    specification_sha="7a48471f0eb14223bbde582b558f386a5dd48b6b",
    implementation_sha="7a48471f0eb14223bbde582b558f386a5dd48b6b",
)
```

Traces: `docs/cycle_escape_play_pilot.json`. `tests/test_cycle_escape_play_lock.py` replays them and does not call the trial.

## Results

Checks passed. No illegal step, pack mismatch, or proof flag. `independent_cold_complete` is false. No episode solved. Windows `process_time` advances in 15.625 ms steps.

| Root | Control stop | Escape stop | Paid | Primitives | Decisions | Probe ids | Previews | Foundations | Hidden | Stock | Label |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| opening | paid-moves | paid-moves | 12 → 12 | 12 → 12 | 7 → 7 | 815 → 815 | 2 | 0 → 0 | 44 → 33 | 50 → 50 | tie |
| after-deal-1 | repeated-state | decisions | 3 → 9 | 3 → 9 | 4 → 8 | 640 → 1,280 | 10 | 0 → 0 | 12 → 10 | 40 → 40 | improved |
| after-deal-2 | repeated-state | decisions | 2 → 4 | 3 → 8 | 4 → 8 | 640 → 1,280 | 11 | 1 → 1 | 8 → 8 | 30 → 30 | tie |
| after-deal-3 | repeated-state | decisions | 3 → 8 | 3 → 8 | 4 → 8 | 640 → 1,280 | 12 | 1 → 1 | 7 → 7 | 20 → 20 | tie |

Wall and CPU seconds, control witness then escape: opening 1.348 / 1.203 then 0.987 / 1.000; after-deal-1 0.888 / 0.875 then 1.807 / 1.781; after-deal-2 1.297 / 1.281 then 3.113 / 3.078; after-deal-3 0.763 / 0.766 then 2.494 / 2.453. Preview time was 2 ms, 10 ms, 12 ms, and 14 ms. It is inside the episode clock and outside the identity counter.

The opening played the same twelve actions as the control and stopped on the paid-move cap. Its two single-action fallbacks were not repeats, so recovery did not fire. Eleven reveals still land at paid 11, and the twelfth paid move reveals nothing. Every shared reveal count has the same observed cost. Those costs are observed, not optimal.

Each warm root followed the control line through the action the old episode refused, then took the next PR3 action. Deal stayed legal and was not chosen. Every replacement was an already probed `unknown` action.

| Root | Refused fallback | Played instead | Later replacements |
| --- | --- | --- | --- |
| after-deal-1 | `(5, 7, 4)` at g 4, earlier g 2 | `(7, 6, 3)` | `(2, 9, 2)` after two repeats |
| after-deal-2 | `(0, 6, 8)` at g 2, earlier g 2 | `(7, 9, 1)` | `(4, 7, 1)`, then `(6, 4, 8)` |
| after-deal-3 | `(2, 6, 5)` at g 4, earlier g 2 | `(6, 4, 2)` | `(6, 5, 1)` after two repeats, then `(4, 5, 2)` |

On `after-deal-1` the hidden count stays 12 through paid 4, then falls to 11 at paid 5 and 10 at paid 6. Foundations stay 0. The control never reached those reveal counts, so the same-reveal table only shares the 0-reveal row at paid 0. The endpoint itself is the improvement.

On `after-deal-2` the shared line still completes the one foundation at paid 1. The escape adds five primitive actions and two paid moves, including zero-cost transfers, and the hidden count stays 8. On `after-deal-3` five further actions leave foundations at 1 and hidden at 7.

The warm episodes used all 8 decisions. The probe-identity counter is also 1,280 on that last decision. The recorded stop is `decisions` because the loop checks the decision cap first. The 60-second, 12-paid, and 512 MB caps did not bind. Stock never changed.

## Limitations

These four roots are positions from one known solution. The warm roots carry an imported prefix, so a finished warm episode would still be prefix-conditioned. Nothing here is a general rule, a cheaper solution, or a complete solve. An unknown fallback is permission to play a legal move, not evidence that the move is good. The run was not repeated, and the caps and selector were not changed after the outcome.

## Recommendation

Leave the default cycle guard unchanged. The opt-in escape did not show a clear foundation or hidden-card benefit.
