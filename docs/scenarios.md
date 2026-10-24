# Scenarios

A scenario is a crowd plus what happens to it. All shipped scenarios use the example venue (`venues/example-minimal-festival.json`); `auto-egress` works for any venue. Run one with `python -m crowd_sim.run`, or start it as an event in the control room.

| Scenario | People | What it tests |
|---|---|---|
| `egress-end-of-night` | 8,000 | Headline act ends, everyone heads for the exits |
| `stage-change` | 8,000 | Set ends; people spread to food, toilets and other places |
| `evacuation-blocked-exit` | 8,000 | Evacuation at 5 min with the south exit lane closed |
| `entry-rush` | 6,000 | Gates open; people arrive over 20 minutes (ramping up) and spread inside |
| `gate-failure-egress` | 8,000 | Egress where the south exit lane fails at 4 min and reopens at 15 min |
| `low-adoption-evacuation` | 8,000 | Evacuation with 10% app adoption and low compliance |
| `meet-up` | 4,000 | 90% in groups of about 4, all heading to the meeting point |
| `food-court-closure` | 6,000 | Food court access closed for 10 minutes mid-event |
| `dense-dispersal` | 14,000 | Dense stage front, one narrow route out (crush risk stress test) |

## Arrival profiles

`crowd.arrival` makes people appear over a window instead of all at once:

```json
"arrival": { "start_s": 0, "end_s": 1200, "shape": "ramp" }
```

Shapes: `uniform`, `ramp` (builds up towards the end) and `peak` (most around the middle). Groups arrive together. People are not counted in any zone until they appear, and the run is not finished until the last one has arrived and left.

## Results (queue baseline vs adaptive, full size, seed 42)

Clearance is time until the last person reached their destination.

| Scenario | Baseline | Adaptive |
|---|---|---|
| dense-dispersal | 1134 s | 557 s |
| egress-end-of-night | 583 s | 309 s |
| gate-failure-egress | 1296 s (p95 1238) | 1005 s (p95 366) |
| low-adoption-evacuation | 870 s | 747 s |
| meet-up | 391 s | 355 s |
| evacuation-blocked-exit | 265 s | 265 s |
| food-court-closure, stage-change, entry-rush | no difference | no difference |

Where nothing differs the venue has only one sensible route, so there is nothing to optimise. Regenerate with `python -m crowd_sim.bench`.

## Adding your own

Copy a file in `scenarios/` and change it. Every file in `scenarios/` is picked up by the tests (`sim/tests/test_scenarios.py`) and appears in the control room.
