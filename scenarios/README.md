# scenarios/

A scenario describes a crowd and what happens to it: how many people, where they start, where they want to go, groups, app adoption, compliance, sensor noise, and timed events (mode change, closure). A run is `seed + venue + scenario + planner`.

Phase 0 scenarios to write:
1. `egress-end-of-night`: headline act ends, most of the crowd heads for the exits.
2. `stage-change`: crowd moves between two stages with food and toilet trips mixed in.
3. `evacuation-blocked-exit`: evacuation triggered mid-event with one exit closed.

All three exist now. Shared defaults: 8,000 people, 60% in groups (mean size 3), compliance 70% in normal and egress and 85% in evacuation. `app_adoption` is left out so the global default in `sim/src/crowd_sim/config.py` applies (1.0 for early testing, target 0.25).
