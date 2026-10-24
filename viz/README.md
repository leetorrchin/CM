# viz/

Run viewer (TypeScript, Vite, Canvas 2D). Plays back an event log (`runs/*.jsonl`) on a venue (`venues/*.json`): zone density heatmap, queues at thresholds, people crossing thresholds, closures, a timeline with event ticks, and a chart of people still moving and waiting. Add two runs of the same venue to compare them side by side with shared time and a final-results table that highlights the better value.

```
cd viz
npm install
npm run dev
```

Open http://localhost:5173 and either use "Open files" (or drop files on the page), or load from the repo with the dropdowns, or use a URL such as:

http://localhost:5173/?venue=example-minimal-festival.json&run=egress-end-of-night-baseline.jsonl&run2=stage-change-baseline.jsonl

The dev server exposes `venues/`, `runs/` and `scenarios/` at `/data` for this. Keys: space plays and pauses, left and right arrows step 5 s (hold shift for 30 s). Hover a zone for details. Use the level selector for multi-level venues (dashed outlines are upper levels).

```
npm test        unit tests (loader, interpolation, geometry)
npm run build   typecheck and production build into dist/
```

Depends only on the JSON schemas and the event log format (`docs/event-log.md`), never on Python code. Types in `src/types.ts` are hand-written for now and will be generated from `schemas/` later. Live WebSocket mode comes with the server.
