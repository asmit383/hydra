"""Prove the swappable relay: rotate the exit IP on a LIVE browser, no relaunch.

    python examples/relay_rotate.py        # needs proxies.txt (>=2 exits)

This is the truth table's *"rotate exit (relay), keep fp+session"* lever, demonstrated:
open one Camoufox browser through the relay, read the exit IP, swap the relay's
upstream to a second proxy, read the exit IP again — the IP changes while the browser
(fingerprint + session cookies) never restarts. That's IP as a HOT lever instead of the
nuclear relaunch that would burn the clearance cookie.

Exit IPs are masked in the output.
"""
import json
import pathlib
import time

from camoufox.sync_api import Camoufox

from hydra.relay import Relay


def _mask(ip: str) -> str:
    p = ip.split(".")
    return f"{p[0]}.x.x.{p[-1]}" if len(p) == 4 else "??"


def main() -> None:
    lines = [l.strip().split(":") for l in pathlib.Path("proxies.txt").read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    if len(lines) < 2:
        raise SystemExit("need >=2 exits in proxies.txt")
    p1, p2 = lines[0], lines[1]

    relay = Relay()
    relay.set_upstream(p1[0], p1[1], p1[2], p1[3])
    relay.start()
    print(f"relay on {relay.server_url()}")

    with Camoufox(headless=True, humanize=True, geoip=True,
                  proxy={"server": relay.server_url()}, os=["windows", "macos"]) as browser:
        page = browser.new_page()
        page.goto("https://api.ipify.org?format=json", timeout=40000)
        ip1 = json.loads(page.inner_text("body"))["ip"]
        page.context.add_cookies([{"name": "hydra_test", "value": "keep",
                                   "url": "https://api.ipify.org"}])
        ua1 = page.evaluate("navigator.userAgent")

        relay.set_upstream(p2[0], p2[1], p2[2], p2[3])   # ROTATE — drops tunnels, no relaunch
        time.sleep(1.5)

        page.goto("https://api.ipify.org?format=json", timeout=40000)
        ip2 = json.loads(page.inner_text("body"))["ip"]
        ua2 = page.evaluate("navigator.userAgent")
        cookie_ok = any(c["name"] == "hydra_test" for c in page.context.cookies())

    relay.stop()
    print(f"exit before/after        : {_mask(ip1)}  →  {_mask(ip2)}")
    print(f"IP rotated (NO relaunch) : {ip1 != ip2}")
    print(f"fingerprint preserved    : {ua1 == ua2}")
    print(f"session cookie preserved : {cookie_ok}")


if __name__ == "__main__":
    main()
