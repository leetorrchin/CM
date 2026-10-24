import json
import random

import pytest

from crowd_core.scenario import scenario_errors
from crowd_core.venue import validate_venue
from crowd_sim.venuegen import VenueParams, generate_scenarios, generate_venue


def random_params(seed: int) -> VenueParams:
    r = random.Random(seed)
    return VenueParams(seed=seed, stages=r.randint(1, 6), entries=r.randint(1, 6), exits=r.randint(1, 6),
                       food_courts=r.randint(1, 4), grandstands=r.random() < 0.7, bottleneck=r.random())


@pytest.mark.parametrize("seed", range(60))
def test_generated_venues_and_scenarios_are_valid(seed):
    v = generate_venue(random_params(seed))
    assert validate_venue(v) == []
    for sc in generate_scenarios(v, total=500).values():
        assert scenario_errors(sc, v) == []


def test_deterministic_and_seed_changes_layout():
    a = generate_venue(VenueParams(seed=3))
    assert a == generate_venue(VenueParams(seed=3))
    assert json.dumps(a) != json.dumps(generate_venue(VenueParams(seed=4)))


def test_bottleneck_knob_narrows_exit_one():
    wide = generate_venue(VenueParams(seed=1, bottleneck=0.0))
    tight = generate_venue(VenueParams(seed=1, bottleneck=1.0))
    width = lambda v: next(t["width_m"] for t in v["thresholds"] if t["id"] == "t_field_exit_1")  # noqa: E731
    assert width(tight) == 4.0 and width(wide) > 4.0


def test_multi_level_only_with_grandstands():
    assert len(generate_venue(VenueParams(grandstands=True))["levels"]) == 2
    v = generate_venue(VenueParams(grandstands=False))
    assert len(v["levels"]) == 1 and not any(z["level"] == "upper" for z in v["zones"])


def test_bad_params_rejected():
    with pytest.raises(ValueError):
        generate_venue(VenueParams(stages=0))
    with pytest.raises(ValueError):
        generate_venue(VenueParams(bottleneck=2))


@pytest.mark.parametrize("seed", [2, 11, 23])
def test_sim_completes_on_generated_venues(seed):
    from crowd_core.graph import compile_venue
    from crowd_core.planner import BaselinePlanner
    from crowd_sim.engine import Simulation

    v = generate_venue(random_params(seed))
    for sc in generate_scenarios(v, total=400).values():
        m = Simulation(compile_venue(v), sc, BaselinePlanner()).run()
        assert m["arrived_share"] == 1.0 and m["stuck"] == 0, (seed, sc["id"], m)
