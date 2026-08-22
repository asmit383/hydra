"""MCP server — tool registration + the security-critical stripping (browser-free).
Skipped if the optional `mcp` extra isn't installed."""
import asyncio

import pytest

pytest.importorskip("mcp")


def test_mcp_tools_registered():
    from hydra.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"open_page", "snapshot", "click", "scroll", "type_text",
            "endpoints", "fetch", "reset"} <= names


def test_safe_never_leaks_headers_or_body():
    from hydra.mcp_server import _safe
    x = {"url": "/a", "method": "GET", "status": 200, "shape": "dict", "size": 9,
         "auth": ["cookie"], "fired_on": "load",
         "request_headers": {"Cookie": "SECRET", "Authorization": "Bearer x"}, "post_data": "q{}"}
    s = _safe(x)
    assert "request_headers" not in s and "post_data" not in s      # secrets never reach the model
    assert s == {"url": "/a", "method": "GET", "status": 200, "shape": "dict",
                 "size": 9, "auth": ["cookie"], "fired_on": "load"}  # only the safe summary
