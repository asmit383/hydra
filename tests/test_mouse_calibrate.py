"""SapiMouse → MouseForge calibration pipeline — tested on SYNTHETIC data in the real format
(timestamp,button,state,x,y), so the extractor is validated without the 120-user download."""
import csv
import json
import math
import random

from hydra.mouse_calibrate import (_RANGES, build_corpus, features, parse_log, persona_from, segment)
from hydra.mouseforge import MouseForge, MousePersona


def _movement_rows(x0, y0, x1, y1, t_start, n=25, dt=0.012, bow=6.0, tremor=0.8, seed=0):
    """SapiMouse-format rows for one humanish move (seconds timestamps) ending in a click."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        f = i / (n - 1)
        x = x0 + (x1 - x0) * f + math.sin(f * math.pi) * bow + rng.gauss(0, tremor)
        y = y0 + (y1 - y0) * f + rng.gauss(0, tremor)
        rows.append((round(t_start + i * dt, 4), "NoButton", "Move", round(x, 1), round(y, 1)))
    rows.append((round(t_start + n * dt, 4), "Left", "Pressed", x1, y1))     # target click
    return rows, t_start + (n + 1) * dt


def _write_sapimouse_csv(path, moves):
    t = 0.0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "button", "state", "x", "y"])
        for (x0, y0, x1, y1, seed) in moves:
            rows, t = _movement_rows(x0, y0, x1, y1, t, seed=seed)
            for r in rows:
                w.writerow(r)


def test_features_are_sane_on_a_synthetic_movement():
    # a 200px move over ~300ms → real speed/curve/tremor, not garbage
    pts = [(i * 12.0, 200 * (i / 24), 0.0 + (5 if i == 12 else 0)) for i in range(25)]
    f = features((pts, True))
    assert f is not None
    assert f["speed"] > 0 and f["curve"] >= 0 and f["tremor"] >= 0
    # tiny jitter (< 40px travel) must be rejected as "not a movement"
    assert features(([(0, 0, 0), (1, 3, 0), (2, 5, 0), (3, 6, 0), (4, 7, 0)], False)) is None


def test_persona_from_clamps_into_the_mousepersona_ranges():
    feats = [{"speed": 99, "curve": 99, "overshoot": 1.0, "tremor": 99, "settle_ms": 9999},
             {"speed": 0, "curve": 0, "overshoot": 0.0, "tremor": 0, "settle_ms": 0}]
    p = persona_from(feats)
    for k, (lo, hi) in _RANGES.items():
        assert lo <= p[k] <= hi                        # every field lands in the valid schema range
    MousePersona(**p)                                  # …and constructs a real MousePersona


def test_end_to_end_parse_segment_and_from_file(tmp_path):
    csv_path = tmp_path / "user_001" / "session1.csv"
    csv_path.parent.mkdir()
    _write_sapimouse_csv(csv_path, [(0, 0, 220, 40, 1), (220, 40, 30, 300, 2),
                                    (30, 300, 400, 120, 3), (400, 120, 60, 60, 4)])

    ev = parse_log(str(csv_path))
    assert ev and ev[-1][0] > 100                      # timestamps normalized seconds → ms
    assert len(segment(ev)) >= 4                        # four clicks → four movements

    corpus = build_corpus(str(tmp_path))               # one persona for the one user folder
    assert len(corpus) == 1 and set(corpus[0]) == set(_RANGES)

    out = tmp_path / "corpus.json"
    out.write_text(json.dumps(corpus))
    mf = MouseForge.from_file(str(out))                # the calibrated corpus loads…
    persona = mf.generate(seed=7)                      # …and drives generation
    assert isinstance(persona, MousePersona) and 0.5 <= persona.speed <= 1.7


def test_mouseforge_auto_loads_calibrated_corpus(tmp_path, monkeypatch):
    corpus = [{"speed": 0.9, "curve": 0.2, "overshoot": 0.1, "tremor": 1.0, "settle_ms": 70},
              {"speed": 1.2, "curve": 0.35, "overshoot": 0.2, "tremor": 1.5, "settle_ms": 110}]
    p = tmp_path / "mc.json"
    p.write_text(json.dumps(corpus))
    monkeypatch.setenv("HYDRA_MOUSE_CORPUS", str(p))
    assert len(MouseForge().corpus) == 2               # running the extractor auto-upgrades sessions
    monkeypatch.setenv("HYDRA_MOUSE_CORPUS", str(tmp_path / "nope.json"))
    assert len(MouseForge().corpus) >= 4               # no corpus → placeholder archetypes fallback
