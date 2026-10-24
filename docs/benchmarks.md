# Planner benchmarks

Generated venues, seeds [3, 7, 11], 3000 people, app adoption 1.0. Means across venues.

| scenario | planner | clearance s | mean travel s | p95 travel s | groups split | venues |
|---|---|---|---|---|---|---|
| egress-end-of-night | adaptive | 276 | 192 | 259 | 0.000 | 3 |
| egress-end-of-night | baseline | 276 | 193 | 262 | 0.000 | 3 |
| egress-end-of-night | queue-aware | 276 | 192 | 259 | 0.000 | 3 |
| evacuation-blocked-exit | adaptive | 287 | 223 | 264 | 0.000 | 3 |
| evacuation-blocked-exit | baseline | 316 | 242 | 306 | 0.000 | 3 |
| evacuation-blocked-exit | queue-aware | 287 | 223 | 262 | 0.000 | 3 |
| stage-change | adaptive | 349 | 184 | 275 | 0.000 | 3 |
| stage-change | baseline | 349 | 184 | 275 | 0.000 | 3 |
| stage-change | queue-aware | 349 | 184 | 275 | 0.000 | 3 |

Reading this honestly: on generated venues the optimisers cut evacuation clearance by about 9% (316 s to 287 s) and mean travel by 8%, but make no difference to egress or stage change, because those layouts have a single dominant bottleneck that no routing can avoid. On the example venue the egress scenario improves a lot (583 s to 307–351 s) because it has two exits with unequal capacity. The planners are untuned.

## Scale (50,000 people, generated venue seed 7, evacuation with a closed exit)

| Planner | Clearance | Mean travel | p95 travel | Plan time |
|---|---|---|---|---|
| baseline | not everyone out by 1,800 s | 851 s | 1,439 s | 0.05 s |
| adaptive | 1,057 s | 641 s | 992 s | 0.2 s |

Reproduce with `uv run python -m crowd_sim.scale --total 50000 --run`. Tuning results are from `python -m crowd_sim.tune`.
