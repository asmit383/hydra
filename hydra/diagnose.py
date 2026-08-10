"""Block diagnosis. (v0.2 — the brain of the self-healing loop)

Given a `CaptureResult`, decide: were we blocked? By what? **Which anti-detection
layer leaked** (IP reputation / browser fingerprint / behavior / network), and
what's the right adaptation. The healer (`stealth.py`) acts on the verdict.

The four layers (see project.md):
  - ip          : IP reputation / geo / ASN         → rotate to a clean exit
  - fingerprint : browser/JS fingerprint            → fresh fingerprint (relaunch)
  - behavioral  : timing / mouse / request cadence  → slow down, humanize
  - network     : TLS/JA3                             → (Camoufox owns this)
"""
from __future__ import annotations

from dataclasses import dataclass

from hydra.discover import CaptureResult


@dataclass
class Verdict:
    blocked: bool
    kind: str      # datadome | cloudflare | perimeterx | ratelimit | forbidden | captcha | none
    layer: str     # ip | fingerprint | behavioral | network | unknown | none
    signal: str    # human-readable: what tipped us off
    action: str    # recommended adaptation (what stealth.py will do)


def diagnose(result: CaptureResult) -> Verdict:
    """Classify a capture. Order matters — most specific vendor signal first, then
    generic HTTP status, then 'clean'. DataDome/rate-limit/403 are dominated by the
    **IP layer** (rotate exit); Cloudflare's JS challenge probes the **fingerprint**."""
    sig = result.block_signals

    def has(*needles: str) -> bool:
        return any(any(n in s for n in needles) for s in sig)

    if has("captcha-delivery.com", "datadome"):
        return Verdict(True, "datadome", "ip",
                       "DataDome interstitial / datadome cookie",
                       "rotate to a clean exit IP + back off")

    if has("challenge-platform", "challenges.cloudflare.com",
           "just a moment", "checking your browser"):
        return Verdict(True, "cloudflare", "fingerprint",
                       "Cloudflare JS challenge",
                       "fresh fingerprint (relaunch) + rotate exit")

    if has("perimeterx", "px-cloud", "/px/"):
        return Verdict(True, "perimeterx", "behavioral",
                       "PerimeterX sensor challenge",
                       "slow the cadence + rotate exit")

    if has("hcaptcha", "verify you are human", "are you a robot",
           "attention required", "access denied"):
        return Verdict(True, "captcha", "unknown",
                       "CAPTCHA / access-denied page",
                       "rotate exit + fresh fingerprint")

    if has("status:429"):
        return Verdict(True, "ratelimit", "ip",
                       "HTTP 429 — too many requests",
                       "back off hard + rotate exit")

    if has("status:403", "status:503"):
        return Verdict(True, "forbidden", "ip",
                       "HTTP 403/503 with no data endpoint",
                       "rotate exit IP")

    return Verdict(False, "none", "none", "clean load — no block signals", "—")
