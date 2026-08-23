"""Camoufox session — the stealth base Hydra sits on. (v0.1)

Three proxy modes, chosen by the caller:
  - native   : no proxy — your own ISP IP. Camoufox aligns geoip to it (geoip=True).
  - file     : a proxy picked from proxies.txt (ip:port:user:pass per line).
  - explicit : a proxy string/dict you pass in.

Patterns ported from the corner-odds engine (Sisal/Eurobet recon). Two notes kept:
  - **geoip is aligned to the proxy's EXIT IP** (not True) when proxied, so the
    fingerprint's timezone/locale matches where the traffic appears to come from.
  - **Do NOT add `page.route("**/*")` resource blocking** — it round-trips every
    request through Python and serializes heavy SPA loads past the timeout
    (measured: Sisal went 0 → 10/14 timeouts with it on). Camoufox's built-in
    uBlock already drops ads/trackers.

Not ported: the preemptive-auth ProxyAuthRelay. If a proxy provider throws
`NS_ERROR_PROXY_BAD_GATEWAY` (407-vs-502 auth quirk), port it from corner-odds.
"""
from __future__ import annotations

import os
import random
from contextlib import contextmanager

from camoufox.sync_api import Camoufox


def load_proxies(path: str | None = None) -> list[dict]:
    """Parse `ip:port:user:pass` lines into Camoufox proxy dicts. Silent if absent."""
    path = path or os.getenv("PROXIES_FILE") or os.path.join(os.getcwd(), "proxies.txt")
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                p = line.split(":")
                if len(p) == 4:
                    out.append({"server": f"http://{p[0]}:{p[1]}",
                                "username": p[2], "password": p[3]})
                elif len(p) == 2:
                    out.append({"server": f"http://{p[0]}:{p[1]}"})
    except FileNotFoundError:
        pass
    return out


def parse_proxy(spec: str | dict | None) -> dict | None:
    """Turn an explicit proxy into a Camoufox dict.
    Accepts 'ip:port:user:pass', 'ip:port', 'http://ip:port', or a dict."""
    if not spec:
        return None
    if isinstance(spec, dict):
        return spec
    if spec.startswith("http"):
        return {"server": spec}
    p = spec.split(":")
    if len(p) == 4:
        return {"server": f"http://{p[0]}:{p[1]}", "username": p[2], "password": p[3]}
    if len(p) == 2:
        return {"server": f"http://{p[0]}:{p[1]}"}
    return None


def pick_proxy(mode: str = "native", *, proxies_file: str | None = None,
               explicit: str | dict | None = None) -> dict | None:
    """Resolve a proxy per mode: 'native'->None · 'file'->random from proxies.txt ·
    'explicit'->parse_proxy(explicit)."""
    if mode == "native":
        return None
    if mode == "explicit":
        return parse_proxy(explicit)
    if mode == "file":
        proxies = load_proxies(proxies_file)
        return random.choice(proxies) if proxies else None
    raise ValueError(f"unknown proxy mode: {mode!r}")


def _geo_align(host: str | None):
    """The geoip value for an exit `host`. If it's a literal IP (a static-exit pool, where the host
    IS the exit) → align straight to it, no lookup. If it's a HOSTNAME (a rotating-gateway proxy like
    `gw.provider.io:10000`, where the hostname is NOT the exit — the real US/residential IP is chosen
    server-side per connection) → return True so Camoufox detects the actual exit IP *through the
    proxy* and aligns to that. Passing the hostname straight to geoip throws 'Invalid IP address'."""
    if not host:
        return True
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return host                      # static exit IP → align directly
    except ValueError:
        return True                      # gateway hostname → let Camoufox find the exit IP


def _geoip_for(proxy: dict | None):
    """Align geoip to the proxy's exit IP so timezone/locale match. True for native."""
    if not proxy:
        return True
    host = proxy["server"].split("://", 1)[-1].rsplit(":", 1)[0]
    return _geo_align(host)


@contextmanager
def launch(proxy: dict | None = None, headless: bool = True,
          storage_state: str | None = None, humanize=True, geoip=None):
    """Yield a fresh Camoufox page. `proxy` is a dict (from pick_proxy / parse_proxy)
    or None for the native ISP IP. `storage_state` is a path to a saved session
    (cookies + localStorage from `hydra login`). `humanize` is True, or a float =
    max cursor-movement duration in seconds. `geoip` overrides the alignment — pass the
    EXIT host when routing through a localhost relay, so geoip matches the exit, not
    localhost; default None → align to `proxy`. Fresh browser per call."""
    with Camoufox(headless=headless, humanize=humanize,
                  geoip=(geoip if geoip is not None else _geoip_for(proxy)), proxy=proxy,
                  os=["windows", "macos"]) as browser:
        if storage_state:
            ctx = browser.new_context(storage_state=storage_state)
            page = ctx.new_page()
        else:
            page = browser.new_page()
        yield page
