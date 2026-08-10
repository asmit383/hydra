"""Adaptive / self-healing stealth — the flagship. (v0.2)

The loop: capture → diagnose → if blocked, **adapt** (rotate to a fresh exit IP +
relaunch for a new fingerprint + back off) → retry, until through or out of tries.

Why this beats "retry from the same IP": the blocks we actually hit (DataDome,
403, 429) are dominated by the **IP-reputation layer** — a single exit you keep
hammering only sinks its score. The adaptation that matters is *change the exit*,
plus a fresh Camoufox fingerprint each launch (free — Camoufox re-rolls per launch).

`rotate=False` reuses one exit for every attempt: that's the **static baseline** you
measure the adaptive loop against. The gap between the two recovery-rates is the
proof (`examples/heal_bench.py`).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from hydra.diagnose import Verdict, diagnose
from hydra.discover import ApiCandidate, capture
from hydra.session import pick_proxy


@dataclass
class Attempt:
    n: int
    via: str            # the exit used (proxy server or "native ISP IP")
    verdict: Verdict
    n_candidates: int


@dataclass
class HealResult:
    recovered: bool
    candidates: list[ApiCandidate]
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def tries(self) -> int:
        return len(self.attempts)


def resilient_capture(url: str, *, proxy_mode: str = "file", proxies_file: str | None = None,
                      explicit: str | dict | None = None, max_attempts: int = 4,
                      base_backoff: float = 2.0, rotate: bool = True, headless: bool = True,
                      on_attempt=None) -> HealResult:
    """Capture `url`, self-healing through blocks.

    - `rotate=True`  : re-pick the exit every attempt (adaptive).
    - `rotate=False` : pick one exit up front and reuse it (static baseline).
    - `on_attempt(Attempt)` : optional callback, fired after each try (for live logs).

    Returns as soon as a capture comes back **clean** (not blocked). If every
    attempt is blocked, `recovered=False` and `candidates` is empty."""
    attempts: list[Attempt] = []
    fixed = None if rotate else pick_proxy(proxy_mode, proxies_file=proxies_file, explicit=explicit)

    for n in range(1, max_attempts + 1):
        proxy = pick_proxy(proxy_mode, proxies_file=proxies_file, explicit=explicit) if rotate else fixed
        via = "native ISP IP" if proxy is None else proxy["server"]

        result = capture(url, proxy=proxy, headless=headless)
        verdict = diagnose(result)
        att = Attempt(n, via, verdict, len(result.candidates))
        attempts.append(att)
        if on_attempt:
            on_attempt(att)

        if not verdict.blocked:
            return HealResult(recovered=True, candidates=result.candidates, attempts=attempts)

        # adapt: rotation happens on the next pick_proxy; fingerprint is fresh on the
        # next launch. Back off (exponential) so we don't hammer — 2s, 4s, 8s...
        if n < max_attempts:
            time.sleep(base_backoff * (2 ** (n - 1)))

    return HealResult(recovered=False, candidates=[], attempts=attempts)
