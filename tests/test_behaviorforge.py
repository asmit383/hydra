"""BehaviorForge tests — prove the seam produces COHERENT personas, and that this is a
real difference from the guessed independent sampler (the whole point of the rung)."""
from hydra.behaviorforge import PersonaGenerator
from hydra.human import KeystrokeModel, _sample_persona_guessed, sample_persona


def _pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


# ── the headline: BehaviorForge personas are coherent; the guessed ones are not ────────
def test_behaviorforge_personas_are_coherent():
    gen = PersonaGenerator()
    ps = [gen.generate(seed=i) for i in range(300)]
    # a faster typist (low base_ms) has a shorter dwell → POSITIVE correlation
    corr = _pearson([p.base_ms for p in ps], [p.dwell_ms for p in ps])
    assert corr > 0.5                     # coherent: base & dwell move together


def test_guessed_sampler_is_incoherent_by_contrast():
    ps = [_sample_persona_guessed(seed=i) for i in range(300)]
    corr = _pearson([p.base_ms for p in ps], [p.dwell_ms for p in ps])
    assert abs(corr) < 0.2                # independent draws → ~no correlation


# ── the seam: sample_persona routes through the generator, drop-in ─────────────────────
def test_sample_persona_uses_generator_when_given():
    gen = PersonaGenerator()
    viaseam = sample_persona(seed=7, generator=gen)
    direct = gen.generate(seed=7)
    assert (viaseam.base_ms, viaseam.dwell_ms) == (direct.base_ms, direct.dwell_ms)
    # and without a generator it falls back to the guessed sampler (unchanged behavior)
    assert sample_persona(seed=7).base_ms == _sample_persona_guessed(seed=7).base_ms


def test_generated_persona_drives_the_engine():
    # a BehaviorForge persona drops straight into the keystroke model
    p = PersonaGenerator().generate(seed=3)
    plans = KeystrokeModel(p).plan("hello world", allow_errors=False)
    assert plans and all(pl.flight_ms > 0 for pl in plans)


def test_reproducible_and_bounded():
    gen = PersonaGenerator()
    assert gen.generate(seed=5).base_ms == gen.generate(seed=5).base_ms   # reproducible
    assert all(60 <= gen.generate(seed=i).base_ms <= 300 for i in range(50))  # bounded


def test_only_bootstrap_is_built():
    import pytest
    with pytest.raises(NotImplementedError):
        PersonaGenerator(model="bayes-net")
