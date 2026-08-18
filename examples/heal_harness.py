"""Controlled self-heal demo target — blocks the first hits, then serves data.

    python examples/heal_harness.py 8899          # start it (leave running)
    hydra capture http://localhost:8899/ --attempts 4    # watch it heal

Real antibot blocks are PROBABILISTIC (StockX/Zillow pass clean; Crunchbase is a
coin-flip), so you can't rely on a live site to block on cue for a demo. This gives
a deterministic block-then-clear so the heal cycle is reproducible:

  "/"  first 2 doc hits -> 429 + Retry-After  (rate-limit → detector: rate_limit,
                                               lever rotate_exit / backoff)
       3rd hit onward    -> 200 HTML that fetches /api/data (a real data channel)
  "/api/data"           -> 200 JSON  (oracle goes GREEN → recovered)

So: attempt 1 → 429 (blocked, why=rate_limit) · attempt 2 → 429 · attempt 3 →
200 + data → clean. The terminal trace shows the whole detect → lever → recover cycle.
"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_hits = {"doc": 0}
_PAGE = (b"<!doctype html><title>heal demo</title><body>loading\xe2\x80\xa6"
         b"<script>fetch('/api/data').then(r=>r.json())"
         b".then(d=>document.body.dataset.n=d.items.length)</script></body>")
_DATA = b'{"items":[{"id":1,"price":9.99},{"id":2,"price":19.99},{"id":3,"price":29.99}]}'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/data"):                 # the data channel
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(_DATA)
            return
        if self.path != "/":                                  # favicon etc. — ignore
            self.send_response(404); self.end_headers()
            return
        _hits["doc"] += 1
        if _hits["doc"] <= 2:                                 # first 2 doc hits → rate-limit
            self.send_response(429)
            self.send_header("retry-after", "1")
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<title>Too Many Requests</title>rate limited")
            return
        self.send_response(200)                               # cleared → serve the page
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(_PAGE)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"heal harness on http://localhost:{port}/  (429 x2 → then 200 + data)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
