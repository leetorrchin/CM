# Manual testing guide

How to check the features built so far: venue validation, the baseline planner, the crowd simulator, the venue generator, the emulated sensors and the run viewer. The optimiser exists (see the planner section); there is no phone app or server yet.

Run all commands from the repo root unless a step says otherwise.

## 0. Setup

Install the tools once (macOS):

```
brew install uv node
uv --version
node --version
```

Install project dependencies:

```
uv sync --all-packages
cd viz && npm install && cd ..
```

`uv` creates `.venv` in the repo for the Python packages and `npm` creates `viz/node_modules`. Both are git-ignored. You never need to activate anything: use `uv run ...` for Python.

## 1. Automated tests

```
uv run pytest
cd viz && npm test && cd ..
```

Expected: 110 Python tests pass and 9 viewer tests pass. If a number is different because tests were added since, the important part is that none fail.

## 2. Venue validation

Valid venue:

```
uv run python -m crowd_core.venue venues/example-minimal-festival.json
```

Expected: `venues/example-minimal-festival.json: ok`

Make it fail on purpose:

```
cp venues/example-minimal-festival.json /tmp/bad.json
```

Open `/tmp/bad.json` and change `"to_zone": "main_field"` in the first threshold to `"to_zone": "nowhere"`, then:

```
uv run python -m crowd_core.venue /tmp/bad.json
```

Expected: `INVALID` and a line saying `unknown to_zone 'nowhere'`. Other things to try: delete a zone's `polygon` (schema error), or remove every threshold touching an exit (a zone `cannot reach any safe destination`).

## 3. Simulator runs

Run each scenario. Each takes about 15 seconds at the full 8,000 people.

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/egress-end-of-night.json
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/stage-change.json
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/evacuation-blocked-exit.json
```

Each prints metrics and writes a log to `runs/<scenario>-baseline.jsonl`.

Expected results (the runs are deterministic, so you should get these exact numbers unless the code changed):

| Scenario | arrived_share | travel_time_mean_s | travel_time_p95_s | clearance_s |
|---|---|---|---|---|
| egress-end-of-night | 1.0 | 235.5 | 522.0 | 584.0 |
| stage-change | 1.0 | 140.7 | 243.0 | 350.0 |
| evacuation-blocked-exit | 1.0 | 125.6 | 236.0 | 265.0 |

Also check in every run: `stuck` is 0, and the largest queue in egress is at `t_field_stage` (the stage opening) followed by `t_field_exit_south` (the narrow gate).

Useful options to vary:

| Option | What it checks |
|---|---|
| `--total 2000` | A smaller crowd runs faster and congestion is lighter. |
| `--seed 5` | A different random crowd gives different but similar numbers. The same seed always gives identical output. |
| `--app-adoption 0` | Nobody gets guidance, everyone routes themselves. With the baseline planner the results are about the same, which is expected because the baseline is what people do on their own. |
| `--app-adoption 0.25` | The 25% target. Same reason, little change for the baseline. |
| `--dt 2` | Coarser time step, results should be close. |

Things that should hold:
- Egress cannot finish faster than the time the south gate needs. About 4,000 people at about 7.8 per second is roughly 510 s, so clearance below that would be a bug.
- In the evacuation run, nobody crosses the south exit gate after 300 s (it is closed). You can see this in the viewer, or check the log: after t = 600 s no `zone_state` line has a key containing `t_field_exit_south` under `transit` or `queues`.

## 4. Venue generator

```
uv run python -m crowd_sim.venuegen --seed 7 --stages 4 --entries 4 --exits 4 --food-courts 3 --bottleneck 0.8
```

Expected: it writes `venues/generated/gen-7.json` and three files in `scenarios/generated/gen-7/`.

Validate and run it:

```
uv run python -m crowd_core.venue venues/generated/gen-7.json
uv run python -m crowd_sim.run --venue venues/generated/gen-7.json --scenario scenarios/generated/gen-7/evacuation-blocked-exit.json --out runs/gen-7-evacuation-baseline.jsonl
```

Expected: `ok`, then `arrived_share` 1.0, `stuck` 0, clearance about 529 s.

Things to try:
- Same seed twice gives an identical file (`diff` two outputs).
- `--bottleneck 0` against `--bottleneck 1`: exit 1 gets narrower (4 m at 1). Look at `t_field_exit_1` width in the file and at egress clearance time.
- `--no-grandstands` removes the upper level and the stairs and ramps.
- `--stages 1 --entries 1 --exits 1 --food-courts 1` is the smallest valid venue.
- `--stages 0` should fail with a clear error.

## 5. Emulated sensors

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/egress-end-of-night.json --sensors --out runs/egress-end-of-night-baseline-sensors.jsonl
```

Expected: the metrics now include a `sensors` section. With default settings you should see roughly:
- `cam_stage_a`: `mean_abs_error_share` about 0.1 (10% noise), some `dropped` readings.
- `turnstile_main`: 0 crossings. This is correct, nobody enters during egress.
- `app_position`: `mean_error_m` about 10 and `wrong_zone_share` about 0.05.

Look at the raw readings:

```
grep '"type":"reading"' runs/egress-end-of-night-baseline-sensors.jsonl | head -3
```

Checks:
- The crowd is unchanged by sensors: clearance is still 584.0.
- To change noise, copy a scenario file, add a block like the following, and run it without `--sensors`:

```json
"sensors": {
  "camera": { "rel_sigma": 0.3, "lag_s": 20, "outages": [{ "from_s": 100, "to_s": 300 }] },
  "app_position": { "sigma_m": 40 }
}
```

Expected: camera error rises, no camera readings between 100 s and 300 s, and the wrong-zone share for the app goes up a lot.

## 6. Run viewer

```
cd viz
npm run dev
```

Open http://localhost:5173. You can load files in three ways:
- "Open files" (select a venue `.json` and one or more run `.jsonl`), or drag them onto the page.
- The two dropdowns and "Add run" (picking a run chooses its venue automatically).
- A URL, for example:

```
http://localhost:5173/?venue=example-minimal-festival.json&run=egress-end-of-night-baseline.jsonl
http://localhost:5173/?venue=generated/gen-7.json&run=gen-7-evacuation-baseline.jsonl
http://localhost:5173/?venue=example-minimal-festival.json&run=egress-end-of-night-baseline.jsonl&run2=stage-change-baseline.jsonl
```

Checklist:

| Check | Expected |
|---|---|
| Press Play at 5x | People move: dashed blue lines flow through thresholds, the queue circles grow and shrink, zone colours change. |
| Egress run, around 2:00 | A big orange queue circle at the narrow south gate. |
| Evacuation run, drag past 5:00 | The mode label changes to evacuation, a red cross appears on the south exit gate, a red tick shows on the timeline at 5:00, and flows redirect to the other exits. |
| Hover a zone | A tooltip shows name, people, density against its limit, and area. |
| Level menu: Grandstand deck | Only the upper-level zones are shown. "All" shows everything, upper zones have dashed outlines. |
| Untick "Names" | Zone names disappear, counts stay. |
| Click the chart in the side panel | The timeline jumps to that time. |
| Space bar, left and right arrows | Play and pause, jump 5 s (30 s with Shift). |
| Load two runs | Two maps side by side on one timeline, and a results table with the better value in bold. |
| Click the x on a map | That run is removed. |
| Resize the window | Maps rescale and stay sharp. |
| Switch your system to dark mode | The viewer follows. |
| Load a run before a venue | A message tells you to open the venue file. |
| Load a venue and a run from different venues | A warning appears. |
| Drop a random text file | An error message appears and nothing breaks. |

Note: people crossing a threshold are not counted in any zone, so during heavy movement the zones can show low counts while "Still moving" is high. This is expected.

## 7. Reproducibility check

Run the same command twice with the same seed and compare:

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/egress-end-of-night.json --total 1000 --seed 3 --out /tmp/a.jsonl
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/egress-end-of-night.json --total 1000 --seed 3 --out /tmp/b.jsonl
diff /tmp/a.jsonl /tmp/b.jsonl && echo identical
```

Expected: `identical`. With `--seed 4` they should differ.

## 8. Not built yet

Nothing to test for these: the phone app, the realtime server, the venue editor, sensor fusion, Wi-Fi and BLE sensors, and a live mode in the viewer. 

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv: command not found` | `brew install uv`, then open a new terminal. |
| `node: command not found` | `brew install node`, or `nvm use --lts` if you use nvm. |
| `ModuleNotFoundError: crowd_core` | Run `uv sync --all-packages` and use `uv run ...`. |
| Viewer shows no dropdowns | Use `npm run dev`. A built or file:// copy cannot read the repo folders, use "Open files" instead. |
| Dropdowns are empty | Make sure you ran a scenario first so `runs/` has files, and that you started the viewer from `viz/`. |
| Viewer is blank | Open the browser console. A common cause is a run file from a different venue. |

## Planners (Phase 3)

Compare planners on the same scenario (8,000 people, example venue):

```
uv run python -m crowd_sim.run --venue venues/example-minimal-festival.json --scenario scenarios/egress-end-of-night.json --planner queue-aware
```

Planner choices: `baseline`, `queue-aware`, `flow`, `adaptive`. Expected egress results: baseline clearance 583 s (mean 241 s, p95 529 s); queue-aware about 351 s (168 s, 267 s); flow about 307 s. `groups_split_peak` should be 0 for all. The example-venue evacuation is the same for every planner (265 s) because the closure leaves one way out; on a generated venue (`venues/generated/gen-7.json`) baseline takes about 532 s and the optimisers about 353 s.

Benchmark across generated venues (takes about 2 minutes):

```
uv run python -m crowd_sim.bench --seeds 3 7 11 --total 3000 --out docs/benchmarks.md
```
