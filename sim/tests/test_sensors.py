import json
from pathlib import Path

from crowd_sim.run import run_scenario

ROOT = Path(__file__).resolve().parents[2]
VENUE = ROOT / "venues" / "example-minimal-festival.json"
EGRESS = ROOT / "scenarios" / "egress-end-of-night.json"


def lines(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines()]


def run(tmp_path, cfg, total=1500, scenario=EGRESS, **kw):
    out = tmp_path / "r.jsonl"
    m = run_scenario(VENUE, scenario, out=out, total=total, sensors=cfg, validate_log=True, **kw)
    return m, lines(out)


def test_no_sensors_by_default(tmp_path):
    m, recs = run(tmp_path, None)
    assert "sensors" not in m and not any(r["type"] == "reading" for r in recs)


def test_default_sensors_emit_valid_readings(tmp_path):
    m, recs = run(tmp_path, True)
    kinds = {r["data"]["source_type"] for r in recs if r["type"] == "reading"}
    assert kinds == {"camera", "turnstile"}
    assert set(m["sensors"]) == {"cam_stage_a", "turnstile_main", "app_position"}


def test_sensors_do_not_change_the_crowd(tmp_path):
    base = run_scenario(VENUE, EGRESS, total=1000)
    with_s = run_scenario(VENUE, EGRESS, total=1000, sensors=True)
    for k in ("travel_time_mean_s", "travel_time_p95_s", "clearance_s", "arrived_share"):
        assert base[k] == with_s[k]


def test_camera_error_follows_sigma(tmp_path):
    exact = {"camera": {"rel_sigma": 0.0, "bias": 0.0, "lag_s": 0.0}}
    noisy = {"camera": {"rel_sigma": 0.3, "bias": 0.0, "lag_s": 0.0}}
    e0, _ = run(tmp_path, exact)
    e1, _ = run(tmp_path, noisy)
    assert e0["sensors"]["cam_stage_a"]["mean_abs_error_share"] == 0.0
    assert e1["sensors"]["cam_stage_a"]["mean_abs_error_share"] > 0.1


def test_camera_lag_adds_error_while_crowd_moves(tmp_path):
    fresh, _ = run(tmp_path, {"camera": {"rel_sigma": 0.0, "lag_s": 0.0}})
    stale, _ = run(tmp_path, {"camera": {"rel_sigma": 0.0, "lag_s": 20.0}})
    assert stale["sensors"]["cam_stage_a"]["mean_abs_error_share"] > 0.0


def test_camera_outage_and_dropout(tmp_path):
    cfg = {"camera": {"outages": [{"from_s": 0, "to_s": 100000}]}}
    m, recs = run(tmp_path, cfg)
    assert not any(r["type"] == "reading" for r in recs) and m["sensors"]["cam_stage_a"]["dropped"] > 0
    m, recs = run(tmp_path, {"camera": {"dropout_prob": 1.0}})
    assert not any(r["type"] == "reading" for r in recs)


def test_turnstile_counts_track_truth(tmp_path):
    m, _ = run(tmp_path, {"turnstile": {"miss_rate": 0.0}})
    s = m["sensors"]["turnstile_main"]
    assert s["count_error_share"] == 0.0
    m, _ = run(tmp_path, {"turnstile": {"miss_rate": 0.2}})
    s = m["sensors"]["turnstile_main"]
    assert s["counted_crossings"] <= s["true_crossings"]


def test_app_position_error_grows_with_sigma(tmp_path):
    small, _ = run(tmp_path, {"app_position": {"sigma_m": 1.0, "dropout_prob": 0.0}})
    big, _ = run(tmp_path, {"app_position": {"sigma_m": 40.0, "dropout_prob": 0.0}})
    a, b = small["sensors"]["app_position"], big["sensors"]["app_position"]
    assert a["wrong_zone_share"] < b["wrong_zone_share"]
    assert a["mean_error_m"] < b["mean_error_m"]


def test_position_updates_logged_only_when_asked(tmp_path):
    _, recs = run(tmp_path, {"app_position": {"sample_size": 5}})
    assert not any(r["type"] == "position_update" for r in recs)
    _, recs = run(tmp_path, {"app_position": {"sample_size": 5, "emit_updates": True}})
    assert any(r["type"] == "position_update" for r in recs)


def test_scenario_can_carry_sensor_config(tmp_path):
    sc = json.loads(EGRESS.read_text())
    sc["sensors"] = {"turnstile": {"miss_rate": 0.05}}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(sc))
    m, _ = run(tmp_path, None, scenario=p)
    assert set(m["sensors"]) == {"turnstile_main"}


def test_deterministic_with_sensors():
    a = run_scenario(VENUE, EGRESS, total=800, sensors=True, seed=3)
    b = run_scenario(VENUE, EGRESS, total=800, sensors=True, seed=3)
    assert a == b
