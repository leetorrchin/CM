# sim/ (crowd_sim)

Emulation (run it with `python -m crowd_sim.run`): simulated clock, emulated people (zone-level flow first), emulated sensors, procedural venue generator, scenario runner, event log writer. Depends only on `core/` and `schemas/`.

Built so far: simulated clock (`clock.py`), event log writer (`eventlog.py`), people spawner with groups, app ownership and speeds (`population.py`), the zone-level engine with queues, compliance, closures, mode changes and metrics (`engine.py`), and the run CLI (`run.py`). Also built: emulated sensors (`sensors.py`: cameras, turnstiles, app position noise) and the procedural venue and scenario generator (`venuegen.py`). Not built yet: Wi-Fi and BLE counters, manual input, a 2D agent mode. Log format: `docs/event-log.md`. Baseline numbers: `docs/baseline-results.md`.

```
# generate a venue and its three scenarios (written to venues/generated and scenarios/generated)
uv run python -m crowd_sim.venuegen --seed 7 --stages 4 --exits 4 --bottleneck 0.8

# run with emulated cameras, turnstiles and app position noise
uv run python -m crowd_sim.run --venue venues/generated/gen-7.json \
  --scenario scenarios/generated/gen-7/evacuation-blocked-exit.json --sensors
```

Sensor settings can also be put in a scenario under `sensors` (see `schemas/scenario.schema.json`). Sensors read the simulation's ground truth and add noise, lag and failures. The defaults in `sensors.py` are placeholders.
