# Event log format

JSON Lines, one record per line, each valid against `schemas/event.schema.json`. Written by `sim/` (`EventLog`), later by the server. Files go in `runs/` (git-ignored). A run is reproducible from `seed + venue + scenario + planner`, so logs can always be regenerated.

Envelope: `schema_version`, `run_id`, `seq` (0, 1, 2, ...), `timestamp` (ISO 8601, from the simulated clock), `type`, `data`.

| type | data | when |
|---|---|---|
| `run_start` | venue, scenario, planner, seed, dt_s, replan_s, app_adoption, people | first line |
| `zone_state` | see below | every 5 simulated seconds |
| `mode_change` | mode, destination | scenario event |
| `closure` | threshold, closed (true or false) | scenario event |
| `plan` | a full plan (`plan.schema.json`) | every replan, only with `log_plans=True` (large) |
| `reading` | an `occupancy_reading` from an emulated camera or turnstile | only with sensors enabled |
| `position_update` | a `position_update` from the emulated app | only with sensors enabled and `emit_updates` (large) |
| `metric` | `scope: "final"` plus the run metrics, including a `sensors` section with each sensor's error | before `run_end` |
| `run_end` | t_s | last line |

## zone_state data

```json
{
  "t_s": 120.0,
  "mode": "egress",
  "zones": { "main_field": 2310, "stage_a_front": 1500 },
  "transit": { "t_field_stage:stage_a_front->main_field": 420 },
  "queues": { "t_field_exit_south:main_field->exit_lane_south": 800 },
  "cleared": 1200,
  "active": 5900,
  "groups_split": 150,
  "closed": ["t_field_exit_south"]
}
```

- `zones`: people in each zone, including those queueing at a threshold. Zero entries are omitted.
- `transit`: people currently crossing each directed threshold. Edge keys look like `threshold_id:from_zone->to_zone`.
- `queues`: people waiting to cross each directed threshold.
- `cleared`: people who reached an exit or assembly point and left the simulation.
- `groups_split`: groups with at least two remaining members that are not all in the same place.
