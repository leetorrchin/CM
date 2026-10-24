# schemas/

Hand-written JSON Schemas (draft 2020-12). This is the source of truth for every message and file that crosses a component boundary. Python validates against them, TypeScript types are generated from them.

| File | Describes |
|---|---|
| `common.schema.json` | Shared types: ids, points, polygons, timestamps, modes |
| `venue.schema.json` | A venue: levels, zones, thresholds, pathways, destinations, sensor sites |
| `entity.schema.json` | A tracked entity and its attributes |
| `position_update.schema.json` | A position report from the app or an emulated person |
| `group.schema.json` | A group of entities that want to stay together |
| `occupancy_reading.schema.json` | One reading from any occupancy source |
| `plan.schema.json` | Guidance output of a planner at a point in time |
| `scenario.schema.json` | A crowd and the timed events that happen to it |
| `event.schema.json` | Envelope for one line of an event log (JSONL) |

Rules: every schema has a `schema_version`; changes that break old files bump it and get an entry in `docs/decisions.md`.
