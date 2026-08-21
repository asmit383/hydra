"""Pure-model tests for the humanized-input timing science (no browser).

These assert the *correlation structure* a sensor actually scores — not just that
delays exist. They double as the seed of the KS-validation harness: the same
KeystrokeModel that types into a page is exercised here with no page at all.
"""
import math
from pathlib import Path

from hydra.human import (KeystrokeModel, _digraph_mult, _tok, sample_persona)


def _mean(xs):
    return sum(xs) / len(xs)


def _skew(xs):
    m, n = _mean(xs), len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / n) ** 0.5
    return sum(((x - m) / sd) ** 3 for x in xs) / n if sd else 0.0


def _lag1_autocorr(xs):
    m = _mean(xs)
    num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(len(xs) - 1))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else 0.0


# ── 1. digraph latency — timing correlates with the KEY PAIR ───────────────────
def test_digraph_same_finger_slower_than_alternation():
    # "ki" = same finger (right, i-finger); "th" = hand alternation (left→right)
    assert _digraph_mult("k", "i") == 1.6          # same finger — slowest
    assert _digraph_mult("t", "h") == 0.85         # alternation — fastest
    assert _digraph_mult("j", "k") == 1.15         # same hand, different finger
    assert _digraph_mult("k", "i") > _digraph_mult("t", "h")


def test_per_bigram_offsets_distinct_but_stable():
    m = KeystrokeModel(seed=5)
    # two DIFFERENT same-finger bigrams get DISTINCT offsets (individuality, not one bucket)
    assert m._bigram_offset("ed") != m._bigram_offset("lo")
    # ...but each is STABLE within the session (your "ed" is consistently your "ed")
    assert m._bigram_offset("ed") == m._bigram_offset("ed")
    # ...and reproducible across instances of the same seed
    assert KeystrokeModel(seed=5)._bigram_offset("ed") == m._bigram_offset("ed")
    # bounded ±15% so the offset never crosses into another physiology bucket
    assert all(-0.15 <= m._bigram_offset(bg) <= 0.15 for bg in ("th", "ed", "lo", "as"))


def test_digraph_propagates_to_planned_flights():
    # over a long run, same-finger bigrams must average slower than alternating ones
    m = KeystrokeModel(seed=7)
    same = [p.flight_ms for p in m.plan("ki" * 200, allow_errors=False)][2:]
    m = KeystrokeModel(seed=7)
    alt = [p.flight_ms for p in m.plan("th" * 200, allow_errors=False)][2:]
    assert _mean(same) > _mean(alt)


# ── 2. autocorrelated tempo — consecutive keys correlated in speed, not IID ─────
def test_tempo_is_autocorrelated():
    m = KeystrokeModel(seed=3)
    tempo = [m._tempo_step() for _ in range(2000)]
    # OU drift → strong positive lag-1 autocorrelation (IID would be ~0)
    assert _lag1_autocorr(tempo) > 0.5
    assert all(0.6 <= t <= 1.7 for t in tempo)     # bounded


# ── 3. log-normal, not uniform — right-skewed timing ───────────────────────────
def test_flights_are_right_skewed():
    m = KeystrokeModel(seed=11)
    flights = [p.flight_ms for p in m.plan("the quick brown fox jumps over " * 40,
                                           allow_errors=False)]
    assert _skew(flights) > 0.3                     # a right tail, not a flat spread


# ── 4. typos: notice → backspace → retype, and only when allowed ───────────────
def test_typos_produce_backspace_corrections():
    p = sample_persona(seed=1)
    p.error_rate = 0.5                              # force frequent typos
    m = KeystrokeModel(p)
    plans = m.plan("abcdefghij" * 20)
    metas = [pl.meta for pl in plans]
    assert "typo" in metas and "backspace" in metas
    # every backspace is preceded by a typo (a correction, not a random delete)
    for i, meta in enumerate(metas):
        if meta == "backspace":
            assert metas[i - 1] == "typo"


def test_secret_disables_typos():
    p = sample_persona(seed=1)
    p.error_rate = 0.9
    m = KeystrokeModel(p)
    plans = m.plan("hunter2hunter2hunter2", allow_errors=False)
    assert all(pl.meta == "key" for pl in plans)    # no typos in a password field


# ── 5. reproducibility — same seed ⇒ identical plan ────────────────────────────
def test_same_seed_is_reproducible():
    a = [(p.key, round(p.flight_ms, 3)) for p in KeystrokeModel(seed=42).plan("hello world")]
    b = [(p.key, round(p.flight_ms, 3)) for p in KeystrokeModel(seed=42).plan("hello world")]
    assert a == b


# ── 6. key tokens + the fill() guard ───────────────────────────────────────────
def test_tok_maps_special_keys():
    assert _tok(" ") == "Space"
    assert _tok("Backspace") == "Backspace"
    assert _tok("a") == "a"


def test_never_uses_fill():
    src = Path(__file__).resolve().parent.parent / "hydra" / "human.py"
    assert ".fill(" not in src.read_text()          # fill() = zero keystrokes = instant flag
