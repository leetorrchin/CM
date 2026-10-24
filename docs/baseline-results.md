# Baseline results

Planner `baseline-shortest-path`, example venue, 8,000 people, seed 42, app adoption 1.0, 70% compliance in normal and egress and 85% in evacuation, 1 s step, replan every 10 s. These are the numbers any better planner has to beat. Regenerate with:

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/<name>.json
```

| Scenario | Mean travel | 95th pct travel | Clearance | Largest queue | Groups split (peak, mean share) |
|---|---|---|---|---|---|
| egress-end-of-night | 235.5 s | 522 s | 584 s | 4,748 at the stage opening, 2,641 at the south gate | 269, 15.3% |
| stage-change | 140.7 s | 243 s | 350 s | 4,453 at the stage opening | 450, 8.7% |
| evacuation-blocked-exit (from 300 s) | 125.6 s | 236 s | 265 s | 3,990 at the stage opening, 3,879 at the north exit | 344, 9.6% |

What this shows:
- Egress is limited by the 6 m south gate (about 7.8 people per second). Clearance sits close to the time it takes 4,000 people to pass it, plus walking time.
- In the evacuation, everyone near the north side is sent to the same exit, so it carries a 3,879 person queue while the assembly field to the west gets little use. A congestion-aware planner should spread people out and lower clearance time.
- Groups split because members queue separately and cross at different times, which is what the cohesion work in Phase 3 targets.

Caveats: zone densities stay low (peak 1.65 people per m2) because zones in the example venue are large, so congestion shows up as queues at thresholds. Constants are placeholders (see decision 011).
