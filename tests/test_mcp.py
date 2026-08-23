"""MCP server — tool registration + the security-critical stripping (browser-free).
Skipped if the optional `mcp` extra isn't installed."""
import asyncio

import pytest

pytest.importorskip("mcp")


def test_mcp_tools_registered():
    from hydra.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"open_page", "snapshot", "click", "click_at", "scroll", "type_text",
            "endpoints", "fetch", "streams", "reset", "screenshot", "configure"} <= names


def test_streams_tool_returns_safe_ws_view():
    import hydra.mcp_server as m
    m._S["h"] = type("H", (), {"streams": [
        {"kind": "websocket", "url": "wss://x/odds", "sent": ["sub tennis"],
         "received": ["Djokovic 1.42|Nadal 3.10"], "n_received": 42}]})()
    try:
        out = m.streams()
        s = out["streams"][0]
        assert out["count"] == 1 and s["url"] == "wss://x/odds" and s["frames_seen"] == 42
        assert s["subscribe_frames"] == ["sub tennis"]
        assert s["received_sample"] == ["Djokovic 1.42|Nadal 3.10"]
    finally:
        m._S["h"] = None


def test_configure_sets_runtime_proxy_and_headful():
    from hydra.mcp_server import _CFG, _cfg_proxies, configure
    try:
        out = configure(proxies="proxies.txt", headful=True)    # runtime, no env / file edit
        assert _CFG["proxies"] == "proxies.txt" and _CFG["headful"] is True
        assert out["headful"] is True and out["proxies"] == "proxies.txt"
        configure(proxies="none")                               # explicit native
        assert _cfg_proxies() is None
    finally:
        _CFG["proxies"], _CFG["headful"] = None, None           # don't leak into other tests


def test_open_page_routes_through_the_healing_navigate():
    """The MCP navigate MUST go through open_healed() — the mechanical self-heal loop — not the
    bare open(). This is how an agent driving via MCP gets rotate/drop/relaunch at all."""
    import inspect

    import hydra.mcp_server as m
    src = inspect.getsource(m)
    assert "open_healed" in src                         # navigate self-heals
    assert "h.open(url" not in src                      # …not the un-healed bare navigate


def test_pinned_runs_all_calls_on_one_thread():
    """Regression: Playwright's sync API is thread-affine, but the MCP framework dispatches each
    sync tool onto an arbitrary anyio worker thread. `_pinned` must funnel EVERY call onto the one
    session thread — else a call landing on a different worker hits 'no running event loop'."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from hydra.mcp_server import _pinned

    @_pinned
    def where_am_i():
        return threading.get_ident()

    # call from many DISTINCT caller threads (mimics anyio.to_thread's per-call worker)
    with ThreadPoolExecutor(max_workers=8) as pool:
        session_threads = set(pool.map(lambda _: where_am_i(), range(40)))
    caller = where_am_i()                       # and from the main thread

    assert len(session_threads) == 1                       # all work ran on ONE session thread
    assert session_threads == {caller}                     # …the same one every time
    assert caller != threading.get_ident()                 # …and it's NOT the calling thread


def test_safe_never_leaks_headers_or_body():
    from hydra.mcp_server import _safe
    x = {"url": "/a", "method": "GET", "status": 200, "shape": "dict", "size": 9,
         "auth": ["cookie"], "fired_on": "load",
         "request_headers": {"Cookie": "SECRET", "Authorization": "Bearer x"}, "post_data": "q{}"}
    s = _safe(x)
    assert "request_headers" not in s and "post_data" not in s      # secrets never reach the model
    assert s == {"url": "/a", "method": "GET", "status": 200, "shape": "dict",
                 "size": 9, "auth": ["cookie"], "fired_on": "load"}  # only the safe summary
