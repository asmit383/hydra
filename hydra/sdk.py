"""Hydra — the stateful SDK object. ONE persistent stealth session an AI *or* a script drives.

Wraps session (heal) + discovery (discover) + detection (detect) + behavior (human) into one
object. The identity lifecycle is BAKED IN and not user-configurable:

  1. ONE persona per session, sampled when the identity is born (from the Aalto corpus;
     falls back to a guessed persona if the corpus isn't present).
  2. persona + fingerprint + session travel together — `relaunch` mints a new identity
     (new persona), hot levers (patience / rotate / drop_session) keep it.
  3. behavior is OURS — `humanize=False` always, `Human` always drives, NO user knob.
     The only escape hatch to raw input is `h.page`.

CLI, MCP, and hand-written scrapers all wrap this SAME object. The AI is an OPTIONAL consumer
(via `observe()`); everything else — navigate / capture / type / click / heal / fetch — is
deterministic and callable directly, no LLM required.
"""
from __future__ import annotations

from hydra.detect import classify
from hydra.discover import capture as _capture
from hydra.heal import HealSession
from hydra.human import Human
from hydra.session import load_proxies, parse_proxy


def _make_persona(seed, corpus_path):
    """A coherent persona from real Aalto data; fall back to the guessed sampler if the
    corpus isn't available (e.g. a fresh clone without the gitignored dataset)."""
    try:
        from hydra.behaviorforge import PersonaGenerator
        return PersonaGenerator.from_file(corpus_path).generate(seed=seed)
    except Exception:
        from hydra.human import sample_persona
        return sample_persona(seed)


class Hydra:
    def __init__(self, *, proxies: str | None = None, proxy: str | None = None,
                 seed: int | None = None, headful: bool = False, state: str | None = None,
                 corpus: str = "data/aalto_corpus.json"):
        exits = [parse_proxy(proxy)] if proxy else (load_proxies(proxies) if proxies else [])
        self._exits = [e for e in exits if e]
        self._on_proxy = bool(self._exits)            # start on the exit if any proxy was given
        self._seed, self._corpus, self._headful, self._state = seed, corpus, headful, state
        self.session: HealSession | None = None
        self.persona = None
        self.human: Human | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def __enter__(self):
        self.persona = _make_persona(self._seed, self._corpus)
        self.session = HealSession(self._exits, headless=not self._headful,
                                   storage_state=self._state,
                                   humanize=False).open(on_proxy=self._on_proxy)  # rule 3: humanize OFF
        self._bind_human()
        return self

    def __exit__(self, *a):
        if self.session:
            self.session.close()

    def _bind_human(self):
        """(Re)bind Human to the current session page, keeping the SAME persona identity."""
        self.human = Human(self.session.page, persona=self.persona, seed=self._seed)

    # ── properties (the state) ────────────────────────────────────────────────
    @property
    def page(self):                       # raw Playwright page — the only escape hatch
        return self.session.page

    @property
    def exit(self) -> str:
        return self.session.label()

    # ── navigation + discovery ────────────────────────────────────────────────
    def navigate(self, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 30000):
        self.session.page.goto(url, wait_until=wait_until, timeout=timeout)
        return self

    def capture(self, url: str, *, interact: bool = True, scroll_steps: int = 6,
                challenge_wait_ms: int = 6000, max_heal: int = 4):
        """Discover the page's data (APIs / SSR / streams), self-healing through blocks on the
        PERSISTENT session (patience → rotate → drop_session → relaunch). Returns CaptureResult
        (`.candidates`, `.embedded`, `.streams`, `.signals`)."""
        result = None
        for attempt in range(1, max_heal + 1):
            result = _capture(url, page=self.session.page, interact=interact,
                              scroll_steps=scroll_steps, challenge_wait_ms=challenge_wait_ms)
            v = classify(result.signals) if result.signals is not None else None
            if v is None or not v.blocked or not v.self_heal:   # got it, or terminal (auth/captcha)
                return result
            if attempt < max_heal:
                self._heal(v.lever)
        return result

    def _heal(self, lever: str):
        """Apply the truth-table lever on the live session. Only a relaunch mints a NEW
        identity (rule 2); rebind Human whenever the page was reopened."""
        reopened = False
        if lever == "patience":
            self.session.patience()
        elif lever == "drop_session":
            self.session.drop_session()
        elif lever == "rotate_exit":
            r = self.session.rotate()
            if r == "cold":                       # native→proxy relaunch (page changed)
                reopened = True
            elif r is None:                       # no pool → relaunch
                self.session.relaunch(); self._reidentify(); reopened = True
        else:                                     # relaunch / fingerprint / unknown
            self.session.relaunch(); self._reidentify(); reopened = True
        if reopened:
            self._bind_human()

    def _reidentify(self):
        """A relaunch = a new device = a new person (rule 2)."""
        self.persona = _make_persona(None, self._corpus)

    # ── behavioral actions (delegate to Human; act by selector OR observe() id) ─
    def _resolve(self, target):
        return f'[data-hydra-id="{target}"]' if isinstance(target, int) else target

    def type(self, target, text: str, **kw):
        return self.human.type(self._resolve(target), text, **kw)

    def click(self, target):
        return self.human.click(self._resolve(target))

    def move_to(self, target):
        return self.human.move_to(self._resolve(target))

    def idle(self, ms: float):
        return self.human.idle(ms)

    # ── replay (warm-session in-page fetch, credentials included) ──────────────
    def fetch(self, candidate):
        """Replay a discovered endpoint from INSIDE the live session (`credentials:'include'`)
        — carries the browser-minted clearance cookie a crafted httpx call can't."""
        url = getattr(candidate, "url", None) or candidate["url"]
        method = getattr(candidate, "method", None) or candidate.get("method", "GET")
        return self.session.page.evaluate(
            """async ([url, method]) => {
                const r = await fetch(url, {method, credentials: 'include'});
                const t = await r.text();
                try { return {status: r.status, json: JSON.parse(t)}; }
                catch { return {status: r.status, text: t.slice(0, 200000)}; }
            }""", [url, method])

    # ── AI action space (OPTIONAL — only when the caller doesn't know the flow) ─
    def observe(self):
        """Return the VISIBLE, labeled interactive elements — each with WHAT it is (label/kind),
        WHERE it is (`box=[x,y,w,h]`, for disambiguation + spatial reasoning), and a stable id
        to act on (`data-hydra-id`, via `h.click(id)` / `h.type(id, text)`). Flags OAuth/
        third-party buttons (dead-ends without external creds). ~top 60, DOM (≈reading) order."""
        return self.session.page.evaluate(
            """() => {
                const els = [...document.querySelectorAll(
                    'a, button, input, select, textarea, [role=button]')];
                const out = []; let id = 0;
                for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2 || !el.offsetParent) continue;  // visible only
                    el.setAttribute('data-hydra-id', String(++id));
                    const label = (el.getAttribute('aria-label') || el.innerText || el.value
                        || el.placeholder || el.name || el.alt || '').trim().slice(0, 60);
                    const oauth = /google|apple|facebook|microsoft|github|sso/i.test(label);
                    out.push({id, kind: el.tagName.toLowerCase(), type: el.type || null, label,
                              oauth, box: [Math.round(r.x), Math.round(r.y),
                                          Math.round(r.width), Math.round(r.height)]});
                    if (id >= 60) break;
                }
                return out;
            }""")


__all__ = ["Hydra"]
