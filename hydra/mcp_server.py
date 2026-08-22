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
import json
import os

from mcp.server import MCPServer

from hydra import Hydra

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp = MCPServer("hydra")
_S = {"h": None}


def _proxies():
    p = os.environ.get("HYDRA_PROXIES") or "proxies.txt"
    p = p if os.path.isabs(p) else os.path.join(_ROOT, p)
    return p if os.path.exists(p) else None


def _h() -> Hydra:
    """The one persistent session (lazily opened; self-heals; humanized behavior baked in)."""
    if _S["h"] is None:
        h = Hydra(proxies=_proxies(),
                  headful=os.environ.get("HYDRA_HEADFUL", "1") not in ("", "0", "false"))
        h.__enter__()
        _S["h"] = h
    return _S["h"]


def _safe(x: dict) -> dict:
    """A discovered endpoint WITHOUT any secret (never expose request_headers/cookies to the model)."""
    return {k: x[k] for k in ("url", "method", "status", "shape", "size", "auth", "fired_on") if k in x}


@mcp.tool()
def open_page(url: str) -> dict:
    """Open a URL in the persistent stealth session (self-heals past antibot / geo-lock) and
    return the page map: overlays to clear, scroll state, and ranked interactive elements."""
    h = _h()
    h.open(url, wait_ms=5500)
    return h.snapshot()


@mcp.tool()
def snapshot() -> dict:
    """Map the CURRENT page — overlays (dismiss these first), scroll {y, hasMore}, and the ranked
    elements (each {id, role, label, overlay}). Use the ids with click()/type_text(). No secrets."""
    return _h().snapshot()


@mcp.tool()
def click(id: int) -> dict:
    """Click an element by its snapshot id (humanized mouse) and capture any internal APIs the
    click fires. Returns {snapshot, new_endpoints} — new_endpoints is stripped of auth/headers."""
    h = _h()
    before = len(h.context)
    h.act(id, label=f"mcp:click:{id}")
    return {"snapshot": h.snapshot(), "new_endpoints": [_safe(x) for x in h.context[before:]]}


@mcp.tool()
def scroll(steps: int = 3) -> dict:
    """Scroll down (humanized) to reveal more content, then return the updated page map."""
    h = _h()
    h.scroll(steps=steps)
    return h.snapshot()


@mcp.tool()
def type_text(id: int, text: str) -> dict:
    """Type `text` into a field by its snapshot id (per-keystroke human timing). Returns the map."""
    h = _h()
    h.type(id, text)
    return h.snapshot()


@mcp.tool()
def endpoints() -> list:
    """Every internal API discovered so far this session, stripped of headers/tokens."""
    return [_safe(x) for x in _h().context]


@mcp.tool()
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
