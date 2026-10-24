# Decisions

Newest at the bottom. Each entry: what, why, and what would make us revisit.

## 001. Single monorepo (2026-10-24)
All components in one repo so schema changes land atomically. Revisit if separate teams or release cycles appear.

## 002. Python for core, sim, connectors, server (2026-10-24)
OR-Tools, NetworkX and NumPy speed up the optimiser. `viz`, `editor` and `app` are TypeScript. Revisit if running the simulator in the browser becomes a priority.

## 003. Hand-written JSON Schema is the source of truth (2026-10-24)
Language-neutral, so Python and TypeScript cannot drift. Python validates with `jsonschema`, TypeScript types are generated.

## 004. Venue geometry: vector polygons in metres, multi-level from the start (2026-10-24)
Zones are polygons and thresholds are segments with a width, in a local metre coordinate system with an optional GPS anchor. Every zone belongs to a level. Stairs and ramps are thresholds that connect zones on different levels. Capacity derives from area and width unless overridden.

## 005. Simulator is zone-level flow first (2026-10-24)
People hop between zones with capacity limits. Scales to tens of thousands and matches the planner's model. A 2D agent mode may be added later behind the same interface.

## 006. Event log is JSON Lines (2026-10-24)
Readable, diffable, streamable. Binary formats can be added behind the same interface if size becomes a problem.

## 007. Timestamps are ISO 8601 strings (2026-10-24)
Real and simulated clocks produce the same format. The simulated clock starts from a configured start time.

## 008. First target venue is a fictional, parameterised festival (2026-10-24)
About 3 stages, 4 gates, a food area and a deliberate bottleneck, produced by the generator in `sim/`. Revisit with a real site once the editor exists.

## 009. App adoption is a global switch, 1.0 for early testing (2026-10-24)
`sim/src/crowd_sim/config.py` holds `DEFAULT_APP_ADOPTION = 1.0`, so in early runs everyone is tracked and the planner needs no cameras or gate counts. A scenario can override it with `app_adoption`. Target is about 0.25 once connectors and fusion exist.

## 010. Scenario defaults (2026-10-24)
8,000 people, 60% in groups with mean size 3, compliance 70% in normal and egress and 85% in evacuation. Three scenarios: `egress-end-of-night`, `stage-change`, `evacuation-blocked-exit`. The example venue has one stage, so `stage-change` models dispersal from it. Revisit with a generated three-stage venue.

## 011. Physical constants are placeholders (2026-10-24)
Walk speed 1.4 m/s, 1.3 people per second per metre of threshold width, default max density 3 people per m^2 (zones can override). Stairs and ramps are slower and have lower flow. All in `core/src/crowd_core/config.py`, to be calibrated against published crowd-dynamics data.

## 012. Baseline planner and planner interface (2026-10-24)
A planner is anything with `name` and `plan(venue_graph, live_state) -> plan` (see `schemas/plan.schema.json`). The baseline sends everyone along the fastest open route, ignoring congestion, resolves `nearest_safe` for evacuation, respects closures and step-free needs, and reports entities with no route in `last_unroutable`.

## 013. Zone-level engine model (2026-10-24)
People are lightweight agents. Each directed threshold has a FIFO queue and admits people at its capacity. Crossing takes the edge travel time, divided by the person's speed (0.8 to 1.2) and slowed as the source zone approaches 5.4 people per m2. Full zones block admission, except safe zones. Planners are called every 10 simulated seconds and on every mode change or closure. People follow guidance only if they have the app and a fixed draw is below the compliance for the current mode. Everyone else takes the fastest route they would find themselves (same as the baseline). Persons queued when a threshold closes or the goal changes are re-decided. Queues do not yet re-evaluate on replan, which a smarter planner may need.

## 014. Metrics (2026-10-24)
Travel time is measured from when the current goal was set. Clearance is the time from the first goal change (or the start) to the last arrival, and is null if anyone is stuck. Also reported: peak zone density, peak queue per threshold, and how many groups are split (members in different places).

## 015. Visualiser stack and data (2026-10-24)
TypeScript, Vite and Canvas 2D (the sim is zone-level, so polygons, heatmaps and flow lines are enough). Data comes from a file picker and drag and drop, or from URL parameters when the Vite dev server is running, which serves `venues/`, `runs/` and `scenarios/` under `/data` (read-only, only those three folders). PixiJS or WebGL can be added if a 2D agent mode appears. Types are hand-written for now.

## 016. Procedural venues are modular blocks on a grid (2026-10-24)
`sim/venuegen.py`: a main field, stage fronts with upper grandstands (north), food courts (south), entry plazas and an assembly field (west) and exit lanes (east), joined by thresholds on shared edges. Parameters: seed, stages, entries, exits, food courts, grandstands, and a bottleneck setting that narrows exit 1. Always valid and connected (checked on 60 random parameter sets). `generate_scenarios` writes the three standard scenarios for any generated venue, closing the narrowest exit in the evacuation one. Generated files live in `venues/generated/` and `scenarios/generated/` and are git-ignored because they can be recreated from a seed.

## 017. Emulated sensors (2026-10-24)
Cameras report noisy, biased, lagged zone counts with dropouts and outages. Turnstiles report crossings per second in the threshold's forward direction with a miss rate. The app position emulator adds Gaussian error and dropouts to reported positions and measures how often the reported position lands in the wrong zone. Defaults: camera error 10% with 3% undercount, 5 s lag and 2% dropouts; turnstile 1% misses; app position error 8 m (sigma) and 5% dropouts. They are placeholders to be replaced with measured values. Sensors exist only where the venue lists a matching `sensor_site`, are configured per scenario (`sensors`) or with `--sensors` for defaults, and use their own random stream so enabling them never changes the crowd.

## 018. Position reports are only logged on request (2026-10-24)
Reported positions are sampled (200 app users per sample) to measure wrong-zone error. Writing them to the event log is off by default because of size, and can be turned on with `emit_updates`.
