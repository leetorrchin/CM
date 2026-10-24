# Server API

`python -m crowd_server` (or `./run.sh`) serves the web apps at `/` and this API under `/api` and `/ws`. Interactive docs: http://localhost:8000/docs.

There is one live session at a time. It runs a simulated crowd on the chosen venue, steps it at an adjustable speed, and shares the state with every client. No authentication: run it on a trusted network.

## Catalog

| Method and path | What it does |
|---|---|
| `GET /api/health` | `{ok, session}`; `session` is the latest summary or null |
| `GET /api/venues` | Venues: `[{id, name, source}]`, source is `example`, `generated` or `user` |
| `GET /api/venues/{id}` | One venue (`venue.schema.json`) |
| `POST /api/venues/validate` | Body: a venue. Returns `{errors: []}` |
| `POST /api/venues` | Validate and save to `venues/user/{id}.json`. 422 with `{errors}` if invalid |
| `GET /api/scenarios?venue=id` | Scenario names for a venue. `auto-egress` works for any venue |
| `GET /api/planners` | `baseline`, `queue-aware`, `flow`, `adaptive` |

## Session control

| Method and path | Body | What it does |
|---|---|---|
| `POST /api/session` | `{venue, scenario, planner, total?, speed?, app_adoption?}` | Start a new session, replacing the current one |
| `POST /api/session/restart` | `{}` | Restart with the same settings (keeps the speed) |
| `GET /api/session` | | Latest summary (no per-zone counts) |
| `POST /api/session/speed` | `{speed}` | Simulated seconds per real second, up to 120 |
| `POST /api/session/pause` | `{paused}` | Pause or resume |
| `POST /api/control/mode` | `{mode, destination?}` | `normal`, `egress` or `evacuation`. Evacuation defaults to `nearest_safe` |
| `POST /api/control/closure` | `{threshold, closed}` | Close or reopen a gate. 422 if it is unknown or not closable |

## Attendees

| Method and path | What it does |
|---|---|
| `GET /api/people?limit=8` | App users in the crowd that a demo phone can follow: `[{id, group_size, zone}]` |
| `POST /api/guest` | `{zone, destination}` adds a real user to the crowd. Returns `{person_id}` (ids start with `guest-`) |
| `POST /api/guidance/{id}/destination` | `{destination}` changes where a guest wants to go (guests only) |
| `GET /api/guidance/{id}` | What the phone shows now: state, zone, next gate, destination, queue ahead, group size, closed gates |

## WebSockets

- `/ws/live`: the latest state about twice a second: `{type: "state", t_s, mode, zones, transit, queues, cleared, active, closed, planner, speed, paused, people, scenario, venue, queue_switches, redirected}`. Edge keys in `transit` and `queues` look like `threshold_id:from_zone->to_zone`, as in the event log.
- `/ws/guide/{id}`: the guidance object for one person, once a second.

Clients reconnect on their own. If the session is replaced, `/ws/live` switches to the new one.

## Settings

Environment variables: `CROWD_VENUE`, `CROWD_SCENARIO`, `CROWD_TOTAL`, `CROWD_SPEED` and `CROWD_AUTOSTART=0` control the session started at boot; `CROWD_STATIC` and `CROWD_ROOT` move the web build and data folders.
