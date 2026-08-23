"""MouseForge — coherent, DIVERSE mouse dynamics per session (the mouse BrowserForge).

The scale problem, stated plainly: Camoufox's `humanize` is ONE algorithm — every agent
moves the mouse with the same Bézier signature. At 10k agents that's an identical-behaviour
**fleet signature** → mass block. So mouse dynamics must be **per-session diverse** (and
coherent), exactly like fingerprints and keystroke personas.

MouseForge samples a coherent **mouse persona** per session and **generates the trajectory
itself** — velocity, curvature, overshoot, tremor all come from the persona — so no two
agents move alike, and each is internally plausible.

Same recipe as BehaviorForge: coherent sampling from real data (placeholder archetypes now;
Balabit / SapiMouse mouse-dynamics datasets via `from_file` later). **Cross-modal coherence:**
a fast typist mouses fast — `generate(typing_base_ms=...)` links mouse speed to the keystroke
persona so ONE identity drives both, without needing joint keystroke+mouse data.

NOTE: because MouseForge owns the path, Camoufox's own `humanize` should be OFF for
MouseForge-driven moves (else it re-humanizes each step and re-introduces its fleet-identical
signature). Owning the trajectory is the whole point.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class MousePersona:
    speed: float        # movement-time multiplier (LOWER = faster)
    curve: float        # arc bow magnitude (0 = straight … ~0.4 = very curved)
    overshoot: float    # probability of an overshoot + correction near the target
    tremor: float       # per-step jitter amplitude (px)
    settle_ms: float    # pause on arrival before acting
    seed: int | None = None


# placeholder coherent archetypes — replace with vectors extracted from Balabit / SapiMouse.
_CORPUS = [
    MousePersona(speed=0.80, curve=0.18, overshoot=0.10, tremor=0.8, settle_ms=60),   # fast, direct
    MousePersona(speed=1.00, curve=0.30, overshoot=0.18, tremor=1.2, settle_ms=90),   # average
    MousePersona(speed=1.30, curve=0.40, overshoot=0.12, tremor=1.6, settle_ms=130),  # slow, loopy
    MousePersona(speed=0.90, curve=0.33, overshoot=0.30, tremor=1.4, settle_ms=70),   # quick, overshooty
]


def _load_default_corpus() -> list[MousePersona] | None:
    """A measured corpus if one exists — `HYDRA_MOUSE_CORPUS`, else `data/mouse_corpus.json` (what
    `python -m hydra.mouse_calibrate` writes). None if absent/unreadable → caller falls back."""
    import json
    import os
    path = os.environ.get("HYDRA_MOUSE_CORPUS") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mouse_corpus.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        fields = MousePersona.__dataclass_fields__
        corpus = [MousePersona(**{k: v[k] for k in fields if k in v}) for v in raw]
        return corpus or None
    except Exception:
        return None


class MouseForge:
    """Samples a coherent mouse persona per session. Continuous jitter → fleet diversity;
    each session's seed gives a distinct persona (never a preset a sensor can correlate)."""

    def __init__(self, corpus: list[MousePersona] | None = None, *, model: str = "bootstrap"):
        # calibrated-if-available: prefer a measured corpus (from hydra.mouse_calibrate) when one is
        # present, else the placeholder archetypes. So running the extractor auto-upgrades every
        # session from guessed → measured, no code change.
        self.corpus = corpus or _load_default_corpus() or _CORPUS
        if model != "bootstrap":
            raise NotImplementedError("only 'bootstrap' built; copula/bayes-net = scale-up")

    @classmethod
    def from_file(cls, path: str, **kw) -> "MouseForge":
        """Load a real mouse corpus (Balabit/SapiMouse vectors extracted to JSON)."""
        import json
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        fields = MousePersona.__dataclass_fields__
        return cls([MousePersona(**{k: v[k] for k in fields if k in v}) for v in raw], **kw)

    def generate(self, seed: int | None = None, *, typing_base_ms: float | None = None) -> MousePersona:
        rng = random.Random(seed)
        a = rng.choice(self.corpus)
        jig = rng.gauss(1.0, 0.08)
        # coherence: if the typing speed is known, bias mouse speed to match (fast typist ⇒
        # fast mouse) — one identity across modalities, no joint dataset needed.
        base_speed = _clamp(0.55 + typing_base_ms / 320.0, 0.6, 1.6) if typing_base_ms else a.speed
        return MousePersona(
            speed=_clamp(base_speed * rng.gauss(1.0, 0.06), 0.5, 1.7),
            curve=_clamp(a.curve * jig, 0.05, 0.5),
            overshoot=_clamp(a.overshoot * rng.gauss(1.0, 0.15), 0.02, 0.45),
            tremor=_clamp(a.tremor * rng.gauss(1.0, 0.15), 0.3, 2.5),
            settle_ms=_clamp(a.settle_ms * jig, 30, 180),
            seed=seed,
        )


def _ease(t: float) -> float:
    """Ease-in-out — speed rises then falls, the measured shape of human pointer velocity."""
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def trajectory(mp: MousePersona, x0: float, y0: float, x1: float, y1: float, rng) -> list[tuple]:
    """Humanized path (x0,y0)→(x1,y1) as [(x, y, dt_ms), …]. Sampling (~1 point / 9px, ≤60 pts —
    each point is a CDP round-trip) so the motion is smooth, an ease-in-out velocity profile, a sine-arc bow, and SMALL
    per-sample tremor. Coords are fractional on purpose (integer-only is a tell). Persona
    drives curve/speed/tremor/overshoot → each session moves differently.
    (Follows the measured-input approach of heydryft/human-input's path.ts — dense samples +
    ease + sine bow — instead of a coarse Bézier with invented constants.)"""
    dx, dy = x1 - x0, y1 - y0
    if math.hypot(dx, dy) < 1:
        return [(x1, y1, mp.settle_ms)]
    trem = min(mp.tremor, 1.3)                         # subtle micro-jitter; large = jagged/botistic
    over = rng.random() < mp.overshoot and math.hypot(dx, dy) > 40
    tx, ty = (x1, y1)
    if over:                                           # aim slightly PAST, then correct back
        d = math.hypot(dx, dy)
        tx, ty = x1 + dx / d * rng.uniform(5, 14), y1 + dy / d * rng.uniform(5, 14)

    pts: list[tuple] = []

    def seg(ax, ay, bx, by):
        sdx, sdy = bx - ax, by - ay
        sd = math.hypot(sdx, sdy) or 1.0
        nx, ny = -sdy / sd, sdx / sd                   # perpendicular → bow direction
        bow = (rng.random() - 0.5) * min(80.0, sd * mp.curve)
        # Each point is a `page.mouse.move` = one CDP round-trip, so point COUNT (not px density)
        # sets wall-clock. ~1 sample/9px, capped at 60, keeps the path smooth (below frame rate)
        # while cutting IPC ~3× — the old sd/4 (up to 200 pts) is what made moves feel sluggish.
        steps = max(8, min(60, round(sd / 9)))
        dt = (mp.speed * (50 + sd * 0.34) * rng.uniform(0.9, 1.1)) / steps
        for i in range(1, steps + 1):
            t = i / steps
            e = _ease(t)
            arc = math.sin(t * math.pi) * bow          # 0 at both ends, max in the middle
            pts.append((ax + sdx * e + nx * arc + rng.gauss(0, trem),
                        ay + sdy * e + ny * arc + rng.gauss(0, trem), dt))

    seg(x0, y0, tx, ty)
    if over:
        seg(tx, ty, x1, y1)                            # smooth correction back to the target
    return pts


__all__ = ["MousePersona", "MouseForge", "trajectory"]
