# Server API

`python -m crowd_server` (or `./run.sh`) serves the web apps at `/` and this API under `/api` and `/ws`. Interactive docs: http://localhost:8000/docs.

The server runs several **events** (sessions) at once. Each event is a simulated crowd on a venue, stepped at an adjustable speed, with a short **join code** (for example `K7QD2X`). Organisers sign in to manage events. Attendees need no account: they join with the code.

## Sign in and roles

Sign in is on by default. `CROWD_AUTH=off` turns it off (everyone is an operator; for local demos and tests).

- Roles: `operator` (create, change and stop events, edit venues) and `viewer` (watch only).
- `POST /api/login` with `{username, password}` returns `{token, user, role, exp}`. Send `Authorization: Bearer <token>` on organiser calls. WebSockets take `?token=`. Tokens expire after 12 hours (`CROWD_TOKEN_TTL_S`).
- 5 wrong passwords from one address in 5 minutes block further tries for a while (HTTP 429).
- First start with no users: an `admin` operator is created. The password is `CROWD_ADMIN_PASSWORD` if set, otherwise a random one printed once in the server log. Accounts live in `data/users.json` (scrypt hashes, `CROWD_DATA` moves the folder).
- Manage accounts: `python -m crowd_server.auth add NAME [--role viewer]`, `remove NAME`, `list`.
- `GET /api/me` returns the signed-in user.

## Catalog (viewer and up)

| Method and path | What it does |
|---|---|
| `GET /api/health` | Public. `{ok, version, auth, sessions, needs_setup}` |
| `GET /api/venues` | Venues: `[{id, name, source}]`, source is `example`, `generated` or `user` |
| `GET /api/venues/{id}` | One venue (`venue.schema.json`) |
| `POST /api/venues/validate` | Operator. Body: a venue. Returns `{errors: []}` |
| `POST /api/venues` | Operator. Validate and save to `venues/user/{id}.json`. 422 with `{errors}` if invalid |
| `GET /api/scenarios?venue=id` | Scenario names for a venue. `auto-egress` works for any venue |
| `GET /api/planners` | `baseline`, `queue-aware`, `flow`, `adaptive` |

## Events (organisers)

| Method and path | Role | What it does |
|---|---|---|
| `GET /api/sessions` | viewer | All running events (summary, no per-zone counts) |
| `POST /api/sessions` | operator | Start one. Body: `{venue, scenario, planner, total?, speed?, app_adoption?, name?, code?, demo_people?, record?}`. `code` is 4 to 12 letters or digits, otherwise one is generated. `demo_people` lets phones follow simulated people. `record` writes the event log to `runs/`. 409 if a limit is hit or the code is taken |
| `GET /api/sessions/{id}` | viewer | One summary |
| `DELETE /api/sessions/{id}` | operator | Stop and remove it |
| `POST /api/sessions/{id}/restart` | operator | Same settings, fresh crowd, same code |
| `POST /api/sessions/{id}/speed` | operator | `{speed}`: simulated seconds per real second, up to 120 |
| `POST /api/sessions/{id}/pause` | operator | `{paused}` |
| `POST /api/sessions/{id}/mode` | operator | `{mode, destination?}`: `normal`, `egress` or `evacuation` (defaults to `nearest_safe`) |
| `POST /api/sessions/{id}/closure` | operator | `{threshold, closed}`. 422 if unknown or not closable |
| `GET /api/sessions/{id}/venue` | viewer | The venue the event uses |
| `GET /api/sessions/{id}/guests` | viewer | Phones that joined: `[{person_id, zone, external, ...}]` |
| `WS /ws/sessions/{id}?token=` | viewer | The latest state about twice a second (see below) |

Limits (environment): `CROWD_MAX_SESSIONS` (default 6), `CROWD_MAX_PEOPLE` simulated people across all events (default 120,000). At most 300 phones per event.

## Attendees (public, by join code)

| Method and path | What it does |
|---|---|
| `GET /api/join/{code}` | Event info: name, venue, mode, `demo_people`, `has_anchor` (GPS usable), zones and places to pick from |
| `GET /api/join/{code}/venue` | The venue for drawing the map |
| `GET /api/join/{code}/people?limit=8` | Simulated people a demo phone can follow (403 unless `demo_people`) |
| `POST /api/join/{code}/guest` | `{zone, destination?, external?}` adds a real user to the crowd. Returns `{person_id, token}`; send the token as `X-Guest-Token` on later calls |
| `GET /api/join/{code}/guest/{id}/guidance` | What the phone shows now: state, zone, next gate, destination, queue ahead, group size, closed gates |
| `POST /api/join/{code}/guest/{id}/destination` | `{destination}` |
| `POST /api/join/{code}/guest/{id}/position` | Report where the phone is: `{lat, lon, accuracy_m?}` (needs a venue anchor) or `{x, y}` in venue metres. Returns `{status, zone, x, y, off_venue_m}` |
| `POST /api/join/{code}/guest/{id}/mode` | `{external}`: true uses the phone's reported position, false goes back to simulated movement |
| `DELETE /api/join/{code}/guest/{id}` | Leave the event |
| `WS /ws/join/{code}/live` | Same state feed as the organiser one, for drawing the map |
| `WS /ws/join/{code}/guide/{id}?token=` | The guidance object, once a second |

Followed simulated people (`person ids p00123`) need no token but only work when `demo_people` is on.

## Real positioning

A venue can carry `anchor: {lat, lon, rotation_deg}`: the real-world point of local (0, 0) and how far the y axis is turned clockwise from north. The server converts GPS fixes to venue metres and then to a zone with these rules:

- fixes with accuracy worse than 50 m are ignored (`status: inaccurate`);
- fixes more than 80 m outside the venue are ignored (`off_venue`);
- a zone change needs 2 fixes in a row and 2 m of clearance from the border, so a phone near a gate does not flicker;
- the first fix is accepted straight away.

Once a phone reports, that person is "external": the simulation stops moving them and takes their zone from the phone. They still count in the zone totals and in the planner. They can switch back to simulated movement.

## State feed

`{type: "state", id, name, t_s, mode, zones, transit, queues, cleared, active, closed, groups_split, planner, speed, paused, people, scenario, venue, queue_switches, redirected, guests, demo_people, recording}`. Edge keys in `transit` and `queues` look like `threshold_id:from_zone->to_zone`, as in the event log. Clients reconnect on their own. A `{type: "ended"}` message arrives when the event is stopped. Close code 4401 means sign in again.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CROWD_AUTH` | on | `off` disables sign in |
| `CROWD_ADMIN_USER`, `CROWD_ADMIN_PASSWORD` | `admin`, random | First-start operator account |
| `CROWD_DATA` | `data/` | Users and signing key |
| `CROWD_MAX_SESSIONS`, `CROWD_MAX_PEOPLE` | 6, 120000 | Limits |
| `CROWD_TOKEN_TTL_S` | 43200 | Login lifetime |
| `CROWD_AUTOSTART` | on | Start a demo event at boot |
| `CROWD_VENUE`, `CROWD_SCENARIO`, `CROWD_TOTAL`, `CROWD_SPEED`, `CROWD_DEMO_CODE` | example venue, egress-end-of-night, 3000, 5, `DEMO` | The demo event |
| `CROWD_STATIC`, `CROWD_ROOT` | | Move the web build and data folders |

Use HTTPS in front of the server for anything outside a trusted network (phones only share GPS on HTTPS or localhost).
