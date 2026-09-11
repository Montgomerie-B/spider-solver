# Spider Solver v0.32 — Dynamic Backward Cut: Mandatory 9H Exposure

## 1. Verdict

`H9_MANDATORY_CUT_STATE_EXPLOSION` — Pass A bound by time limit

The unique pre-SD4 9H cut is valid: one face-down 9H in column 2 under JH, AH, 8D and six face-up cards. JH must flip first. v0.31 static maps and Level-2=full-legal are confirmed and fixed only in v0.32. Pass A reached levels 0-3 in 900s / 198k unique. Level 0 exhausted at 552 states without exposing 9H, so the tight 9H-direct funnel is insufficient. Levels 1-3 did not exhaust and found no H9 boundary. Pass B did not run. SD4 was never expanded. This is a bounded miss of the gateway, not a proof it is unreachable.

- Branch: `agent/dynamic-heart9-mandatory-cut-v0-32`
- Base SHA: `5ca21738d399b9faa99662e7fe7800cea560a2a3`

## 2. Implementation audit

{
  "level2_finding": "v0.31 action_allowed_at_level Level 2 is `return label != JOIN_BREAK or True`, which is unconditionally True, so Level 2 is already full-legal.",
  "level2_unconditional": true,
  "static_dependency_map": true,
  "static_finding": "v0.31 builds build_dependency_map(src) once per origin and reuses deps[origin] for every descendant. Blocker columns therefore go stale.",
  "v32_fix": "v0.32 recomputes h9_progress from the current unpacked state and Level 2 excludes JOIN_BREAK while Level 3 admits every engine-legal action."
}

## 3. Mandatory cut

{
  "h9": {
    "column_0": 1,
    "column_1": 2,
    "down_index": 1,
    "face_down_above": [
      "JH",
      "AH",
      "8D"
    ],
    "face_down_blockers_above": 3,
    "face_down_len": 5,
    "face_up": false,
    "face_up_above": [
      "KD",
      "QS",
      "JD",
      "10H",
      "9D",
      "8D"
    ],
    "face_up_count": 6,
    "in_sd3": false,
    "zone": "down"
  },
  "jh": {
    "column_0": 1,
    "column_1": 2,
    "down_index": 2,
    "face_down_above": [
      "AH",
      "8D"
    ],
    "face_down_blockers_above": 2,
    "face_down_len": 5,
    "face_up": false,
    "face_up_above": [
      "KD",
      "QS",
      "JD",
      "10H",
      "9D",
      "8D"
    ],
    "face_up_count": 6,
    "in_sd3": false,
    "zone": "down"
  },
  "jh_must_flip_before_h9": true,
  "proof": "Heart 1 before SD4 needs one 9H. Tableau+SD3 contains exactly one 9H, currently face-down. Every such route therefore crosses the first state in which that 9H is face-up. This is a trajectory cut, not a licence to prune moves that do not immediately expose 9H.",
  "valid": true
}

## 4. Pass A

- levels=[0, 1, 2, 3] unique=198303 expanded=228681 generated=742359 dups=488222 reopens=55838
- first_g=None best_g=None portfolio=0 timings=[] stop=time limit elapsed_s=900.0000213999883 rss=149.078125

## 5. Pass B

{
  "run": false
}

## 6. Boundary

{}

## 7. Exactly one next recommendation

Keep the dynamic 9H cut; do not raise these limits here and do not take SD4.

## Integrity

Verdict H9_MANDATORY_CUT_STATE_EXPLOSION. SD4 expanded=False.
No Heart-foundation search. No production change. No human-route guidance.

