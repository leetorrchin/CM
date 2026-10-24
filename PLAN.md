# crowD build plan

Last updated 2026-10-24. Core decisions (Python, monorepo, vector multi-level venues, zone-level sim first, JSONL event log) are recorded in `docs/decisions.md`.

## Target

A large concert or festival: tens of thousands of attendees, multiple stages, many entry and exit points, mixed indoor and outdoor areas. Use cases in priority order:

1. Evacuation
2. Egress at the end of the event or a headline act
3. General flow (arrivals, stage changes, queues)

## Guiding decisions

1. **Simulate before building the app.** The optimiser can be built and judged with synthetic crowds. Positioning and the app are the slowest and riskiest parts, so they should not block the core.
2. **Core is headless.** `core/` takes a venue graph, a live occupancy state and the groups, and returns a plan. No network, UI or device code in it.
3. **Baseline first.** Plain shortest-path routing is the benchmark. Every optimiser change has to beat it on simulated scenarios.
4. **Macroscopic at scale.** At this size, plan on zones and thresholds (flows, densities) and derive individual guidance from that, instead of optimising every person.
5. **Never depend on the app.** Only some of the crowd will have it. Occupancy has to come from several sources, and evacuation must work with fallbacks.
6. **One venue, end to end, before generalising.**
7. **Everything behind an interface.** Real and emulated versions of people, venues, sensors, guidance delivery and the clock are interchangeable. The server and planner never know which they are talking to.
8. **If you cannot see it, you cannot debug it.** The visualiser is built alongside the simulator, not after it.

## Modularity and emulation

Early on there is no access to real crowds, so emulated inputs are first-class, not a stopgap. Each seam below has a real implementation (built later) and an emulated one (built first).

| Interface | Real | Emulated |
|---|---|---|
| VenueSource | Template from the editor | Procedural festival generator, hand-written JSON |
| PositionSource | Entity app | Synthetic agents with speed, goals, groups and phone-like noise |
| OccupancySource | Camera, turnstile, Wi-Fi/BLE adapters | Fake sensors derived from simulated ground truth, with noise, lag and failures |
| Planner | Optimiser | Baseline shortest path, or any experimental planner |
| GuidanceSink | Push to the app | Simulated people who follow guidance with a compliance probability |
| Clock | Wall clock | Simulated clock, faster than real time, deterministic from a seed |
| EventLog | Same | Same (every run is recorded, replayable, comparable) |

Rules:
- Components communicate only through versioned message schemas. No shared globals, no reaching into another component's internals.
- Dependencies point inward: `core/` depends on nothing in the repo, `sim/` and `connectors/` only on `core/` and `schemas/`, `viz/` only on the event log and venue schemas.
- The same server code runs against simulated or real inputs, chosen by configuration.
- A run is a seed, a venue, a scenario and a planner. Re-running it gives the same result, so regressions are easy to spot.

### Emulated people
- Walking speed distribution, density-dependent slowdown (a standard fundamental diagram to start with), goals and dwell time at stages and stalls.
- Group members that follow each other and try to regroup.
- Compliance: a probability of following guidance, and a tendency to follow the crowd instead.
- Evacuation behaviour: familiar-exit bias, herding, delayed reaction.
- Position noise, dropouts and a configurable app adoption rate.

### Emulated venues
- Procedural generator: number of stages, gates, corridor widths, bottleneck severity, indoor and outdoor areas, all from parameters and a seed.
- Used for stress tests ("does the planner still win on 200 random venues?") on top of the hand-built target venue.

### Visualiser (`viz/`)
- Venue map with zones, thresholds, pathways, closures and assembly points.
- Density heatmap per zone, and crowd rendering that scales to tens of thousands of agents (particles or density, not individual DOM elements).
- Groups highlighted, planned routes and next waypoints shown as arrows, queue lengths at thresholds.
- Timeline with play, pause, speed and scrubbing. Live mode over WebSocket, replay mode from an event log file.
- Side-by-side comparison of two planners (for example baseline versus optimiser) on the same seed, with a metrics panel.
- Later reused as the operator console, so effort spent here is not throwaway.

## Problem formulation

- Venue becomes a directed graph. Nodes are zones and thresholds. Edges carry length, free-flow travel time and capacity (people per second, based on width).
- Time-expanded network over a horizon of roughly 1 to 5 minutes in 5 to 10 second steps.
- Entities are grouped into commodities by destination. One destination is a single-commodity min-cost flow, solved exactly. Many destinations is multi-commodity, which is harder.
- Modes and objectives:
  - Normal: minimise total travel time, with a penalty on density above a comfort threshold and a fairness term so nobody gets a long detour to help the average.
  - Egress: as above, with extra weight on keeping queues out of critical areas.
  - Evacuation: minimise the clearance time of the last person (min-max), with hard density limits and operator-defined closures and hazards.
- Re-plan every few seconds on a rolling horizon, warm started from the previous plan.

Solver approach, in order of effort:

1. Static shortest path (baseline).
2. Shortest path with congestion-aware edge costs, iterated (dynamic traffic assignment style).
3. Time-expanded min-cost flow for a single destination, and min-max variant for evacuation.
4. Multi-commodity: sequential or prioritised assignment, then LP relaxation with rounding if the heuristic is not good enough.

### Groups

- A group is a single super-entity in the planner: same route, same waypoint, with speed set by the slowest member.
- Cohesion is a soft constraint with a configurable penalty for splitting, so it can be traded off against delay in normal mode.
- In evacuation mode the penalty is much lower. Safety wins, and the app proposes a meeting point at a safe location for anyone separated.
- Group formation: invite code or QR in the app. Groups need an ID and a member list, but no personal identity.
- Simulator must model groups, including how a group's speed and spacing differ from individuals.

### Occupancy sensing and fusion

- Common reading format: source, type, target (zone or threshold), timestamp, count or flow, confidence.
- Source types: app positions, camera counts, turnstile and ticket scans, Wi-Fi and BLE counts, manual operator input.
- Fusion estimates per-zone density and per-threshold flow by combining sources weighted by confidence and age. App positions are treated as a sample of the crowd and scaled up using the adoption rate, cross-checked against camera and gate counts.
- Stale or failed sources are detected and dropped, and confidence is shown to operators.
- Privacy: cameras provide counts only, processed on the edge. No images or video reach crowD.

### Evacuation requirements

- Operator console to switch modes, close thresholds, mark hazards and designate assembly points.
- Pre-computed plans per scenario, generated offline from the venue graph, usable when live data or connectivity fails. These are what signage and staff follow.
- Accessibility: step-free routes and extra time for entities flagged as needing them.
- Validation in the simulator across many scenarios (blocked exits, one stage overcrowded, partial compliance, low app adoption) before anything real.
- External: review with the event's safety officers and local regulations, and test in drills. This is not something to deploy on an untested basis.

## Phases

### Phase 0: Spec (about 1 to 2 weeks)
- Venue format: vector polygons in metres, multi-level, zones, thresholds, pathways, destinations, one-way flags, capacities, assembly points. (Drafted, schema v0.1.0.)
- Data models for entity, group, plan, mode and occupancy reading.
- Pick one target festival layout (can be a realistic fictional one) and three scenarios: end-of-night egress, stage change, evacuation with a blocked exit.
- Record decisions in `docs/`.
- **Done when:** a hand-written JSON venue validates against the schema.

### Phase 1: Venue graph and baseline (1 to 2 weeks)
- JSON Schema in `schemas/` and validator in `core/` (done in Phase 0, extend as needed).
- Compiler from template to graph in `core/`.
- Baseline shortest-path router with unit tests.
- Example venues, including a festival layout with deliberate bottlenecks.
- **Done when:** given a venue and entity positions, the router returns a path per entity.

### Phase 2: Emulation and visualiser (3 to 4 weeks)
Progress: done are the clock, event log, zone-level engine, emulated people with groups and compliance, scenarios and metrics (baseline numbers in `docs/baseline-results.md`), the procedural venue and scenario generator, emulated cameras, turnstiles and app position noise, and visualiser v1 (replay, heatmap, queues, closures, timeline, side-by-side comparison). Remaining: Wi-Fi and BLE counters, manual operator input, a live (WebSocket) mode in the viewer, and wiring the sim to the server through the real interfaces.
- Simulated clock, event log format, and the interfaces from the table above.
- Discrete-time simulator on the venue graph with edge capacities and queueing at thresholds.
- Emulated people with the behaviours listed above, including groups, compliance and noise.
- Procedural venue generator and the first festival venue.
- Emulated sensors (camera counts, turnstiles) driven from ground truth.
- Scenario files: entity counts, spawn zones, destinations, arrival timing, group size distribution, app adoption rate, compliance rate.
- Metrics: mean and 95th percentile travel time, clearance time, peak density per zone, queue lengths, groups split.
- Visualiser v1: venue, moving crowd, density heatmap, timeline scrubber, replay from event log.
- **Done when:** baseline results are reproducible from a seed, congestion at the bottlenecks is visible in the visualiser, and swapping the emulated position source for a stub "real" one needs no changes outside configuration.

### Phase 3: Optimiser, groups and evacuation (4 to 6 weeks)

**Progress:** groups-as-units, queue switching, queue-aware and flow planners, adaptive mode switching and the benchmark are done. Tuning and a 50,000-person scale test are done (decision 021). Left: hazards, fallback plan generator, cohesion cost measurement.

- Solver steps 2 to 4, behind one interface so they can be swapped in the simulator.
- Rolling horizon re-planning loop.
- Group handling as super-entities, with the soft cohesion penalty.
- Modes: normal, egress, evacuation (min-max objective, closures, hazards).
- Pre-computed fallback plan generator.
- Benchmark table against baseline in `docs/`.
- **Done when:** the optimiser beats baseline on clearance time and peak density on the bottleneck scenarios, groups stay together at a measured low cost in normal mode, and plans compute within the re-plan interval at the target scale.

### Phase 4: Venue editor (2 to 3 weeks)
- Web canvas editor: draw zones, place thresholds, mark pathways and one-way, place destinations and assembly points, set capacities.
- Import a site plan image as a background to trace over.
- Import and export the template JSON, with live validation errors.
- **Done when:** a festival site can be drawn from a plan and loaded into the simulator without hand-editing JSON.

### Phase 5: Entity app and positioning (3 to 4 weeks)
- Expo app: join a venue, show position on the map, show next waypoint and direction, create and join groups.
- Positioning spike first (1 week): GPS outdoors, plus BLE or Wi-Fi where GPS is weak. Choose what v1 needs.
- Smoothing and snapping of raw positions to the venue graph.
- Group features: see members, meeting point suggestions.
- Offline behaviour: keep the last guidance if the connection drops.
- **Done when:** a phone walking through a real space is placed in the right zone most of the time and shows sensible guidance.

### Phase 6: Realtime server and operator console (3 to 4 weeks)
- FastAPI with WebSockets: ingest positions, hold live state, run the optimiser on a timer, push guidance.
- Operator console: built on the Phase 2 visualiser in live mode, adding mode switch, closures, hazards and plan overview.
- Venue and event management endpoints.
- Load test with simulated clients at target scale.
- **Done when:** the simulator can drive the server using the same protocol as the app.

### Phase 7: Occupancy connectors and fusion (3 to 4 weeks)
- Connector interface and reading schema.
- Adapters: webhook, MQTT, turnstile feed, a camera counting adapter (start with a simulated one, then one real vendor or an open-source people counter on an edge device), and manual input.
- Fusion layer with confidence weighting, adoption-rate scaling and stale-source handling.
- Real adapters implement the same OccupancySource interface as the emulated sensors, so they can be swapped in or run side by side to compare against the simulated ground truth.
- **Done when:** the optimiser keeps performing in simulation when the app adoption rate is low and one or more sensors are noisy or offline.

### Phase 8: Drills, pilot and hardening (ongoing)
- Small real test with friends in a real space, then a drill with safety staff.
- Failure modes: lost positions, app killed, stale plans, sensor outages, people going against guidance.
- Privacy: retention limits, anonymous IDs by default, camera counts only.
- Regulatory and liability review for evacuation use.

## Milestones

| Milestone | Phases | Outcome |
|---|---|---|
| M1 | 0 to 2 | Festival venue in, emulated crowd out, baseline numbers, all watchable in the visualiser. |
| M2 | 3 | Optimiser with groups and evacuation mode beats baseline in simulation. |
| M3 | 4 and 5 | Draw a venue and walk it with a phone. |
| M4 | 6 and 7 | Live end-to-end with operator console and multiple occupancy sources. |
| M5 | 8 | Drill with safety staff. |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Low app adoption | Density estimates are poor | Fuse several sources, scale up the app sample, treat the app as one input |
| Positioning inaccurate near structures or in dense crowds | Guidance sent to the wrong people | Early spike, snap to graph, plan at zone level |
| Multi-commodity solve too slow at scale | Plans stale before use | Macroscopic planning, heuristics first, warm start, solve per region |
| People ignore guidance, or herd | Plan assumptions break | Model compliance in the simulator, re-plan from observed state |
| Evacuation guidance wrong or unavailable | Serious safety harm | Pre-computed fallbacks, operator override, simulator validation, drills, safety officer review, never the sole system |
| Group cohesion slows evacuation | Longer clearance | Low cohesion weight in evacuation mode, measured in simulation |
| Camera data privacy | Legal and trust issues | Counts only, edge processing, no video stored or sent |
| Simulation does not match real crowd behaviour | Results look good in sim and fail in reality | Start from established density and speed relationships, vary behaviour parameters widely, test robustness not just averages, calibrate with real data from drills when possible |
| Venue drawing is tedious | Nobody uses the editor | Trace over site plan images, sensible defaults for capacity |

## Immediate next steps

1. Done: example festival venue and the three scenarios (`scenarios/`).
2. Write the venue schema and one example venue by hand, including the occupancy reading and group data models. (Done: see `schemas/` and `venues/`.)
3. Repo skeleton (done: `schemas/`, `core/`, `sim/`, `connectors/`, `server/`, `docs/`). Still to do: CI running tests, and `viz/` project setup.
4. Done: graph compiler and baseline router (`core/`), clock, event log, the first emulated crowd, venue generator and sensors (`sim/`), and the run viewer (`viz/`). Phase 3 is largely built: unit-based groups, queue switching, queue-aware, flow and adaptive planners (`core/optimiser.py`), and a benchmark (`docs/benchmarks.md`). Next: hazards, a fallback plan generator, a cohesion-cost measurement in normal mode, and an arrivals scenario for turnstiles.
