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

    pool = [parse_proxy(explicit)] if explicit else load_proxies(proxies_file)
    tried: set[str] = set()

    if start == "proxy" or strategy == "rotate":
        exit_ = _fresh_exit(pool, tried)
    else:
        exit_ = None                       # native first — the patient default
    if start != "proxy":
        tried.add("native")

    attempts: list[Attempt] = []
    fp_tries = 0
    last = None                            # best result seen, for the final report

    for n in range(1, max_attempts + 1):
        result = capture(url, proxy=exit_, headless=headless,
                         challenge_wait_ms=challenge_wait_ms,
                         interact=interact, scroll_steps=scroll_steps,
                         storage_state=storage_state)
        v = diagnose(result)
        if not v.blocked:
            last = result
        att = Attempt(n, _label(exit_), v, len(result.candidates))
        attempts.append(att)

        if not v.blocked and _met(result):
            att.move = "done"
            if on_attempt:
                on_attempt(att)
            return HealResult(True, result.candidates, attempts, result=result)

        # ---- escalate for the next attempt ----------------------------------
        if n >= max_attempts:
            att.move = "give up (out of attempts)"
        elif not v.blocked:  # not blocked, but the result is thin / expected data
            new = _fresh_exit(pool, tried)   # didn't fire → geo-degraded: try another exit
            why = f"expected '{expect}' missing" if expect else \
                  f"only {len(result.candidates)} endpoint(s)"
            exit_, att.move = new, f"{why} → rotate exit → {_label(new)}"
            fp_tries = 0
        elif strategy == "static":
            att.move = "retry same exit (patience only)"
        elif strategy == "rotate":
            exit_ = _fresh_exit(pool, tried)
            att.move = f"rotate → {_label(exit_)}"
        else:  # adaptive: react to which layer leaked
            if v.layer == "ip":
                new = _fresh_exit(pool, tried)
                exit_, att.move = new, f"IP-layer block → rotate exit → {_label(new)}"
                fp_tries = 0
            else:  # fingerprint / behavioral / unknown — a JS challenge
                fp_tries += 1
                if fp_tries > fp_retries_before_rotate:
                    new = _fresh_exit(pool, tried)
                    exit_, att.move = new, f"patience failed → rotate exit → {_label(new)}"
                    fp_tries = 0
                else:
                    att.move = "same exit, fresh fingerprint + patience"

        if on_attempt:
            on_attempt(att)
        if n < max_attempts:
            time.sleep(base_backoff * (2 ** (n - 1)))   # 2s, 4s, 8s...

    # never met the expectation — hand back the best (unblocked) result we did get
    return HealResult(False, last.candidates if last else [], attempts, result=last)
