# Architecture and repo structure

```
crowD/
  README.md  PLAN.md  pyproject.toml  .gitignore
  schemas/      JSON Schemas, the contract between components
  venues/       venue files (examples, fixtures)
  scenarios/    scenario files for the simulator
  core/         crowd_core: graph, planners, groups, validation
    src/crowd_core/
    tests/
  sim/          crowd_sim: emulated people, venues, sensors, clock, runner
    src/crowd_sim/
    tests/
  connectors/   crowd_connectors: occupancy adapters and fusion
    src/crowd_connectors/
    tests/
  server/       crowd_server: realtime and operator API
    src/crowd_server/
    tests/
  viz/          visualiser (TypeScript)
  editor/       venue editor (TypeScript)
  app/          entity app (React Native)
  runs/         generated event logs (git-ignored)
  docs/         architecture, decisions
```

## Dependency rules

```
schemas  <--  core  <--  sim
                  \<--  connectors  <--  server (also uses core)
schemas  <--  viz, editor, app   (TypeScript, via generated types)
```

- `core` imports nothing from the repo except `schemas/` files.
- `sim` and `connectors` import `core` only. They never import each other.
- `server` imports `core` and `connectors`. It never imports `sim`. A simulator drives the server over the same protocol as the app.
- `viz`, `editor` and `app` never import Python code. They consume schemas and event logs.
- Cross-component data is always a message that validates against `schemas/`.

## Tooling

- Python: `uv` workspace, `pytest`, `ruff`.
- TypeScript: `npm`, Vite for `viz/` and `editor/`, Expo for `app/`.
- Types for TypeScript are hand-written in `viz/src/types.ts` for now and will be generated from `schemas/` later.
- `viz/` dev server (`npm run dev`) serves `venues/`, `runs/` and `scenarios/` read-only at `/data`.
- Install node packages on your own machine (`npm install` in `viz/`). `node_modules/` is git-ignored.
