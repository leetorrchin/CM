# core/ (crowd_core)

Venue graph compiler (`graph.py`), live state models (`state.py`), planner interface and baseline shortest-path planner (`planner.py`), scenario and venue validation, schema loading. Optimiser and group handling come in Phase 3. No dependency on any other crowD component. Takes a venue, a live state and groups, returns a plan. Deterministic given its inputs.
