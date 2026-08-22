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

from hydra.mouseforge import MouseForge, trajectory

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
    """Flight-time multiplier for a key pair — the core human correlation. Values MEASURED
    from 3000 real Aalto typists (median bigram flight / the typist's own base): same finger
    slowest, hand-alternation fastest. The real spread is far gentler than the intuitive
    guess (same-finger 1.06×, not 1.6×) — measured, not invented."""
    a, b = _finger(prev), _finger(cur)
    if a is None or b is None:
        return 1.0
    if a == b:
        return 1.06                      # same finger — slowest (measured; was a guessed 1.6)
    if (a < 5) == (b < 5):
        return 0.92                      # same hand, different finger (was 1.15)
    return 0.80                          # hand alternation — fastest (was 0.85)


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

    def __init__(self, page, *, persona: Persona | None = None, seed: int | None = None,
                 mouse_forge: MouseForge | None = None):
        self.page = page
        self.model = KeystrokeModel(persona, seed=seed)
        self.persona = self.model.persona
        self._rng = random.Random(
            (self.persona.seed or 0) + 1 if self.persona.seed is not None else seed)
        # ONE coherent mouse persona per session (fast typist ⇒ fast mouse), and we
        # GENERATE the trajectory ourselves — so no two agents move alike (fleet diversity).
        self.mouse = (mouse_forge or MouseForge()).generate(
            seed, typing_base_ms=self.persona.base_ms)
        self._pos: tuple[float, float] | None = None   # tracked cursor position

    def _locate(self, target):
        """Accept a CSS selector string OR a Playwright Locator (SDK-friendly)."""
        return target if hasattr(target, "click") else self.page.locator(target)

    def _point_in(self, box) -> tuple[float, float]:
        """A random interior point of a box — never dead-center (that's a tell)."""
        return (box["x"] + box["width"] * self._rng.uniform(0.25, 0.75),
                box["y"] + box["height"] * self._rng.uniform(0.3, 0.7))

    def _viewport(self) -> dict:
        return getattr(self.page, "viewport_size", None) or {"width": 1280, "height": 800}

    def _targets(self) -> list:
        """VISIBLE, in-viewport interactive elements. Humans move toward these — and we SKIP
        off-screen ones: moving toward an element below the fold flings the cursor out of
        view (the 'weird wandering'). Degrades to [] on any error."""
        vp, boxes = self._viewport(), []
        try:
            for loc in self.page.locator("a, button, input, [role=button]").all()[:40]:
                b = loc.bounding_box()
                if (b and b["width"] > 4 and b["height"] > 4
                        and 0 <= b["x"] <= vp["width"] and 0 <= b["y"] <= vp["height"]):
                    boxes.append(b)
        except Exception:
            pass
        return boxes

    def _cursor(self) -> tuple[float, float]:
        if self._pos is None:
            vp = self._viewport()
            self._pos = (vp["width"] / 2, vp["height"] / 2)
        return self._pos

    def _trace_to(self, x: float, y: float) -> None:
        """Step a PERSONA-GENERATED trajectory to (x,y) — our own curve/velocity/tremor,
        not Camoufox's fleet-identical one — updating the tracked cursor position."""
        x0, y0 = self._cursor()
        for px, py, dt in trajectory(self.mouse, x0, y0, x, y, self._rng):
            try:
                self.page.mouse.move(px, py)
            except Exception:
                pass
            if dt:
                time.sleep(dt / 1000.0)
        self._pos = (x, y)

    def move_to(self, target) -> None:
        """Humanized move onto an element via the generated trajectory, then settle."""
        loc = self._locate(target)
        try:
            loc.scroll_into_view_if_needed(timeout=3000)   # below-fold → bring it in first
        except Exception:
            pass
        try:
            box = loc.bounding_box()
        except Exception:
            return
        if box:
            x, y = self._point_in(box)
            self._trace_to(x, y)
            time.sleep(self.mouse.settle_ms / 1000.0)

    def drift(self) -> None:
        """A SMALL, LOCAL idle movement near the current cursor — a human at rest doesn't
        fling the cursor across the page. Occasionally a short hop toward a NEARBY visible
        element; otherwise a gentle ±px nudge. Always clamped on-screen."""
        cx, cy = self._cursor()
        vp = self._viewport()
        near = [t for t in self._targets()
                if abs(t["x"] + t["width"] / 2 - cx) < 350 and abs(t["y"] + t["height"] / 2 - cy) < 350]
        if near and self._rng.random() < 0.35:            # occasional nearby purposeful hop
            x, y = self._point_in(self._rng.choice(near))
        else:                                             # small local nudge
            x, y = cx + self._rng.uniform(-90, 90), cy + self._rng.uniform(-70, 70)
        self._trace_to(min(max(x, 2), vp["width"] - 2), min(max(y, 2), vp["height"] - 2))

    def idle(self, ms: float) -> None:
        """Fill a wait — above all the LLM round-trip between agent actions — with human
        idle behavior instead of a FROZEN cursor. A cursor that sits dead-still for seconds
        every time the brain thinks is the loudest agent-body tell, and it's *inherent* to
        the agent loop (observe → LLM thinks → act). Paced by the persona. Call this instead
        of `time.sleep` around an LLM call."""
        spent, scale = 0.0, self.persona.base_ms / 135.0
        while spent < ms:
            pause = min(self._rng.uniform(700, 2200) * scale, ms - spent)
            if pause <= 0:
                break
            time.sleep(pause / 1000.0)                 # mostly STILL…
            spent += pause
            if spent < ms and self._rng.random() < 0.5:   # …with an occasional small drift
                self.drift()

    def scroll(self, *, steps: int | None = None) -> None:
        """Humanized scrolling — variable-distance real wheel scrolls with persona-paced
        reading pauses + the occasional scroll-back. PERSONA-COHERENT (a slower typist
        scrolls and reads slower). Never a fixed distance/rhythm — that's the robotic tell."""
        n = steps if steps is not None else self._rng.randint(4, 8)
        scale = self.persona.base_ms / 135.0
        for i in range(n):
            try:
                self.page.mouse.wheel(0, self._rng.randint(280, 820))   # variable chunk
                if i and self._rng.random() < 0.2:                      # occasional re-read
                    time.sleep(self._rng.uniform(0.15, 0.5))
                    self.page.mouse.wheel(0, -self._rng.randint(120, 380))
            except Exception:
                break
            time.sleep(self._rng.uniform(0.3, 1.1) * scale)             # reading dwell, persona-paced

    def click(self, target) -> None:
        """Move to an interior point (Camoufox humanizes the PATH), settle, then press with
        a human hold — never a teleport-click, never dead-center."""
        loc = self._locate(target)
        try:
            loc.scroll_into_view_if_needed(timeout=3000)  # CRITICAL: a below-fold target must be
        except Exception:                                 # scrolled in, else the humanized move lands
            pass                                          # off-screen, never focuses it, and typing
        try:                                              # leaks into whatever WAS focused
            box = loc.bounding_box()
        except Exception:
            box = None
        if not box:                                   # not visible/measurable → brief fallback, no 30s hang
            try:
                loc.click(timeout=3000)
            except Exception:
                pass
            return
        x, y = self._point_in(box)
        self._trace_to(x, y)                          # our persona-generated trajectory
        time.sleep(self.mouse.settle_ms / 1000.0)
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
