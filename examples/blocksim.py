"""Block simulator — trigger each self-heal lever on command, and watch it react.

    python examples/blocksim.py --ip          # 403 → ip_block → rotate exit
    python examples/blocksim.py --rate         # 429+Retry-After → rate_limit → rotate
    python examples/blocksim.py --session      # 412 → session_block → drop session, keep fp
    python examples/blocksim.py --transient     # "Just a moment" → transient → patience
    python examples/blocksim.py --auth          # redirect to login → terminal (needs human)
    python examples/blocksim.py                 # UNKNOWN block → cost-ladder fallback (relaunch)

A local server serves the chosen block for the first N hits, then clears to a real data
page — so you watch the loop DETECT the block (vendor-free), pick the truth-table lever,
and RECOVER. `--auth` never clears (it's terminal — a human is needed), which shows the
loop stop cleanly instead of spinning. No args = an unclassifiable block, so you see how
it reacts to something it can't name (falls back to the cost-ordered ladder).
"""
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hydra import stealth

_DATA = b'{"items":[{"id":1,"price":9.99},{"id":2,"price":19.99}]}'
_PAGE = (b"<!doctype html><title>ok</title><body>data"
         b"<script>fetch('/api/data').then(r=>r.json())</script></body>")
_LOGIN = b"<!doctype html><title>Login</title><body>please sign in</body>"

_state = {"mode": "unknown", "block_for": 2, "hits": 0}


def _block(h):
    m = _state["mode"]
    if m == "ip":
        h.send_response(403); h.send_header("content-type", "text/html"); h.end_headers()
        h.wfile.write(b"<title>nope</title>forbidden")
    elif m == "rate":
        h.send_response(429); h.send_header("retry-after", "2"); h.send_header("server", "cloudflare")
        h.send_header("content-type", "text/html"); h.end_headers()
        h.wfile.write(b"<title>slow down</title>too many requests")
    elif m == "session":
        h.send_response(412); h.send_header("content-type", "text/html"); h.end_headers()
        h.wfile.write(b"<title>precondition</title>session/token required")
    elif m == "transient":
        h.send_response(200); h.send_header("content-type", "text/html"); h.end_headers()
        h.wfile.write(b"<title>Just a moment...</title>checking your browser")
    elif m == "auth":                                   # 302 → /login (never clears — human needed)
        h.send_response(302); h.send_header("location", "/login"); h.end_headers()
    else:                                               # unknown: 200, tiny body, no data, no challenge
        h.send_response(200); h.send_header("content-type", "text/html"); h.end_headers()
        h.wfile.write(b"<title>x</title>blocked")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/data"):
            self.send_response(200); self.send_header("content-type", "application/json")
            self.end_headers(); self.wfile.write(_DATA); return
        if self.path.startswith("/login"):
            self.send_response(200); self.send_header("content-type", "text/html")
            self.end_headers(); self.wfile.write(_LOGIN); return
        if self.path != "/":
            self.send_response(404); self.end_headers(); return
        _state["hits"] += 1
        if _state["mode"] == "auth" or _state["hits"] <= _state["block_for"]:
            _block(self)                                # still blocking (auth never clears)
        else:
            self.send_response(200); self.send_header("content-type", "text/html")
            self.end_headers(); self.wfile.write(_PAGE)  # cleared → real data


def main() -> None:
    ap = argparse.ArgumentParser(description="trigger each self-heal lever on command")
    for m in ("ip", "rate", "session", "transient", "auth"):
        ap.add_argument(f"--{m}", action="store_const", const=m, dest="mode")
    ap.add_argument("--block-for", type=int, default=2, help="hits blocked before it clears")
    ap.add_argument("--port", type=int, default=8891)
    args = ap.parse_args()
    _state["mode"] = args.mode or "unknown"
    _state["block_for"] = args.block_for

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"\n=== simulating block: {_state['mode'].upper()} "
          f"({'terminal — never clears' if _state['mode']=='auth' else f'clears after {args.block_for} hits'}) ===")

    def on_attempt(att):
        d = getattr(att, "detv", None)
        cls = d.block_class if d else "?"
        print(f"  attempt {att.n} [{att.via}]  detected={cls:14} →  {att.move}")

    r = stealth.resilient_capture(url, max_attempts=5, base_backoff=0.3,
                                  challenge_wait_ms=1500, interact=False, on_attempt=on_attempt)
    srv.shutdown()
    print(f"\nRESULT: {'RECOVERED ✓ (got the data)' if r.recovered else 'stopped — not self-healable'}"
          f"  ·  {r.tries} attempt(s)\n")


if __name__ == "__main__":
    main()
