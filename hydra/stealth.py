"""Adaptive / self-healing stealth — the flagship. (v0.2)

The loop: capture (patient — waits a JS challenge out) → diagnose → if still
blocked, **escalate by the leaked layer**, retry.

The escalation ladder is *patience-first, rotate-last* — the lesson from the
working Prospector scraper, which beats DataDome/Cloudflare on a plain native IP
by letting Camoufox solve the challenge, no proxy at all:

  1. try the current exit, waiting the challenge out (in `capture`)
  2. still blocked, and it's a **fingerprint/behavioral** challenge (Cloudflare,
     DataDome, PerimeterX)? → relaunch on the SAME exit (fresh Camoufox
     fingerprint, free per launch). Blindly rotating here often makes it worse —
     a clean native IP frequently beats a flagged proxy exit.
  3. only after patience+fingerprint fail, or when the layer is **IP** (403/429/
     geo — the exit genuinely is the problem), → rotate to a fresh exit.

`strategy="static"` (one exit, no escalation) is the baseline you measure against;
`strategy="rotate"` is blind-rotate-every-attempt (the naive version).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from hydra.diagnose import Verdict, diagnose
from hydra.discover import ApiCandidate, capture
from hydra.heal import HealSession
from hydra.session import load_proxies, parse_proxy


def _key(proxy: dict | None) -> str:
    return proxy["server"] if proxy else "native"


def _label(proxy: dict | None) -> str:
    return "native ISP IP" if not proxy else proxy["server"]


def _fresh_exit(pool: list[dict], tried: set[str]) -> dict | None:
    """A proxy not yet tried this run; reuse if the pool's exhausted; None if empty."""
    avail = [p for p in pool if _key(p) not in tried] or pool
    if not avail:
        return None
    choice = random.choice(avail)
    tried.add(_key(choice))
    return choice


@dataclass
class Attempt:
    n: int
    via: str            # the exit used this attempt
    verdict: Verdict
    n_candidates: int
    move: str = ""      # what the healer did next (escalation) or "done"
    detv: object = None  # detect.Verdict — vendor-free block-class → transition → lever


@dataclass
class HealResult:
    recovered: bool
    candidates: list[ApiCandidate]
    attempts: list[Attempt] = field(default_factory=list)
    result: object = None          # the winning CaptureResult (candidates + embedded)

    @property
    def tries(self) -> int:
        return len(self.attempts)

    @property
    def embedded(self):
        return self.result.embedded if self.result else []

    @property
    def streams(self):
        return self.result.streams if self.result else []


def resilient_capture(url: str, *, proxies_file: str | None = None,
                      explicit: str | dict | None = None, start: str = "native",
                      strategy: str = "adaptive", max_attempts: int = 4,
                      base_backoff: float = 2.0, fp_retries_before_rotate: int = 1,
                      behavioral_retries_before_rotate: int = 2,
                      challenge_wait_ms: int = 6000, headless: bool = True,
                      interact: bool = True, scroll_steps: int = 6,
                      storage_state: str | None = None, expect: str | None = None,
                      min_candidates: int = 1, on_attempt=None) -> HealResult:
    """Capture `url`, self-healing through blocks.

    strategy: 'adaptive' (layer-driven ladder, default) · 'static' (one exit, the
    baseline) · 'rotate' (fresh exit every attempt, the naive version).
    start: 'native' (no proxy first — usually the cleanest) or 'proxy'.
    Two ways to catch a *geo-degraded* 200 (a thin page, not a block, from a
    wrong-country exit) and keep rotating exits until the real data arrives:
      - min_candidates: require at least N discovered endpoints (no endpoint name
        needed — the practical default for discovery).
      - expect: require a discovered endpoint URL to contain this substring (when
        you already know the endpoint you're after).
    """
    def _met(result) -> bool:
        # count *all* data found — XHR candidates, SSR blobs, and live streams —
        # so a WebSocket-only or SSR-only page isn't mistaken for an empty one.
        found = len(result.candidates) + len(result.embedded) + len(result.streams)
        if found < min_candidates:
            return False
        if expect:
            urls = [c.url for c in result.candidates] + [s.url for s in result.streams]
            if not any(expect.lower() in u.lower() for u in urls):
                return False
        return True

    exits = [e for e in ([parse_proxy(explicit)] if explicit else load_proxies(proxies_file)) if e]

    def _apply_lever(session, lever, att) -> None:
        """Execute the truth-table lever on the LIVE session (hot; relaunch is nuclear)."""
        if lever == "patience":
            session.patience()
            att.move = "transient → patience (wait, same session)"
        elif lever == "rotate_exit":
            r = session.rotate()
            if r == "hot":
                att.move = "rate/IP → rotate exit (relay) — keep fp+session"
            elif r == "cold":
                att.move = "rate/IP → native→proxy (new session, geoip aligned)"
            else:
                session.relaunch()
                att.move = "rate/IP → rotate (no pool) → relaunch"
        elif lever == "drop_session":
            session.drop_session()
            att.move = "session/quota → drop session, keep fp"
        else:                                  # relaunch / fingerprint / unknown
            session.relaunch()
            att.move = "fingerprint → relaunch (new fp + session)"

    # ONE persistent session held across attempts — the levers mutate it in place.
    session = HealSession(exits, headless=headless, storage_state=storage_state).open()
    attempts: list[Attempt] = []
    last = None                                # best UNblocked result, for the final report
    last_any = None                            # most recent result even if blocked — for the trace
    try:
        for n in range(1, max_attempts + 1):
            result = capture(url, page=session.page, challenge_wait_ms=challenge_wait_ms,
                             interact=interact, scroll_steps=scroll_steps)
            last_any = result
            detv = None
            try:                               # vendor-free detector DRIVES the decision (Part 1)
                from hydra.detect import classify
                detv = classify(result.signals) if result.signals is not None else None
            except Exception:
                detv = None
            v = detv if detv is not None else diagnose(result)
            if not v.blocked:
                last = result
            att = Attempt(n, session.label(), v, len(result.candidates))
            att.detv = detv
            attempts.append(att)

            # terminal / not-a-block classes — don't spin.
            if detv is not None and detv.block_class == "no_data_channel":
                att.move = "no API channel (SSR) — not a block, stop"
                if on_attempt:
                    on_attempt(att)
                return HealResult(bool(result.embedded or result.candidates),
                                  result.candidates, attempts, result=result)
            if detv is not None and detv.blocked and not detv.self_heal:  # auth / hard_verify
                att.move = f"terminal: {detv.block_class} — needs a human/solver"
                if on_attempt:
                    on_attempt(att)
                return HealResult(False, result.candidates, attempts, result=result)

            if not v.blocked and _met(result):
                att.move = "done"
                if on_attempt:
                    on_attempt(att)
                return HealResult(True, result.candidates, attempts, result=result)

            # ---- escalate: apply the truth-table lever ON THE LIVE SESSION ------
            if n >= max_attempts:
                att.move = "give up (out of attempts)"
            elif not v.blocked:                # thin / geo-degraded 200 → rotate exit
                if session.rotate():
                    att.move = f"thin result ({len(result.candidates)} ep) → rotate exit (keep session)"
                else:
                    session.relaunch()
                    att.move = "thin result → relaunch (no pool)"
            else:
                lever = detv.lever if detv is not None else \
                    ("rotate_exit" if v.layer == "ip" else "relaunch")
                _apply_lever(session, lever, att)

            if on_attempt:
                on_attempt(att)
            if n < max_attempts:
                time.sleep(base_backoff * (2 ** (n - 1)))   # 2s, 4s, 8s…

        # out of attempts — hand back the best result (unblocked if we got one, else the
        # last blocked capture so its signals still explain WHY we're blocked).
        final = last if last is not None else last_any
        return HealResult(False, final.candidates if final else [], attempts, result=final)
    finally:
        session.close()
