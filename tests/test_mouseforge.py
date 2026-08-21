"""MouseForge tests — the headline is FLEET DIVERSITY: at 10k agents no two may move
alike, or the fleet is mass-blocked. All browser-free (pure trajectory + persona)."""
import math
import random

from hydra.mouseforge import MouseForge, MousePersona, trajectory


def _len(path):
    return sum(math.hypot(path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1])
               for k in range(1, len(path)))


# ── the point of the whole thing: no identical behaviour across the fleet ──────────────
def test_fleet_diversity_no_two_personas_move_alike():
    forge = MouseForge()
    sigs = set()
    for i in range(60):
        mp = forge.generate(seed=i)                       # a distinct session persona
        path = trajectory(mp, 0, 0, 400, 300, random.Random(i))   # OWN rng per session (as real Human)
        pts = [path[k] for k in (0, len(path) // 2, -1)]  # sample the actual path, not a rounded length
        sigs.add(tuple(round(c, 2) for p in pts for c in p[:2]))
    assert len(sigs) >= 58                                # ~all 60 distinct trajectories


def test_personas_are_continuously_sampled_not_a_preset():
    speeds = {round(MouseForge().generate(seed=i).speed, 4) for i in range(40)}
    assert len(speeds) > 30                               # continuous, not a handful of presets


# ── cross-modal coherence: a fast typist mouses fast ───────────────────────────────────
def test_mouse_speed_tracks_typing_speed():
    f = MouseForge()
    fast = sum(f.generate(seed=i, typing_base_ms=90).speed for i in range(30)) / 30
    slow = sum(f.generate(seed=i, typing_base_ms=230).speed for i in range(30)) / 30
    assert fast < slow                                    # lower speed value = faster mouse


# ── trajectory correctness ─────────────────────────────────────────────────────────────
def test_trajectory_ends_at_target():
    mp = MousePersona(speed=1.0, curve=0.3, overshoot=0.0, tremor=0.0, settle_ms=60)
    path = trajectory(mp, 0, 0, 200, 100, random.Random(1))
    assert abs(path[-1][0] - 200) < 1 and abs(path[-1][1] - 100) < 1   # no tremor/overshoot → exact


def test_curve_bows_the_path_beyond_straight_line():
    straight = math.hypot(300, 200)
    mp = MousePersona(speed=1.0, curve=0.4, overshoot=0.0, tremor=0.0, settle_ms=60)
    curved_len = _len(trajectory(mp, 0, 0, 300, 200, random.Random(2)))
    assert curved_len > straight                          # an arc is longer than the chord


def test_reproducible_per_seed():
    a = MouseForge().generate(seed=7)
    b = MouseForge().generate(seed=7)
    assert (a.speed, a.curve, a.tremor) == (b.speed, b.curve, b.tremor)


def test_only_bootstrap_built():
    import pytest
    with pytest.raises(NotImplementedError):
        MouseForge(model="copula")
