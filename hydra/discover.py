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
from dataclasses import dataclass, field

from hydra.embed import EmbeddedBlob, extract_embedded
from hydra.session import launch


_NOISE = (
    "google-analytics", "googletagmanager", "doubleclick", "facebook.com",
    "segment.io", "segment.com", "rudderstack", "sentry.io", "datadoghq", "hotjar",
    "mixpanel", "cloudflareinsights", "intercom", "amplitude", "fullstory",
    "clarity.ms", "gstatic.com", "googleapis.com", "recaptcha", "/fonts",
    "fonts.", "cdn.jsdelivr", "unpkg.com", "bat.bing",
    "cookielaw.org", "onetrust", "cookiebot", "usercentrics",  # consent/CMP config
    "adobedc.net", "demdex.net", "omtrdc.net",  # Adobe Experience Cloud tracking
    "stripe.com", "paypal.com", "braintreegateway",  # payment SDKs/infra
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
    embedded: list[EmbeddedBlob] = field(default_factory=list)  # SSR-inlined data (v0.1.1)


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


def _challenge_title(title: str) -> str | None:
    """Return the matched challenge-title substring, or None if the title is normal."""
    low = title.lower()
    return next((t for t in _BLOCK_TITLES if t in low), None)


def _autoscroll(page, steps: int, pause: int) -> None:
    """Scroll the page in steps to fire infinite-scroll / lazy-loaded XHR. Safe:
    scrolling never navigates away or submits anything — it just makes the page
    ask for more data, which the response handler then catches. The single most
    universal trigger; a lot of the web only fetches its data on scroll.

    Uses a programmatic scrollTo(bottom) — that reliably fires the `scroll` events
    infinite-scroll libraries listen on (a raw mouse wheel often doesn't), and each
    step reaches the newly grown bottom to pull the next page."""
    for _ in range(max(0, steps)):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.mouse.wheel(0, 1200)   # nudge — some libs also watch wheel events
        except Exception:
            break
        page.wait_for_timeout(pause)


def capture(url: str, proxy: dict | None = None, wait_ms: int = 3500,
            headless: bool = True, challenge_wait_ms: int = 6000,
            interact: bool = True, scroll_steps: int = 6,
            scroll_pause: int = 1200, storage_state: str | None = None) -> CaptureResult:
    """Navigate `url` and return both the API candidates and the block evidence.

    `proxy` is a Camoufox proxy dict (from session.pick_proxy) or None for the
    native ISP IP. If a JS challenge (DataDome/Cloudflare "just a moment") is up
    after load, wait up to `challenge_wait_ms` for it to auto-solve before judging
    — Camoufox passes these if you let the challenge JS finish (the Prospector
    tactic). Blocked/not is decided from the *terminal* state, so a challenge that
    clears isn't a false positive. `discover()` is the thin candidates-only wrapper."""
    candidates: list[ApiCandidate] = []
    seen: set[str] = set()
    challenge_hosts: set[str] = set()

    def on_response(response):
        # This IS "the handler": Camoufox calls it for EVERY response automatically.
        u = response.url
        low = u.lower()
        # record challenge hosts seen (to *name* a block) and never treat the
        # interstitial's own JSON as a data candidate.
        is_block = False
        for b in _BLOCK_HOSTS:
            if b in low:
                challenge_hosts.add(b)
                is_block = True
        if is_block or u in seen or _is_noise(u):
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
    html = ""
    with launch(proxy=proxy, headless=headless, storage_state=storage_state) as page:
        page.on("response", on_response)          # register BEFORE navigating!
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=45000)
            nav_status = resp.status if resp else None
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)            # let lazy / on-scroll XHR fire
        try:
            title = page.title()
        except Exception:
            pass
        # patience: if a JS challenge is up, give it time to auto-solve before we
        # judge — poll the title until it stops looking like an interstitial.
        if _challenge_title(title) and challenge_wait_ms > 0:
            waited, step = 0, 1500
            while waited < challenge_wait_ms:
                page.wait_for_timeout(step)
                waited += step
                try:
                    title = page.title()
                except Exception:
                    pass
                if not _challenge_title(title):
                    break                          # challenge cleared → through
        # interaction pass: scroll to fire lazy / infinite-scroll / paginated XHR
        if interact and not _challenge_title(title):
            _autoscroll(page, scroll_steps, scroll_pause)
        try:
            final_url = page.url
            html = page.content()
        except Exception:
            pass

    # biggest data blob first — most likely the real listing/data endpoint
    candidates.sort(key=lambda c: c.size, reverse=True)

    # Always check for SSR-inlined data too: some sites fire an API for *part* of
    # the page (ads, suggestions) but server-render the main list into the HTML
    # (Vinted, most Next.js apps). Surfacing both gives the full picture.
    embedded = extract_embedded(html) if html else []

    # Decide blocked from the TERMINAL state, not a challenge that already cleared.
    # Real data captured → we're through, full stop. Otherwise a lingering challenge
    # title, or a hard status with no data, means blocked — name it from hosts seen.
    block: list[str] = []
    title_hit = _challenge_title(title)
    terminal_blocked = bool(title_hit) or (nav_status in (403, 429, 503) and not candidates)
    if terminal_blocked:
        block = [f"host:{h}" for h in sorted(challenge_hosts)]
        if title_hit:
            block.append(f"title:{title_hit}")
        if nav_status in (403, 429, 503):
            block.append(f"status:{nav_status}")

    return CaptureResult(candidates, nav_status, final_url, title, block, embedded)


def discover(url: str, proxy: dict | None = None, wait_ms: int = 3500,
             headless: bool = True) -> list[ApiCandidate]:
    """Load `url` and return the internal-data API candidates, biggest first.
    Thin wrapper over `capture()` for callers that only want the endpoints."""
    return capture(url, proxy=proxy, wait_ms=wait_ms, headless=headless).candidates
