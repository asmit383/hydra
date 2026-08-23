"""MCP server — tool registration + the security-critical stripping (browser-free).
Skipped if the optional `mcp` extra isn't installed."""
import asyncio

import pytest

pytest.importorskip("mcp")


def test_mcp_tools_registered():
    from hydra.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"open_page", "snapshot", "click", "click_at", "scroll", "type_text",
            "endpoints", "fetch", "reset", "screenshot"} <= names


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
