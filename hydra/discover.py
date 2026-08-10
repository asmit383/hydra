"""Internal-API discovery. (v0.1 — the core)

Navigate a target URL in Camoufox, intercept every XHR/fetch response, and find
the internal JSON endpoint(s) that carry the target data. Capture each candidate's
request (url, method, headers, params) so it can be replayed browser-free.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from hydra.session import launch


_NOISE = (
    "google-analytics", "googletagmanager", "doubleclick", "facebook.com",
    "segment.io", "segment.com", "sentry.io", "datadoghq", "hotjar",
    "mixpanel", "cloudflareinsights", "intercom", "amplitude", "fullstory",
    "clarity.ms", "gstatic.com", "googleapis.com", "recaptcha", "/fonts",
    "fonts.", "cdn.jsdelivr", "unpkg.com", "bat.bing",
    "cookielaw.org", "onetrust", "cookiebot", "usercentrics",  # consent/CMP config
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


def discover(url: str, proxy: dict | None = None, wait_ms: int = 3500,
             headless: bool = True) -> list[ApiCandidate]:
    """Load `url` in Camoufox, capture the JSON XHR/fetch responses, and return the
    ones that look like the site's internal data API — biggest (most data) first.

    `proxy` is a Camoufox proxy dict (from session.pick_proxy / parse_proxy) or None
    for the native ISP IP. Needed for geo-locked / IP-reputation-gated sites."""
    candidates: list[ApiCandidate] = []
    seen: set[str] = set()

    def on_response(response):
        # This IS "the handler": Camoufox calls it for EVERY response automatically.
        u = response.url
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

    with launch(proxy=proxy, headless=headless) as page:
        page.on("response", on_response)          # register BEFORE navigating!
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)            # let lazy / on-scroll XHR fire

    # biggest data blob first — most likely the real listing/data endpoint
    candidates.sort(key=lambda c: c.size, reverse=True)
    return candidates
