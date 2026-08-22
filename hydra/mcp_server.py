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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp = MCPServer("hydra")
_S = {"h": None}

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


def _proxies():
    """Native IP by DEFAULT — a proxy is opt-IN. Only routes through a file when HYDRA_PROXIES
    points at one (relative paths resolve against the repo root)."""
    raw = (os.environ.get("HYDRA_PROXIES") or "").strip()
    if not raw or raw.lower() in ("none", "off", "0", "no", "native"):
        return None                                           # unset/empty/opt-out → native IP
    p = raw if os.path.isabs(raw) else os.path.join(_ROOT, raw)
    return p if os.path.exists(p) else None


def _headful() -> bool:
    """Headless by DEFAULT — headful is opt-IN (HYDRA_HEADFUL=1), just to watch the browser."""
    return (os.environ.get("HYDRA_HEADFUL") or "").strip().lower() in ("1", "true", "yes", "on")


def _h() -> Hydra:
    """The one persistent session (lazily opened; self-heals; humanized behavior baked in)."""
    if _S["h"] is None:
        h = Hydra(proxies=_proxies(), headful=_headful())
        h.__enter__()
        _S["h"] = h
    return _S["h"]


def _safe(x: dict) -> dict:
    """A discovered endpoint WITHOUT any secret (never expose request_headers/cookies to the model)."""
    return {k: x[k] for k in ("url", "method", "status", "shape", "size", "auth", "fired_on") if k in x}


@mcp.tool()
@_pinned
def open_page(url: str) -> dict:
    """Open a URL in the persistent stealth session (self-heals past antibot / geo-lock) and
    return the page map: overlays to clear, scroll state, and ranked interactive elements."""
    h = _h()
    h.open(url, wait_ms=5500)
    h.wait_ready()                     # wait until the page stops changing before we map it
    return h.snapshot()


@mcp.tool()
@_pinned
def snapshot() -> dict:
    """Map the CURRENT page — overlays (dismiss these first), scroll {y, hasMore}, and the ranked
    elements (each {id, role, label, overlay}). Use the ids with click()/type_text(). No secrets."""
    return _h().snapshot()


@mcp.tool()
@_pinned
def click(id: int) -> dict:
    """Click an element by its snapshot id (humanized mouse) and capture any internal APIs the
    click fires. Returns {snapshot, new_endpoints} — new_endpoints is stripped of auth/headers."""
    h = _h()
    before = len(h.context)
    h.act(id, label=f"mcp:click:{id}")
    h.wait_ready()                     # a navigating click may redirect/repaint after act() returns
    return {"snapshot": h.snapshot(), "new_endpoints": [_safe(x) for x in h.context[before:]]}


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
