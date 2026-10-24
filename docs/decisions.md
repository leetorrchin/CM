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

## 019. Groups move as one unit; followers can switch queues (2026-10-24)
The simulator moves units, not people. A group is one unit that waits for all its members, crosses each threshold together (using as many admission tokens as it has members) and walks at its slowest member's speed. This replaces the per-person model, where groups split. `group_mode="individual"` keeps the old behaviour for comparison. A unit follows guidance if any member has the app and its fixed draw is under the compliance of the mode. Followers waiting in a queue can leave it and join the back of another when a new plan says so (after 30 s in the queue), and can be redirected to an equivalent destination (another exit).

## 020. Two congestion-aware planners plus an adaptive wrapper (2026-10-24)
`QueueAwarePlanner` (default): method of successive averages on edge cost = travel time + (queue + planned load) / capacity, per destination class, giving a split of each zone's people over exits and parallel thresholds. `FlowPlanner`: time-expanded min-cost flow (OR-Tools) for the earliest time everyone can be out, used for evacuation; it falls back to queue-aware for mixed destinations or step-free needs. `AdaptivePlanner` picks flow in evacuation and queue-aware otherwise. Destinations of kind exit, food, toilets and assembly point are interchangeable within their kind; other destinations are fixed. Objective by mode: evacuation minimises clearance time; egress and normal minimise mean travel time without making p95 worse. The planners see only app users and scale their view up with zone counts, and until sensor fusion exists they are fed ground-truth queues, so results are an upper bound. 

## 021. Planner defaults tuned; scale checked at 50,000 (2026-10-24)
Grid search on generated venues (3 seeds, 3 bottleneck settings, egress and evacuation, 3,000 people, `python -m crowd_sim.tune`): congestion weight 0.25 to 1.0 all land at about 0.95 of baseline, 2.0 is worse (0.96), and 4 vs 8 iterations makes no difference. Defaults are now weight 0.5 and 4 iterations. No setting was worse than baseline on average. Plan time for 50,000 people is 0.12 to 0.23 s for queue-aware, flow and adaptive (budget 2 s), measured with `python -m crowd_sim.scale`. The baseline planner had a quadratic group lookup that made a 50,000-person simulation take over 12 minutes; fixed, the full run takes about 20 s.

## 022. MVP architecture: one process serves the API and the web apps (2026-10-24)
`crowd_server` (FastAPI) holds one `LiveSession`: the simulator stepped in a background thread at an adjustable speed (`advance` on the engine, so the same engine runs batch and live), a lock around every access, and a version counter that WebSocket handlers poll. The same process serves the built web apps from `viz/dist`, so `./run.sh` and the Docker image need only one port. Control-room actions (mode, closures) are injected as events at the next step, the same event types scenarios use. Real users join as "guests": one person added to the simulated crowd who always follows guidance and can change destination. No authentication and one session at a time are deliberate MVP limits.

## 023. The attendee app is a web app (PWA) (2026-10-24)
Opens from a link, installs to the home screen (manifest, icons and a service worker that caches the shell only, never live data), and works on iPhone and Android from one codebase. In the MVP a guest picks their zone from a list because positioning is not built; a user can also follow a simulated person to see what guidance looks like. React Native stays an option for later if native sensors (Bluetooth, background location) are needed.

## 024. Venue editor and the three web apps share one Vite project (2026-10-24)
`viz/` is now a multi-page Vite app: home, control room, attendee app, venue editor and run viewer, sharing the renderer and types. The editor draws zones (rectangle or polygon), gates (dragged along the shared edge of two zones, with the zones found automatically), and places, supports levels, undo and snapping to the grid and to other corners, validates against the server, and saves to `venues/user/` (git-ignored). The editor's exact position for a place is not saved because the schema places a destination in a zone only.

## 025. Several events at once, joined by a short code (2026-10-24)
The server holds a `SessionManager` of independent events, each with its own thread, lock and engine. Attendees join by a 6 character code (no look-alike letters, so no 0/O or 1/I), which doubles as the event id. Limits protect a laptop: 6 events, 120,000 simulated people in total, 300 phones per event. The old single-session endpoints are gone; `/api/join/{code}/...` is public and `/api/sessions/...` is for organisers.

## 026. Accounts for organisers only (2026-10-24)
Organisers sign in (roles `operator` and `viewer`); attendees never do. Passwords are scrypt hashed in `data/users.json`, tokens are HMAC signed with a key in `data/secret.key` and expire after 12 hours, and failed logins are throttled per address. A guest gets a random token when joining, which is the only thing that lets them read or change their own guidance. This is basic protection for a trusted deployment behind HTTPS, not a full identity system (no password reset, no SSO, no audit log). `CROWD_AUTH=off` exists for local demos and tests.

## 027. Real positioning is a filtered zone report (2026-10-24)
A phone sends GPS (or taps the map). The server converts it with the venue anchor (flat-earth approximation, fine at venue scale) and `PositionFilter` turns it into a zone: reject poor accuracy and far-off-venue fixes, require two consecutive fixes and 2 m clearance before changing zone. The engine then treats that person as "external": not moved by the simulation, still counted in occupancy and planning, and arrival is decided by the phone's zone. This keeps the planner unchanged and lets real and simulated people share one crowd. Indoor positioning (levels, Wi-Fi, BLE) is not solved: GPS has no floor, so multi-level zones need the tap fallback or a future indoor source.

## 028. Arrival profiles and more scenarios (2026-10-24)
`crowd.arrival` schedules when each unit appears; groups arrive as one. Nine scenarios now ship, covering entry, egress, a gate failure, closures, low adoption, group meet-ups and a dense stage front. Benchmarks are in `docs/scenarios.md`.

