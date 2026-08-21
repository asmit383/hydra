"""BehaviorForge — a persona generator, the behavioral analog of BrowserForge (v0.1).

BrowserForge samples a *coherent* fingerprint from a Bayesian network Apify trained on
real device data (`FingerprintGenerator(browser='firefox')` → the ~689KB Apify network).
BehaviorForge is the same recipe, one layer over: sample a *coherent* PERSONA (motor
params) from real human data, so the persona's fields fit together like a real person
(fast typist ⇒ fast dwell ⇒ fast mouse) instead of being drawn independently from guessed
ranges.

The seam is one function: `human.sample_persona(seed, generator=<PersonaGenerator>)`. The
whole engine downstream (`KeystrokeModel`, `Human`) consumes a `Persona` and never sees
which path made it — so this drops in without touching anything else.

    ┌──────────────┬────────────────────────┬──────────────────┬────────────────────────┐
    │ BrowserForge │ Apify corpus           │ Bayesian network │ FingerprintGenerator   │
    │ BehaviorForge│ human keystroke corpus │ joint model      │ PersonaGenerator       │
    └──────────────┴────────────────────────┴──────────────────┴────────────────────────┘

── HONEST STATE (v0.1) ────────────────────────────────────────────────────────────────
This is the SEAM with a **placeholder corpus** — a handful of hand-authored, *internally
coherent* archetypes (skilled / average / slow / fast-sloppy / hunt-and-peck). It already
does the important thing: every persona is a coherent bundle + coherent jitter, NOT
independent draws — so it fixes the incoherence bug today. What it is NOT yet:
  • real data — replace the placeholder corpus with vectors EXTRACTED from a real dataset
    (Aalto 136M-keystroke, Clarkson, Buffalo). That's ~80% of the real work (a data job).
  • diverse — 5 archetypes + jitter is low diversity; a real corpus gives thousands.
  • layout/device-conditioned — `locale`/`device` are accepted but not yet used to pick a
    digraph table / touch model. Stubbed, marked below.
The `model="bootstrap"` path (resample a real vector + coherent jitter) is the MVP; a
Gaussian copula / Bayesian net over real vectors is the scale-up (unlimited diversity).
"""
from __future__ import annotations

import random

from hydra.human import Persona, _clamp

# ── placeholder corpus: coherent archetypes (each field bundle fits ONE real-ish person).
# Replace with vectors extracted from a real keystroke dataset — same Persona shape.
# Coherence baked in: faster base ⇒ shorter dwell/think; skill ⇒ lower variance + lower
# error; hunt-and-peck ⇒ slow + high think + careful (low error) + high variance.
_CORPUS: list[Persona] = [
    # skilled touch-typist — fast, consistent, few errors
    Persona(base_ms=95,  flight_sigma=0.20, dwell_ms=70,  dwell_sigma=0.16,
            error_rate=0.008, tempo_theta=0.12, tempo_sigma=0.04,
            think_ms=180, shift_ms=40,  mouse_settle=0.05),
    # average office typist
    Persona(base_ms=140, flight_sigma=0.27, dwell_ms=85,  dwell_sigma=0.20,
            error_rate=0.015, tempo_theta=0.10, tempo_sigma=0.06,
            think_ms=280, shift_ms=55,  mouse_settle=0.08),
    # slow + deliberate
    Persona(base_ms=200, flight_sigma=0.30, dwell_ms=100, dwell_sigma=0.22,
            error_rate=0.010, tempo_theta=0.08, tempo_sigma=0.06,
            think_ms=420, shift_ms=80,  mouse_settle=0.10),
    # fast but sloppy — quick, high variance, more typos
    Persona(base_ms=105, flight_sigma=0.33, dwell_ms=65,  dwell_sigma=0.24,
            error_rate=0.028, tempo_theta=0.09, tempo_sigma=0.08,
            think_ms=160, shift_ms=45,  mouse_settle=0.06),
    # hunt-and-peck — slow, careful, long thinks, high variance
    Persona(base_ms=260, flight_sigma=0.38, dwell_ms=110, dwell_sigma=0.26,
            error_rate=0.006, tempo_theta=0.06, tempo_sigma=0.09,
            think_ms=520, shift_ms=100, mouse_settle=0.11),
]


class PersonaGenerator:
    """Draw a coherent persona from a corpus. Mirrors BrowserForge's FingerprintGenerator:
    conditions (locale/device) in, one coherent sample out."""

    def __init__(self, corpus: list[Persona] | None = None, *, model: str = "bootstrap",
                 locale: str = "en-US", device: str = "desktop"):
        self.corpus = corpus or _CORPUS
        self.model = model
        self.locale = locale      # STUB: not yet used to pick a digraph table
        self.device = device      # STUB: desktop only (no touch model yet)
        if model != "bootstrap":
            raise NotImplementedError(
                f"model={model!r}: only 'bootstrap' is built; copula/bayes-net = scale-up")

    @classmethod
    def from_file(cls, path: str, **kw) -> "PersonaGenerator":
        """Load a real corpus (extracted by `hydra.corpus`) instead of the placeholder."""
        from hydra.corpus import load_corpus
        return cls(load_corpus(path), **kw)

    def generate(self, seed: int | None = None) -> Persona:
        """One coherent persona: bootstrap a real vector, then apply COHERENT jitter — a
        single shared speed factor moves the timing fields together (so a faster draw is
        faster *everywhere*, preserving the correlations), plus tiny per-field noise. This
        is the whole point: the jitter never breaks the bundle's coherence."""
        rng = random.Random(seed)
        a = rng.choice(self.corpus)                 # bootstrap: resample a real-ish person
        speed = rng.gauss(1.0, 0.05)                # shared tempo → keeps timings coherent
        return Persona(
            base_ms=_clamp(a.base_ms * speed * rng.gauss(1, 0.02), 60, 320),
            dwell_ms=_clamp(a.dwell_ms * speed * rng.gauss(1, 0.02), 40, 170),
            think_ms=_clamp(a.think_ms * speed * rng.gauss(1, 0.03), 100, 650),
            mouse_settle=_clamp(a.mouse_settle * speed, 0.03, 0.16),
            shift_ms=_clamp(a.shift_ms * rng.gauss(1, 0.05), 25, 120),
            # widened to the real Aalto range (old caps pinned err/sigma → fleet-diversity leak)
            flight_sigma=_clamp(a.flight_sigma * rng.gauss(1, 0.05), 0.15, 0.70),
            dwell_sigma=_clamp(a.dwell_sigma * rng.gauss(1, 0.05), 0.12, 0.45),
            error_rate=_clamp(a.error_rate * rng.gauss(1, 0.10), 0.002, 0.13),
            tempo_theta=a.tempo_theta,
            tempo_sigma=a.tempo_sigma,
            seed=seed,
        )


__all__ = ["PersonaGenerator"]
