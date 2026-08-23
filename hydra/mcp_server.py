"""Hydra as an MCP server — drive a persistent stealth session from any MCP client (e.g. Claude
Code). The **client is the brain**: it calls snapshot/click/scroll, so there's no separate LLM
API cost (no key to burn — the model already in the loop does the deciding).

Security: tool results NEVER include request headers, cookies, or tokens — only a stripped view
(url · method · status · shape · size · auth-summary · fired_on). `fetch` returns the live DATA
(that's the point — the odds), but the auth used to get it stays server-side and is never shown.

Setup:
  pip install mcp
  # register with Claude Code (user scope):
  claude mcp add hydra -- /path/to/hydra/.venv/bin/python -m hydra.mcp_server
  # or project scope via .mcp.json (see README)

Then, in a session, drive it: open_page(url) → snapshot() → click(id) / scroll() → endpoints() →
fetch(url_contains). One persistent, self-healing browser behind the tools.
"""
import concurrent.futures
import functools
import json
import os

from mcp.server import MCPServer
from mcp.server.mcpserver import Image

from hydra import Hydra
from hydra.discover import _challenge_title

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp = MCPServer("hydra")
_S = {"h": None}
# RUNTIME config (set via the configure() tool, not the launch env). None = fall back to env/default.
_CFG = {"proxies": None, "headful": None}

# Playwright's SYNC api is thread-affine: the browser/page objects belong to the thread that
# created them. But this MCP framework runs each sync tool via anyio.to_thread — an arbitrary
# worker thread PER CALL. So a call that lands on a different worker than the one that opened the
# session hits "no running event loop". Fix: pin the whole session (create + every call) to ONE
# dedicated thread, and marshal every tool onto it.
_LOOP = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hydra-session")


def _pinned(fn):
    """Run `fn` on the single session thread (Playwright objects live there) and block for it."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return _LOOP.submit(lambda: fn(*a, **k)).result()
    return wrapper


def _resolve_proxies(raw):
    """A proxies value → a file path (relative resolves against the repo root) or None (native IP).
    Empty / 'none'/'off'/'native' → native. `None` here means 'not set' → caller falls back to env."""
    raw = (raw or "").strip()
    if not raw or raw.lower() in ("none", "off", "0", "no", "native"):
        return None
    p = raw if os.path.isabs(raw) else os.path.join(_ROOT, raw)
    return p if os.path.exists(p) else None


def _cfg_proxies():
    """Effective proxies: the runtime configure() override if set, else HYDRA_PROXIES env, else native."""
    raw = _CFG["proxies"] if _CFG["proxies"] is not None else os.environ.get("HYDRA_PROXIES")
    return _resolve_proxies(raw)


def _cfg_headful() -> bool:
    """Effective headful: the runtime override if set, else HYDRA_HEADFUL env, else headless."""
    if _CFG["headful"] is not None:
        return bool(_CFG["headful"])
    return (os.environ.get("HYDRA_HEADFUL") or "").strip().lower() in ("1", "true", "yes", "on")


def _h() -> Hydra:
    """The one persistent session (lazily opened; self-heals; humanized behavior baked in). Built
    from the current runtime config — change it with configure() and the next open_page relaunches."""
    if _S["h"] is None:
        h = Hydra(proxies=_cfg_proxies(), headful=_cfg_headful())
        h.__enter__()
        _S["h"] = h
    return _S["h"]


def _safe(x: dict) -> dict:
    """A discovered endpoint WITHOUT any secret (never expose request_headers/cookies to the model)."""
    return {k: x[k] for k in ("url", "method", "status", "shape", "size", "auth", "fired_on") if k in x}


def _block(h):
    """Thin block-sentinel over the CURRENT page. snapshot()/click() have no oracle to run full
    classify(), so surface only POSITIVE markers: a captcha widget on a challenge/thin page (→
    hard_verify, the brain's job), or an interstitial title (→ transient, the server heals it).
    Returns None on a normal page (no false 'blocked' — we only flag what we can see)."""
    try:
        page = h.session.page
        info = page.evaluate("""() => ({
            widget: ['.h-captcha', '.g-recaptcha', '#cf-turnstile', 'iframe[src*="hcaptcha.com"]',
                     'iframe[src*="recaptcha"]', 'iframe[src*="challenges.cloudflare.com"]',
                     'iframe[src*="turnstile"]'].some(s => document.querySelector(s)),
            len: document.body ? document.body.innerText.length : 0 })""")
        ct = _challenge_title(page.title() or "")
        if info["widget"] and (bool(ct) or info["len"] < 2000):     # widget + wall context
            return {"class": "hard_verify", "self_heal": False,
                    "needs": "YOU — solve it (or a human/solver)", "signal": "captcha wall"}
        if ct:
            return {"class": "transient", "self_heal": True,
                    "needs": "server auto-heals (patience)", "signal": "challenge interstitial"}
    except Exception:
        pass
    return None


@mcp.tool()
@_pinned
def configure(proxies: str | None = None, headful: bool | None = None) -> dict:
    """Set the stealth session config at RUNTIME — no file edits, no reconnect. `proxies` = a
    proxy-pool file path (e.g. 'proxies.txt') or 'none' for the native IP; `headful` = watch the
    browser (True) or run headless. Applies to the NEXT open_page (the current session is closed so
    it relaunches with the new config). Call with no args to just read the current config."""
    if proxies is not None:
        _CFG["proxies"] = proxies
    if headful is not None:
        _CFG["headful"] = bool(headful)
    if (proxies is not None or headful is not None) and _S["h"] is not None:
        try:                                    # drop the old session → next open relaunches w/ new cfg
            _S["h"].__exit__(None, None, None)
        finally:
            _S["h"] = None
    return {"proxies": _CFG["proxies"] or "native", "headful": _cfg_headful(),
            "note": "applies on the next open_page"}


@mcp.tool()
@_pinned
def open_page(url: str) -> dict:
    """Open a URL in the persistent stealth session and return the page map. MECHANICALLY
    self-heals a real block — a 403/429/503/401/412, a JS challenge, or a clearance-cookie gate
    makes it escalate the cost ladder (patience → rotate exit → drop session → relaunch),
    re-navigating on a fresh exit each round, before it hands you the page. A thin-but-fine page
    (200, no API) is NOT treated as a block. If a block still stands, the map carries a `block`
    verdict {class, self_heal, needs}: a captcha wall → `hard_verify` (the brain must solve it); a
    mechanical block that outlived the ladder → its class + what to try next (retry / change exit)."""
    h = _h()
    _cands, v = h.open_healed(url, wait_ms=5500)   # navigate + mechanical self-heal (rotate/drop/relaunch)
    h.wait_ready()                                 # let the (possibly healed) page settle before mapping
    snap = h.snapshot()
    if v is not None:                              # a real mechanical block outlived the whole ladder
        snap["block"] = {"class": v.block_class, "self_heal": True, "healed": False,
                         "needs": f"escalated the {v.lever} ladder — still blocked; retry later, "
                                  "change exit (configure proxies=…), or pick another target",
                         "signal": v.signal}
    b = _block(h)                                  # captcha/challenge wall → hard_verify (brain/solver)
    if b:
        snap["block"] = b                          # takes precedence — it's the human-actionable one
    return snap


@mcp.tool()
@_pinned
def snapshot() -> dict:
    """Map the CURRENT page — overlays (dismiss these first), scroll {y, hasMore}, and the ranked
    elements (each {id, role, label, overlay}). Use the ids with click()/type_text(). No secrets.
    Carries a `block` verdict if a captcha/challenge is up (hard_verify = you must solve it)."""
    h = _h()
    snap = h.snapshot()
    b = _block(h)
    if b:
        snap["block"] = b
    return snap


@mcp.tool()
@_pinned
def click(id: int) -> dict:
    """Click an element by its snapshot id (humanized mouse) and capture any internal APIs the
    click fires. Returns {snapshot, new_endpoints} — new_endpoints is stripped of auth/headers."""
    h = _h()
    before = len(h.context)
    h.act(id, label=f"mcp:click:{id}")
    h.wait_ready()                     # a navigating click may redirect/repaint after act() returns
    snap = h.snapshot()
    b = _block(h)                      # did the click walk us into a captcha/challenge?
    if b:
        snap["block"] = b
    return {"snapshot": snap, "new_endpoints": [_safe(x) for x in h.context[before:]]}


@mcp.tool()
@_pinned
def click_at(x: int, y: int) -> dict:
    """Click at VIEWPORT pixel (x, y) with a humanized mouse — the ACT companion to screenshot():
    reach things the structural map CAN'T (a captcha checkbox in a cross-origin iframe, a
    Google-Places autocomplete item, a canvas widget). Prefer click(id) when the element is in the
    map. Coords are viewport CSS pixels — the SAME space as snapshot()'s `at`. If you read a target
    off a screenshot on a HiDPI display, divide the image coords by devicePixelRatio (=
    screenshot_width / snapshot viewport width). Returns {snapshot, new_endpoints}."""
    h = _h()
    before = len(h.context)
    h.act_xy(x, y, label=f"mcp:click_at:{x},{y}")
    h.wait_ready()
    snap = h.snapshot()
    b = _block(h)
    if b:
        snap["block"] = b
    return {"snapshot": snap, "new_endpoints": [_safe(e) for e in h.context[before:]]}


@mcp.tool()
@_pinned
def scroll(steps: int = 3) -> dict:
    """Scroll down (humanized) to reveal more content, then return the updated page map."""
    h = _h()
    h.scroll(steps=steps)
    return h.snapshot()


@mcp.tool()
@_pinned
def type_text(id: int, text: str) -> dict:
    """Type `text` into a field by its snapshot id (per-keystroke human timing). Returns the map."""
    h = _h()
    h.type(id, text)
    return h.snapshot()


@mcp.tool()
@_pinned
def screenshot(full_page: bool = False) -> list:
    """VISION FALLBACK — a picture of the current page. Prefer snapshot() first (cheaper, and it
    gives clickable ids); reach for this when the map isn't enough: snapshot() came back empty or
    ambiguous, the content is in a cross-origin iframe / canvas / custom widget, or you want to
    VISUALLY VERIFY an action landed (e.g. did the text go into the right field?)."""
    png = _h().screenshot(full_page=full_page)
    return [Image(data=png, format="jpeg"),
            "Vision fallback — screenshot of the current page. Use snapshot() for clickable ids."]


@mcp.tool()
@_pinned
def endpoints() -> dict:
    """Every internal API discovered so far this session, stripped of headers/tokens.
    Returns {count, endpoints:[{url,method,status,shape,size,auth,fired_on}]}."""
    eps = [_safe(x) for x in _h().context]
    return {"count": len(eps), "endpoints": eps}


@mcp.tool()
@_pinned
def streams() -> dict:
    """Live WebSocket / SSE feeds discovered this session — where PUSH-based sites (sportsbooks,
    tickers, trading) stream their real DATA (odds, prices) instead of a REST endpoint. The WS
    companion to endpoints() (which is REST-only). Each feed: url + the client's subscribe frames
    (how to replay it) + a sample of received frames (the data) + how many frames have arrived."""
    st = _h().streams
    return {"count": len(st),
            "streams": [{"kind": s["kind"], "url": s["url"], "subscribe_frames": s["sent"],
                         "received_sample": s["received"], "frames_seen": s["n_received"]}
                        for s in st]}


@mcp.tool()
@_pinned
def fetch(url_contains: str) -> dict:
    """Replay a discovered endpoint IN-SESSION (warm cookie; auth stays server-side) and return a
    sample of the live data. Match by a substring of the endpoint URL (see endpoints())."""
    h = _h()
    cand = next((x for x in h.context if url_contains in x["url"]), None)
    if not cand:
        return {"error": f"no captured endpoint matching {url_contains!r} — call endpoints() first"}
    data = h.fetch(cand)
    body = data.get("json", data.get("text"))
    return {"url": cand["url"], "status": data.get("status"),
            "sample": json.dumps(body, ensure_ascii=False)[:4000] if body is not None else None}


@mcp.tool()
@_pinned
def reset() -> str:
    """Close the session — a fresh identity + persona is minted on the next call."""
    if _S["h"] is not None:
        try:
            _S["h"].__exit__(None, None, None)
        finally:
            _S["h"] = None
    return "session closed"


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_ROOT, ".env"))
    except Exception:
        pass
    mcp.run()


if __name__ == "__main__":
    main()
