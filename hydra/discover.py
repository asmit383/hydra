"""Internal-API discovery. (v0.1 — the core)

Navigate a target URL in Camoufox, intercept every XHR/fetch response, and find
the internal JSON endpoint(s) that carry the target data. Capture each candidate's
request (url, method, headers, params) so it can be replayed browser-free.

`capture()` also records **block signals** (DataDome / Cloudflare / 403 / challenge
titles) so the v0.2 self-healing loop can diagnose *why* a load failed. `discover()`
stays the thin "just give me the candidates" entry point.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from hydra.session import launch


_NOISE = (
    "google-analytics", "googletagmanager", "doubleclick", "facebook.com",
    "segment.io", "segment.com", "rudderstack", "sentry.io", "datadoghq", "hotjar",
    "mixpanel", "cloudflareinsights", "intercom", "amplitude", "fullstory",
    "clarity.ms", "gstatic.com", "googleapis.com", "recaptcha", "/fonts",
    "fonts.", "cdn.jsdelivr", "unpkg.com", "bat.bing",
    "cookielaw.org", "onetrust", "cookiebot", "usercentrics",  # consent/CMP config
)

# Hosts/paths that mean "you got challenged", not "here's your data". Kept separate
# from _NOISE: noise is ignored, a block is a *signal* the healer reacts to.
_BLOCK_HOSTS = (
    "captcha-delivery.com", "datadome",              # DataDome
    "challenges.cloudflare.com", "/cdn-cgi/challenge-platform",  # Cloudflare
    "perimeterx", "px-cloud", "/px/",                # PerimeterX
    "hcaptcha.com",                                  # hCaptcha gate
)
# Interstitial page <title>s (lowercased substrings).
_BLOCK_TITLES = (
    "just a moment", "checking your browser", "attention required",
    "access denied", "verify you are human", "are you a robot",
)


@dataclass
class ApiCandidate:
    url: str
    method: str
    status: int
    size: int                 # bytes of the JSON body (bigger ~ more likely the data)
    shape: str                # "list[120]" / "dict(8 keys)" — quick eyeball
    request_headers: dict     # includes auth (Authorization / X-Api-Key / cookies)
    post_data: str | None     # POST body / GraphQL query, if any
    sample: object            # a small slice of the JSON, to confirm it's the data


@dataclass
class CaptureResult:
    """Everything one navigation told us — the data *and* the block evidence."""
    candidates: list[ApiCandidate]
    nav_status: int | None    # HTTP status of the main document response
    final_url: str            # where we ended up (redirects/interstitials move it)
    title: str                # page <title> (challenge pages have telltale titles)
    block_signals: list[str]  # e.g. ["host:captcha-delivery.com", "status:403"]


def _is_noise(url: str) -> bool:
    low = url.lower()
    return any(n in low for n in _NOISE)


def _shape(data) -> tuple[str, object]:
    """Human-readable shape + a small sample of a parsed JSON body."""
    if isinstance(data, list):
        return f"list[{len(data)}]", data[:2]
    if isinstance(data, dict):
        return f"dict({len(data)} keys)", {k: data[k] for k in list(data)[:5]}
    return type(data).__name__, data


def _looks_like_data(data) -> bool:
    """Heuristic: does this JSON look like real records, not a ping/flag/config?"""
    if isinstance(data, list):
        return len(data) >= 1
    if isinstance(data, dict):
        # a dict that *wraps* a non-empty list counts ({"results": [...]}, GraphQL, etc.)
        if any(isinstance(v, list) and v for v in data.values()):
            return True
        return len(data) >= 3
    return False


def capture(url: str, proxy: dict | None = None, wait_ms: int = 3500,
            headless: bool = True) -> CaptureResult:
    """Navigate `url` and return both the API candidates and the block evidence.

    `proxy` is a Camoufox proxy dict (from session.pick_proxy) or None for the
    native ISP IP. This is the full result the healer diagnoses; `discover()` is
    the thin wrapper that only wants the candidates."""
    candidates: list[ApiCandidate] = []
    seen: set[str] = set()
    block: set[str] = set()

    def on_response(response):
        # This IS "the handler": Camoufox calls it for EVERY response automatically.
        u = response.url
        low = u.lower()
        # block detection runs on every response, independent of the noise/JSON gates
        for b in _BLOCK_HOSTS:
            if b in low:
                block.add(f"host:{b}")
        if u in seen or _is_noise(u):
            return
        # cheap filter first: content-type must smell like JSON
        ctype = (response.headers or {}).get("content-type", "").lower()
        if "json" not in ctype:
            return
        # read the body — can fail (redirects, empty, already-consumed) → skip those
        try:
            data = response.json()
        except Exception:
            return
        if not _looks_like_data(data):
            return

        seen.add(u)
        shape, sample = _shape(data)
        req = response.request
        candidates.append(ApiCandidate(
            url=u,
            method=req.method,
            status=response.status,
            size=len(json.dumps(data)),
            shape=shape,
            request_headers=dict(req.headers),
            post_data=req.post_data,
            sample=sample,
        ))

    nav_status: int | None = None
    final_url = url
    title = ""
    with launch(proxy=proxy, headless=headless) as page:
        page.on("response", on_response)          # register BEFORE navigating!
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=45000)
            nav_status = resp.status if resp else None
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)            # let lazy / on-scroll XHR fire
        try:
            title = page.title()
            final_url = page.url
        except Exception:
            pass

    # fold the non-network signals in (status of the main doc, challenge-page title)
    if nav_status in (403, 429, 503):
        block.add(f"status:{nav_status}")
    low_title = title.lower()
    for t in _BLOCK_TITLES:
        if t in low_title:
            block.add(f"title:{t}")

    # biggest data blob first — most likely the real listing/data endpoint
    candidates.sort(key=lambda c: c.size, reverse=True)
    return CaptureResult(candidates, nav_status, final_url, title, sorted(block))


def discover(url: str, proxy: dict | None = None, wait_ms: int = 3500,
             headless: bool = True) -> list[ApiCandidate]:
    """Load `url` and return the internal-data API candidates, biggest first.
    Thin wrapper over `capture()` for callers that only want the endpoints."""
    return capture(url, proxy=proxy, wait_ms=wait_ms, headless=headless).candidates
