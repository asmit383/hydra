"""Battle-test harness — run capture over many real sites, report where it breaks.

    python examples/battle_test.py urls.txt
    python examples/battle_test.py urls.txt --proxies-file proxies.txt

`urls.txt` is one URL per line (# comments allowed). For each URL it runs a
capture and records the outcome — how many API endpoints / SSR blobs / live
streams were found, or an ERROR + which exception — plus wall-clock time. Ends
with a summary so you can see, across a big diverse list, what fraction works,
what comes up empty, and what crashes. That's the "does it hold up in the wild"
test, separate from the deterministic unit suite.
"""
import argparse
import random
import time

from hydra.discover import capture
from hydra.session import load_proxies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", help="file with one URL per line")
    ap.add_argument("--proxies-file", help="rotate a random proxy per URL")
    ap.add_argument("--no-interact", action="store_true")
    args = ap.parse_args()

    with open(args.urls) as fh:
        urls = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    pool = load_proxies(args.proxies_file) if args.proxies_file else []

    tally = {"ok": 0, "empty": 0, "error": 0}
    slow = []
    print(f"battle-testing {len(urls)} url(s)\n" + "-" * 72)
    for u in urls:
        proxy = random.choice(pool) if pool else None
        t0 = time.time()
        try:
            r = capture(u, proxy=proxy, interact=not args.no_interact)
            found = len(r.candidates) + len(r.embedded) + len(r.streams)
            outcome = f"{len(r.candidates)} api · {len(r.embedded)} ssr · {len(r.streams)} ws"
            status = "ok" if found else "empty"
        except Exception as e:                        # a crash is the thing we hunt
            outcome = f"{type(e).__name__}: {str(e)[:50]}"
            status = "error"
        dt = time.time() - t0
        tally[status] += 1
        if dt > 40:
            slow.append((u, dt))
        print(f"  {status:5}  {dt:5.1f}s  {u[:52]:52}  {outcome}")

    print("-" * 72)
    print(f"ok {tally['ok']} · empty {tally['empty']} · error {tally['error']}"
          f"  (of {len(urls)})")
    if slow:
        print(f"slow (>40s): {len(slow)} — " + ", ".join(u[:40] for u, _ in slow[:5]))


if __name__ == "__main__":
    main()
