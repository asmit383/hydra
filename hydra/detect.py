"""Robust, vendor-FREE block detection (v0.3 — replaces the diagnose.py vendor table).

The old `diagnose.py` mapped vendor names → layers (DataDome→ip, Cloudflare→fp). That's
a canned guess: brittle (needs a maintained list) and often wrong (a DataDome block can
be behavioral, not IP). This module keys on the **block itself**, not the brand:

  1. ANCHOR on the success-oracle — "did I get usable data?" (candidates+embedded+streams).
     The one signal the adversary can't fake: handing you the data means they failed to
     block you. Everything else is a hint.
  2. When the oracle is red, SUB-CLASSIFY from vendor-free signals — status, response
     headers (Retry-After / X-RateLimit / WWW-Authenticate / clearance Set-Cookie),
     edge-vs-origin, challenge-shape, timing, scope.
  3. Map the block-class → a human transition → the cheapest lever that mimics it.

Reliability rule baked in: trust non-200 as "restricted", distrust 200 as "success"
(the 200-hidden-block is the adversary's best weapon), always confirm with the oracle.

NOT built here: the learned feedback loop (that's an optimisation). This is deterministic
diagnosis from rich passive signals — which covers most blocks on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# clearance cookies whose Set-Cookie means "a challenge token is being minted"
_CLEARANCE = ("_abck", "datadome", "cf_clearance", "_px", "ak_bmsc", "bm_sv")

# block-class → (human transition, lever, self-heals?)  — the heart of the healer.
_PLAN: dict[str, tuple[str, str, bool]] = {
    "clean":             ("—",              "none",         True),
    "transient":         ("returning user", "patience",     True),
    "rate_limit":        ("moved network",  "rotate_exit",  True),
    "ip_block":          ("moved network",  "rotate_exit",  True),
    "session_block":     ("fresh visit",    "drop_session", True),
    "fingerprint_block": ("new device",     "relaunch",     True),
    "auth_required":     ("—",              "login",        False),   # human
    "hard_verify":       ("—",              "solver",       False),   # human
    "no_data_channel":   ("—",              "parse_ssr",    True),    # not a block
    "unknown":           ("ladder",         "cost_ladder",  True),
}


@dataclass
class Signals:
    """A rich, vendor-free observation of one capture. Every field is a raw signal —
    the classifier reasons over these, never over a vendor name."""
    oracle_count: int = 0            # candidates+embedded+streams — the ANCHOR
    nav_status: int | None = None    # main-document HTTP status
    statuses: list[int] = field(default_factory=list)   # every response status seen (scope)
    redirected: bool = False         # final_url != requested (→ login/challenge?)
    body_len: int = 0                # emptiness axis (rules hard-block in/out)
    title: str = ""
    content_type: str = ""           # of the main document
    server: str = ""                 # edge (CF-RAY/cloudflare/akamai) vs origin
    retry_after: str | None = None   # → rate-limit + the backoff
    ratelimit: bool = False          # X-RateLimit-* present → app-layer QUOTA (key), not IP
    www_authenticate: str | None = None   # → auth/session
    clearance_cookies: list[str] = field(default_factory=list)  # _abck/_px/... minted
    challenge_shape: bool = False    # interstitial structure (min content + script + redirect)
    interactive_captcha: bool = False   # a real captcha widget (hCaptcha/reCAPTCHA)
    first_request_block: bool = False   # blocked on request #1 (pre-emptive → ip/fp)


@dataclass
class Verdict:
    blocked: bool
    block_class: str          # see _PLAN keys
    transition: str           # returning user | moved network | fresh visit | new device | …
    lever: str                # patience | rotate_exit | drop_session | relaunch | login | solver | …
    self_heal: bool           # can the machine fix it, or is it the human part?
    confidence: float
    reasons: list[str]        # the reasoning chain, for the verbose log
    signal: str               # one-line human summary
    # back-compat with stealth.py's Verdict interface:
    layer: str = "unknown"
    action: str = ""


def _edge(server: str) -> bool:
    s = (server or "").lower()
    return any(x in s for x in ("cloudflare", "akamai", "cf-ray", "fastly", "cloudfront"))


def classify(sig: Signals) -> Verdict:
    """Oracle-anchored, vendor-free classification. Order = oracle first, then
    sub-classify the failure from rich passive signals, cheapest-transition first."""
    r: list[str] = []

    # 1. ORACLE ANCHOR — got the data? then you're not blocked, whatever the status says.
    if sig.oracle_count >= 1:
        r.append(f"oracle GREEN: {sig.oracle_count} data channel(s) → not blocked")
        return _verdict("clean", 0.98, r, "clean — got the data")

    r.append("oracle RED: 0 data channels → investigate WHY")

    # 2. Human-verification (terminal — the human part).
    if sig.interactive_captcha:
        r.append("interactive captcha widget → needs a human/solver")
        return _verdict("hard_verify", 0.9, r, "hard captcha — human/solver")

    # 3. Auth required (the human part — a saved login or a person).
    if sig.www_authenticate or (sig.redirected and "login" in (sig.title + " ").lower()):
        r.append("WWW-Authenticate / redirect-to-login → auth gate")
        return _verdict("auth_required", 0.85, r, "auth required — human/login")

    # 4. Transient JS challenge (auto-clearing) → patience, change nothing.
    if sig.challenge_shape and not sig.interactive_captcha:
        r.append("challenge-shape interstitial (auto-clearing) → wait it out")
        return _verdict("transient", 0.7, r, "transient challenge — patience")

    # 5. Rate / quota. X-RateLimit ⇒ QUOTA on your key (app-layer), not raw IP.
    if sig.ratelimit or sig.retry_after or sig.nav_status == 429:
        if sig.ratelimit and not _edge(sig.server):
            r.append("X-RateLimit + origin (not edge) → app-layer QUOTA on the key/session")
            return _verdict("session_block", 0.75, r, "quota on key — drop session")
        r.append(f"429 / Retry-After ({sig.retry_after}) → rate-limit, likely IP/edge")
        return _verdict("rate_limit", 0.75, r, "rate-limit — rotate exit")

    # 6. Session/token gate (401/412 or a clearance cookie being demanded).
    if sig.nav_status in (401, 412) or sig.clearance_cookies:
        r.append(f"status {sig.nav_status} / clearance cookie {sig.clearance_cookies} "
                 "→ session/token gate")
        return _verdict("session_block", 0.7, r, "session/token gate — drop session")

    # 7. Hard forbidden — IP/edge restriction (no data, real deny).
    if sig.nav_status in (403, 503):
        cls = "ip_block"
        r.append(f"status {sig.nav_status}, no data → forbidden (IP/edge layer)")
        if sig.first_request_block:
            r.append("blocked on request #1 → pre-emptive (IP or fingerprint)")
        return _verdict(cls, 0.7, r, "forbidden — rotate exit")

    # 8. 200 but no data, real page, no challenge → NOT a block: SSR / no-API (Amazon).
    if sig.nav_status == 200 and sig.body_len > 4000 and not sig.challenge_shape:
        r.append(f"200 + real page (body {sig.body_len}b) + no challenge + no API "
                 "→ NO data channel exists (SSR/no-API) — DON'T heal, parse the page")
        return _verdict("no_data_channel", 0.8, r, "no API here — SSR, parse it")

    # 9. Opaque residual — nothing diagnostic. Fall back to the cost-ordered ladder.
    r.append("no diagnostic signal (opaque) → cost-ordered ladder "
             "(patience→rotate→drop_session→relaunch, stop when oracle green)")
    return _verdict("unknown", 0.4, r, "opaque — cost-ordered ladder")


def _verdict(block_class: str, conf: float, reasons: list[str], summary: str) -> Verdict:
    transition, lever, self_heal = _PLAN[block_class]
    blocked = block_class not in ("clean", "no_data_channel")
    layer = {"rate_limit": "ip", "ip_block": "ip", "session_block": "session",
             "fingerprint_block": "fingerprint", "transient": "network",
             "clean": "none", "no_data_channel": "none"}.get(block_class, "unknown")
    return Verdict(blocked=blocked, block_class=block_class, transition=transition,
                   lever=lever, self_heal=self_heal, confidence=conf, reasons=reasons,
                   signal=summary, layer=layer, action=f"{transition} → {lever}")


# ── verbose terminal logging — show EVERYTHING, not just the APIs ──────────────
def log_trace(sig: Signals, v: Verdict, *, use_color: bool = True) -> None:
    """Print the full reasoning chain: raw signals → diagnosis → transition/lever."""
    C = _C if use_color else _NoC
    print(f"\n{C.bold}── detection trace ─────────────────────────────{C.end}")
    print(f"{C.dim}signals:{C.end}")
    rows = [
        ("oracle (data channels)", sig.oracle_count),
        ("nav_status", sig.nav_status),
        ("all statuses", sig.statuses or "—"),
        ("body_len", sig.body_len),
        ("content_type", sig.content_type or "—"),
        ("server", sig.server or "—"),
        ("retry_after", sig.retry_after or "—"),
        ("X-RateLimit", sig.ratelimit),
        ("WWW-Authenticate", sig.www_authenticate or "—"),
        ("clearance cookies", sig.clearance_cookies or "—"),
        ("challenge_shape", sig.challenge_shape),
        ("interactive_captcha", sig.interactive_captcha),
        ("redirected", sig.redirected),
        ("first_request_block", sig.first_request_block),
    ]
    for k, val in rows:
        print(f"  {C.dim}{k:22}{C.end} {val}")
    print(f"{C.dim}reasoning:{C.end}")
    for step in v.reasons:
        print(f"  {C.dim}·{C.end} {step}")
    tag = (C.green if not v.blocked else (C.yellow if v.self_heal else C.red))
    print(f"{C.bold}verdict:{C.end} {tag}{v.block_class}{C.end}  "
          f"(conf {v.confidence:.2f})")
    print(f"  transition {C.bold}{v.transition}{C.end}  →  lever "
          f"{C.bold}{v.lever}{C.end}  →  self-heal "
          f"{(C.green+'yes' if v.self_heal else C.red+'HUMAN')}{C.end}")


class _C:
    bold = "\033[1m"; dim = "\033[2m"; green = "\033[32m"; yellow = "\033[33m"
    red = "\033[31m"; end = "\033[0m"


class _NoC:
    bold = dim = green = yellow = red = end = ""


# ── demo: run synthetic cases so you see the full trace with no browser ────────
def _demo() -> None:
    cases = {
        "clean product page":      Signals(oracle_count=2, nav_status=200, body_len=90000),
        "amazon SSR (no API)":     Signals(oracle_count=0, nav_status=200, body_len=1400000,
                                           content_type="text/html"),
        "429 edge rate-limit":     Signals(oracle_count=0, nav_status=429, retry_after="30",
                                           server="cloudflare", statuses=[200, 429]),
        "429 key quota (origin)":  Signals(oracle_count=0, nav_status=429, ratelimit=True,
                                           server="amazon", statuses=[429]),
        "403 forbidden (IP)":      Signals(oracle_count=0, nav_status=403, body_len=800,
                                           first_request_block=True),
        "cloudflare interstitial": Signals(oracle_count=0, nav_status=503, body_len=1500,
                                           challenge_shape=True),
        "perimeterx 412 token":    Signals(oracle_count=0, nav_status=412,
                                           clearance_cookies=["_px", "_abck"]),
        "hcaptcha wall":           Signals(oracle_count=0, nav_status=403,
                                           interactive_captcha=True),
        "login gate":              Signals(oracle_count=0, nav_status=200, redirected=True,
                                           title="Sign in", body_len=6000),
        "opaque 403 no headers":   Signals(oracle_count=0, nav_status=403, body_len=200),
    }
    for name, sig in cases.items():
        v = classify(sig)
        print(f"\n\033[1m### {name}\033[0m")
        log_trace(sig, v)


if __name__ == "__main__":
    _demo()
