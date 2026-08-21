"""Humanized input — the behavioral layer Camoufox doesn't own (v0.1).

Camoufox spoofs the *fingerprint* (layers 1-2); it does NOT make your *behavior*
human. Its `humanize` gives a Bézier mouse PATH, but a behavioral sensor
(PerimeterX/DataDome) scores TIMING and its CORRELATIONS over the session. This
module fills that gap: realistic keystroke timing + humanized clicks.

The design principle that makes it robust (not just "random delays"):
**sensors score the CORRELATION STRUCTURE, not the marginal histogram.** So we
reproduce the correlations a real typist has, not just a nice per-key spread:

  1. digraph latency   — flight time depends on the KEY PAIR (same-finger slow,
                         hand-alternation fast), so timing correlates with what's typed.
  2. autocorrelated    — a slowly-drifting tempo (Ornstein-Uhlenbeck), so consecutive
     tempo             keys are correlated in speed, not IID (IID = zero autocorrelation
                         = a giveaway to any sensor reading the time series).
  3. log-normal        — right-skewed timings, never uniform (uniform is as detectable
                         as a constant — the "excessive variance" anti-pattern).
  4. boundary pauses   — longer gaps at word boundaries and before shifted keys.
  5. per-session       — ONE Persona drives typing AND mouse speed AND dwell, so the
     PERSONA            signals stay mutually coherent (fast typist ⇒ fast everything).
                         Incoherence across signals is what sensors actually catch.

The honest ceiling: behavior is NECESSARY, NOT SUFFICIENT — a sensor fuses it with
IP + fingerprint + challenge, and runs server-side ML you can't see. The defensible
claim is "statistically indistinguishable from human on the features I can measure",
never "beats the sensor". Validate with a KS-test vs a real-human baseline.

Structure (built for the SDK/MCP layers on top):
  KeystrokeModel — PURE timing (no browser) → unit-tested + used by the KS harness.
  Human(page, …) — the DRIVER: executes a plan on a Playwright page (engine-agnostic;
                   only the `page` API, so it ports to Chromium and wraps as an MCP tool).
The session holds one Human; SDK `h.type(...)` and MCP `hydra_type` call the same thing.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

# ── QWERTY hand/finger map (US layout) — the basis of digraph latency ──────────
# finger id: 0-4 left (pinky→index), 5-9 right (index→pinky). hand = id < 5.
_ROWS = {
    "1qaz": 0, "2wsx": 1, "3edc": 2, "4rfv5tgb": 3,           # left  pinky→index
    "6yhn7ujm": 6, "8ik,": 7, "9ol.": 8, "0p;/-=[]'": 9,      # right index→pinky
}
_FINGER: dict[str, int] = {c: fid for keys, fid in _ROWS.items() for c in keys}


def _finger(ch: str) -> int | None:
    """Finger id for a character (lowercased), or None for space/unknown."""
    return _FINGER.get((ch or "").lower())


def _digraph_mult(prev: str, cur: str) -> float:
    """Flight-time multiplier for a key pair — the core human correlation.
    same finger → slow (you can't move one finger twice instantly); same hand →
    medium; opposite hands → fast (the fingers move in parallel)."""
    a, b = _finger(prev), _finger(cur)
    if a is None or b is None:
        return 1.0
    if a == b:
        return 1.6                       # same finger — the slowest transition
    if (a < 5) == (b < 5):
        return 1.15                      # same hand, different finger
    return 0.85                          # hand alternation — the fastest


_SHIFT_SYMBOLS = set('~!@#$%^&*()_+{}|:"<>?')


def _needs_shift(ch: str) -> bool:
    return ch.isupper() or ch in _SHIFT_SYMBOLS


# Playwright key tokens for the non-literal keys.
_TOK = {" ": "Space", "\n": "Enter", "\t": "Tab"}


def _tok(key: str) -> str:
    """Map a plan key to a Playwright keyboard token ('Backspace' passes through;
    a space becomes 'Space'; a printable char stays itself)."""
    return _TOK.get(key, key)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ── Persona — the per-session coherence unit (sampled ONCE) ────────────────────
@dataclass
class Persona:
    """One synthetic typist. Sampled once per session; drives EVERY behavior so the
    signals stay mutually coherent (the cross-signal check sensors run)."""
    base_ms: float       # median inter-key flight for a neutral digraph
    flight_sigma: float  # log-normal spread of flight (the skew)
    dwell_ms: float      # median key hold (press→release)
    dwell_sigma: float
    error_rate: float    # per-key typo probability (visible fields only)
    tempo_theta: float   # OU mean-reversion (how fast tempo returns to 1.0)
    tempo_sigma: float   # OU volatility (how much tempo wanders)
    think_ms: float      # median "read the field / new word" pause
    shift_ms: float      # extra reach time for a shifted key
    mouse_settle: float  # seconds to settle on a target before clicking
    seed: int | None = None


def _sample_persona_guessed(seed: int | None = None) -> Persona:
    """FALLBACK: draw a persona from GUESSED, INDEPENDENT ranges — each field sampled
    alone, so it *can* produce incoherent corners (fast flight + slow dwell). Fine as a
    default; the coherent version is BehaviorForge's joint sampler (see behaviorforge.py).
    Same seed → same persona (reproducible)."""
    rng = random.Random(seed)
    return Persona(
        base_ms=_clamp(rng.gauss(135, 35), 75, 240),
        flight_sigma=rng.uniform(0.22, 0.34),
        dwell_ms=_clamp(rng.gauss(85, 18), 45, 130),
        dwell_sigma=rng.uniform(0.15, 0.28),
        error_rate=rng.uniform(0.004, 0.03),
        tempo_theta=rng.uniform(0.05, 0.15),
        tempo_sigma=rng.uniform(0.04, 0.09),
        think_ms=_clamp(rng.gauss(280, 90), 120, 600),
        shift_ms=_clamp(rng.gauss(55, 15), 25, 110),
        mouse_settle=rng.uniform(0.04, 0.12),
        seed=seed,
    )


def sample_persona(seed: int | None = None, generator=None) -> Persona:
    """Born a persona. With a BehaviorForge `generator` → measured + joint (coherent by
    construction). Without → the guessed independent fallback. Drop-in: everything
    downstream consumes a `Persona` and never sees which path made it."""
    if generator is not None:
        return generator.generate(seed)
    return _sample_persona_guessed(seed)


@dataclass
class KeyPlan:
    """One keyboard action: pause `flight_ms` (before), then hold the key `dwell_ms`."""
    key: str             # a character, or a Playwright key name ('Backspace')
    flight_ms: float
    dwell_ms: float
    meta: str = "key"    # "key" | "typo" | "backspace" — for the trace/validation


# ── KeystrokeModel — PURE timing science (no browser) ──────────────────────────
class KeystrokeModel:
    """Turns text into a timed KeyPlan sequence. Pure and deterministic per seed —
    unit-testable and reusable by the KS-validation harness with no browser."""

    def __init__(self, persona: Persona | None = None, *, seed: int | None = None):
        self.persona = persona or sample_persona(seed)
        # own RNG so the driver's mouse jitter can't desync the keystroke stream
        self._rng = random.Random(
            self.persona.seed if self.persona.seed is not None else seed)
        self._tempo = 1.0                # OU state — persists across calls in a session
        # per-(persona, bigram) stable offset: THIS typist's "th" is consistently
        # its own speed, distinct from "he", even though both share a digraph bucket.
        # Salt makes it per-session (two None-seeded personas don't share a fingerprint).
        self._salt = (self.persona.seed if self.persona.seed is not None
                      else random.getrandbits(32))
        self._offsets: dict[str, float] = {}

    def _bigram_offset(self, bigram: str) -> float:
        """A stable ±15% offset for a specific key pair — fixed per persona, distinct
        across bigrams. Adds per-bigram *individuality* on top of the physiology bucket,
        while the log-normal draw still adds the moment-to-moment trial noise."""
        off = self._offsets.get(bigram)
        if off is None:
            off = random.Random(f"{self._salt}:{bigram}").uniform(-0.15, 0.15)
            self._offsets[bigram] = off
        return off

    def _lognorm(self, target_ms: float, sigma: float) -> float:
        return _clamp(self._rng.lognormvariate(math.log(max(target_ms, 1.0)), sigma),
                      15, 3000)

    def _dwell(self) -> float:
        p = self.persona
        return _clamp(self._rng.lognormvariate(math.log(p.dwell_ms), p.dwell_sigma), 25, 180)

    def _tempo_step(self) -> float:
        """Ornstein-Uhlenbeck: drift around 1.0 → consecutive keys correlated in speed."""
        p = self.persona
        self._tempo += p.tempo_theta * (1.0 - self._tempo) + p.tempo_sigma * self._rng.gauss(0, 1)
        self._tempo = _clamp(self._tempo, 0.6, 1.7)
        return self._tempo

    def _neighbor(self, ch: str) -> str:
        """A plausible wrong key for a typo — a different key on the SAME hand (a
        real slip, not a random jump). Falls back to a nearby letter."""
        fid = _finger(ch)
        pool = [c for c, f in _FINGER.items()
                if c.isalpha() and fid is not None and (f < 5) == (fid < 5) and c != ch.lower()]
        return self._rng.choice(pool) if pool else "e"

    def plan(self, text: str, *, first_field: bool = False,
             allow_errors: bool = True) -> list[KeyPlan]:
        """Plan the full keystroke sequence for `text` (typos + corrections inlined)."""
        plans: list[KeyPlan] = []
        prev: str | None = None
        for i, ch in enumerate(text):
            tempo = self._tempo_step()
            if prev is None:                              # first key of the field
                base = self.persona.think_ms if first_field else self.persona.base_ms * 1.5
            else:                                         # physiology bucket × this typist's per-bigram offset
                mult = _digraph_mult(prev, ch) * (1.0 + self._bigram_offset(prev + ch))
                base = self.persona.base_ms * mult
            flight = self._lognorm(base, self.persona.flight_sigma) * tempo
            if prev == " ":                               # new-word think pause
                flight += self._lognorm(self.persona.think_ms * 0.5, self.persona.flight_sigma)
            if _needs_shift(ch):                          # reach for shift
                flight += self._lognorm(self.persona.shift_ms, self.persona.flight_sigma)

            # occasional typo → notice → backspace → retype (the strongest human tell)
            if (allow_errors and prev is not None and ch.isalnum()
                    and self._rng.random() < self.persona.error_rate):
                plans.append(KeyPlan(self._neighbor(ch), flight, self._dwell(), "typo"))
                notice = self._lognorm(self.persona.base_ms * 2.5, self.persona.flight_sigma)
                plans.append(KeyPlan("Backspace", notice, self._dwell(), "backspace"))
                flight = self._lognorm(self.persona.base_ms * 0.8, self.persona.flight_sigma)

            plans.append(KeyPlan(ch, flight, self._dwell(), "key"))
            prev = ch
        return plans


# ── Human — the DRIVER (thin actuator over the Playwright page) ────────────────
class Human:
    """Executes humanized input on a live page. Holds ONE Persona/model for the
    session (coherence). Engine-agnostic: only the `page` API, so it ports to
    Chromium and wraps unchanged as an MCP tool."""

    def __init__(self, page, *, persona: Persona | None = None, seed: int | None = None):
        self.page = page
        self.model = KeystrokeModel(persona, seed=seed)
        self.persona = self.model.persona
        self._rng = random.Random(
            (self.persona.seed or 0) + 1 if self.persona.seed is not None else seed)

    def _locate(self, target):
        """Accept a CSS selector string OR a Playwright Locator (SDK-friendly)."""
        return target if hasattr(target, "click") else self.page.locator(target)

    def click(self, target) -> None:
        """Move to a random interior point (Camoufox humanizes the PATH), settle,
        then press with a human hold — never a teleport-click."""
        loc = self._locate(target)
        box = loc.bounding_box()
        if not box:                                   # not visible/measurable → safe fallback
            loc.click()
            return
        x = box["x"] + box["width"] * self._rng.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * self._rng.uniform(0.35, 0.65)
        self.page.mouse.move(x, y)                    # Camoufox draws the human curve
        time.sleep(self.persona.mouse_settle)
        self.page.mouse.down()
        time.sleep(self._rng.uniform(0.05, 0.11))     # click hold (down→up dwell)
        self.page.mouse.up()

    def type(self, target, text: str, *, secret: bool = False,
             click_first: bool = True) -> list[tuple]:
        """Type `text` into `target` key-by-key with human timing. NEVER uses
        `fill()` — fill() sets .value with ZERO keystroke events, which is an
        instant flag. `secret=True` (passwords) disables typo-correction. Returns
        the (key, flight_ms, dwell_ms, meta) trace — for logging / KS validation."""
        loc = self._locate(target)
        if click_first:
            self.click(loc)
            time.sleep(self._rng.uniform(0.08, 0.2))  # read the field before typing
        trace: list[tuple] = []
        for p in self.model.plan(text, first_field=True, allow_errors=not secret):
            time.sleep(p.flight_ms / 1000.0)
            self.page.keyboard.press(_tok(p.key), delay=int(p.dwell_ms))  # delay = hold
            trace.append((p.key, round(p.flight_ms, 1), round(p.dwell_ms, 1), p.meta))
        return trace


def type_into(page, target, text: str, *, seed: int | None = None,
              secret: bool = False) -> list[tuple]:
    """One-off convenience (tests / quick use): make a transient Human and type."""
    return Human(page, seed=seed).type(target, text, secret=secret)


__all__ = ["Persona", "sample_persona", "KeystrokeModel", "KeyPlan", "Human", "type_into"]
