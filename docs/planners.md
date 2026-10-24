# Planners

All planners implement `plan(venue_graph, live_state) -> plan` (schema `plan.schema.json`) and are selected with `--planner` in `crowd_sim.run`.

| Name | Idea | Use |
|---|---|---|
| `baseline` | Fastest open route, ignores congestion | Benchmark to beat |
| `queue-aware` | Splits people over routes so queues do not build up needlessly (successive averages on queue-aware times) | Default for normal and egress |
| `flow` | Time-expanded min-cost flow: earliest time everyone can be out, 10 s steps | Evacuation, single destination class |
| `adaptive` | `flow` in evacuation, `queue-aware` otherwise | What the app should run |

## How people are assigned
- Subjects are single people or whole groups (same zone, destination and step-free need), so a group always gets one route.
- People are grouped by zone and destination class. `nearest_safe` is the set of safe destinations; exits, food and toilets are classes of their own; stages and similar are fixed.
- Each zone gets split fractions over its outgoing thresholds. People are assigned to match them, keeping their previous choice while it still has a share, so plans do not flip every 10 s.
- The planner returns the resolved destination, so someone heading for a swamped exit can be sent to another one.

## Limits
- Zone density limits are not modelled by the flow planner.
- Only app users are seen; zone counts scale the load estimate up to everyone.
- Queues come from the simulator (ground truth) until sensor fusion exists.
- Defaults (congestion weight 0.5, 4 iterations, 10 s flow steps) come from a small grid search (decision 021). Gains are flat across settings.
