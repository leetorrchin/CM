# crowD

An algorithmic manager that determines the optimal flow of entities given their spatial distribution.

crowD takes a drawn-out event space and a live picture of how full it is, then works out where people should go next so the crowd as a whole moves efficiently and safely. Think of it as traffic management for people. The first target is a large concert or festival, for both everyday flow (arrivals, stage changes, exits) and evacuation.

> Status: early build. Venue schemas, a graph compiler, a zone-level crowd simulator (groups move as units), a procedural venue generator, emulated sensors, a run viewer, and three planners (baseline, queue-aware, flow, plus an adaptive wrapper) are in place. See [PLAN.md](PLAN.md) for the build plan and [docs/planners.md](docs/planners.md) for the planners.

## What it does

1. **Optimal pathing.** Given an event space and where entities are, compute routes for all of them.
   - Many origins, one shared destination (for example everyone leaving through the exits).
   - Many origins, many destinations (for example attendees heading to different stages, food stalls, or gates).
2. **On-device tracking.** Each entity runs an app that reports where they are in the venue and shows them where to go.
3. **Venue templates.** A template format and editor for drawing an event space, so the system can ingest destinations, areas, thresholds (doors, gates, stairs) and pathways without hand-written config.
4. **Occupancy connectors.** Not everyone will have the app, so crowd density cannot come from app positions alone. crowD accepts occupancy data from other sources through APIs and connectors, such as cameras with people counting, turnstile and ticket scans, and Wi-Fi or BLE counts. These are fused with app positions into one estimate of how full each zone and path is.
5. **Groups.** Friends and families can link up in the app as a group. The planner treats a group as a unit, so the algorithm does not split people up, and it can suggest meeting points if a group gets separated.
6. **Evacuation mode.** Beyond everyday flow, crowD has an evacuation mode that minimises the time for everyone to reach safety, supports operator overrides (closing a gate, blocking a path), and degrades safely to pre-computed plans if live data or connectivity is lost.

## Core concepts

| Term | Meaning |
|---|---|
| Venue | The whole event space, made of one or more floors or areas. |
| Zone | A walkable area with a known size, so it has a capacity. |
| Threshold | A connection between zones (door, gate, stairs, ramp) with a throughput limit. |
| Pathway | A designated route between zones, optionally one-way. |
| Destination | A place entities want to reach (exit, stage, stall, toilets, assembly point). |
| Entity | A tracked person, with a position, a goal, and optional attributes (for example needs step-free access). |
| Group | Two or more entities that want to stay together. |
| Occupancy source | Anything that reports how many people are in a zone or crossing a threshold (app, camera, turnstile, manual input). |
| Mode | The current objective: normal flow, egress, or evacuation. |
| Plan | The current assignment of a next waypoint to every entity or group, recomputed continuously. |

## How it works

Every box below sits behind an interface. The real thing and an emulated version are interchangeable.

```
 VenueSource ---------> Compiler --> Venue graph --+
 (template file | procedural generator)            |
                                                   |
 PositionSource ------+                            |
 (real app | emulated people)                      |
                      +--> Fusion --> Live state --+--> Planner --> GuidanceSink
 OccupancySource -----+                            |    (baseline |   (real app push |
 (real sensors | emulated sensors)                 |     optimiser)    emulated people)
                                                   |
 Operator console --> mode, closures --------------+

 Clock (real | simulated)        Event log --> Visualiser (live or replay)
```

- The **compiler** turns a drawn template into a graph with capacities and travel times.
- The **fusion** layer combines app positions and connector data into per-zone occupancy and flow estimates, each with a confidence value.
- The **optimiser** treats the crowd as a flow problem on a time-expanded version of the graph, with capacity limits on zones and thresholds, and re-plans on a rolling horizon. Groups move as one unit.
- The **entity app** sends position updates and displays the next waypoint.
- A **simulator** runs the same optimiser against synthetic crowds, including groups, partial app adoption and non-compliance, so changes can be measured and watched in the visualiser before touching a real venue.

At festival scale (tens of thousands of people) the planner works mostly at zone and threshold level rather than optimising every individual, and individual guidance is derived from that.

## Modular by design, emulation first

It is very early, and testing with real crowds is not realistic. So the system is built so that people, venues and sensors can all be emulated, and everything can be watched in a visualiser.

- **Interfaces everywhere.** Components talk through small, versioned message schemas. Swapping a real source for an emulated one means changing configuration, not code.
- **Emulated people.** Synthetic entities with walking speeds, destinations, group behaviour, compliance with guidance, and (in evacuation) herding. Position noise and dropouts can be added to mimic real phones.
- **Emulated venues.** Besides hand-drawn templates, a procedural generator produces festival-style layouts (stages, gates, corridors, bottlenecks) from parameters, so the planner can be tested on many layouts.
- **Emulated sensors.** Fake cameras, turnstiles and Wi-Fi counters derived from the simulated ground truth, with configurable noise, lag and failures.
- **Simulated clock.** Runs faster than real time and is deterministic from a seed, so any run can be reproduced.
- **Event log.** Every state change is recorded. The visualiser plays it back or follows it live, and the same server code runs against simulated or real inputs.
- **Visualiser.** A web view of the venue with density heatmaps, moving crowds, groups, planned routes, closures and a timeline scrubber, with side-by-side comparison of two planners on the same scenario. See `viz/`.

## Planned architecture

| Component | Responsibility | Proposed stack |
|---|---|---|
| `schemas/` | JSON Schemas for venues and every message between components | JSON Schema (draft 2020-12) |
| `venues/` | Example and fixture venue files | JSON |
| `scenarios/` | Scenario files for the simulator | JSON |
| `core/` | Venue graph, planner interface, baseline and optimiser, groups, validation | Python, NetworkX, OR-Tools |
| `sim/` | Emulated people, venue generator, emulated sensors, simulated clock, scenarios | Python |
| `viz/` | Visualiser for live and replayed runs, shared with the operator console | TypeScript, canvas or PixiJS |
| `connectors/` | Real occupancy source adapters and fusion | Python |
| `server/` | Live state, plan distribution, operator API | Python, FastAPI, WebSockets |
| `editor/` | Web tool for drawing venues | TypeScript, React, canvas |
| `app/` | Real entity tracking, groups and guidance | React Native (Expo) |
| `docs/` | Design notes, decisions | Markdown |

These are starting choices, not commitments. Hard rules: `core/` depends on nothing else in the repo, `sim/` and `connectors/` depend only on `core/` and `schemas/`, and no component reaches into another except through the schemas.

## Occupancy connectors

Every source implements the same small interface and reports readings like:

```json
{
  "source": "camera-gate-3",
  "type": "camera_count",
  "target": { "kind": "zone", "id": "main-stage-front" },
  "timestamp": "2026-10-24T17:45:00+11:00",
  "count": 1840,
  "confidence": 0.85
}
```

Planned adapters: generic webhook and MQTT ingest, vendor camera counting APIs, turnstile and ticketing feeds, Wi-Fi and BLE counters, and manual operator input. Cameras should send counts only. Raw video stays on the edge device and never reaches crowD.

## Groups

- Members link up in the app (invite code or QR).
- The planner assigns a group the same route and waypoint, and paces it to the slowest member.
- If members get separated, the app suggests a nearby meeting point on a route that suits them all.
- In evacuation mode, safety comes first. Cohesion is kept where it costs little, but never at the expense of clearing the venue.

## Evacuation

- Objective is minimum time for the last person to reach safety, rather than average travel time.
- Operators can close thresholds, mark hazards and switch modes, and the plan updates immediately.
- Fallbacks: if live data is stale, crowD uses pre-computed plans per scenario. If the app or network is unavailable, venue signage and staff follow the same pre-computed plans. crowD must never be the only thing people depend on.
- Real-world use needs sign-off from the event's safety officers and compliance with local regulations, and should be exercised in drills before any live use.

## Repository layout (planned)

```
crowD/
  README.md
  PLAN.md
  schemas/      JSON Schemas, the contract between components
  venues/       example and fixture venue files
  scenarios/    scenario files for the simulator
  core/         graph, planner interface, optimiser, groups
  sim/          emulated people, venues, sensors, scenarios
  viz/          visualiser (live and replay)
  connectors/   real occupancy adapters and fusion
  server/       realtime and operator API
  editor/       venue drawing tool
  app/          entity app
  docs/         design notes and decision records
```

## Roadmap

See [PLAN.md](PLAN.md) for details. In short:

0. Spec and venue schema
1. Venue graph and baseline shortest-path routing
2. Emulation (synthetic people, venues, sensors) and the visualiser
3. Optimiser with groups and evacuation mode
4. Venue editor
5. Entity app and positioning
6. Realtime server and operator console
7. Occupancy connectors and fusion
8. Drills, pilot and hardening

## Open questions

- Indoor and outdoor positioning: GPS is fine in open fields but weak near structures. Which supplement (BLE, UWB, Wi-Fi) is worth it?
- App adoption: what fraction of a crowd will realistically have the app, and how does that change the fusion and guidance design?
- Compliance: how far will people follow guidance, and what happens when they do not?
- Privacy: how long is location data kept, and is it ever tied to identity? Camera data should be counts only.
- Regulation and liability for evacuation guidance in the target jurisdiction.
- Which camera or counting vendors to support first.
- How faithful the emulation needs to be, and how to calibrate it against real crowd behaviour (density and speed relationships, drill data) when that becomes possible.

## Getting started

Needs [uv](https://docs.astral.sh/uv/).

```
uv sync --all-packages
uv run pytest
uv run python -m crowd_core.venue venues/example-minimal-festival.json
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/egress-end-of-night.json
uv run python -m crowd_sim.venuegen --seed 7 --stages 4   # generate a venue and its scenarios
cd viz && npm install && npm run dev                      # watch runs in the browser
```

Layout and dependency rules are in [docs/architecture.md](docs/architecture.md). Design decisions are logged in [docs/decisions.md](docs/decisions.md).

## Contributing

Work in small branches off `main`, keep `core/` free of server, connector and app dependencies, and add or update a simulator scenario for any change to the optimiser.
