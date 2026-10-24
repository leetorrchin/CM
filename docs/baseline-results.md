# Baseline results

Planner `baseline-shortest-path`, example venue, 8,000 people, seed 42, app adoption 1.0, 70% compliance in normal and egress and 85% in evacuation, 1 s step, replan every 10 s. These are the numbers any better planner has to beat. Regenerate with:

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/<name>.json
```

| Scenario | Mean travel | 95th pct travel | Clearance |
|---|---|---|---|
| egress-end-of-night | 241.3 s | 529 s | 583 s |
| stage-change | 147.7 s | 248 s | 350 s |
| evacuation-blocked-exit (from 300 s) | 131.6 s | 243 s | 265 s |

Groups now move as one unit, so none are split (decision 019). Numbers changed from the earlier person-based engine for that reason. Planner comparison is in `docs/benchmarks.md`.

What this shows:
- Egress is limited by the 6 m south gate (about 7.8 people per second). Clearance sits close to the time it takes 4,000 people to pass it, plus walking time.
- In the evacuation, everyone near the north side is sent to the same exit, so it carries a 3,879 person queue while the assembly field to the west gets little use. A congestion-aware planner should spread people out and lower clearance time.

Caveats: zone densities stay low (peak 1.65 people per m2) because zones in the example venue are large, so congestion shows up as queues at thresholds. Constants are placeholders (see decision 011).
