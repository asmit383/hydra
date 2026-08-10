"""Hydra CLI — `hydra capture <url>`.

Installed as the `hydra` console script (see pyproject.toml [project.scripts]):
    pip install -e .
    hydra capture https://example.com
    hydra capture <url> --proxy explicit --proxy-str ip:port:user:pass
    hydra capture <url> --proxy file --proxies-file ./proxies.txt
"""
from __future__ import annotations

import argparse
import json
import sys

from hydra.discover import capture
from hydra.session import pick_proxy
from hydra.stealth import resilient_capture


def _add_proxy_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--proxy", choices=("native", "file", "explicit"), default="native",
                   help="native = your ISP IP (default); file = random from proxies.txt; "
                        "explicit = one proxy via --proxy-str")
    p.add_argument("--proxy-str", metavar="ip:port:user:pass",
                   help="proxy for --proxy explicit")
    p.add_argument("--proxies-file", metavar="PATH",
                   help="proxies.txt for --proxy file (or set PROXIES_FILE)")


def _cmd_capture(args: argparse.Namespace) -> int:
    proxy = pick_proxy(args.proxy, proxies_file=args.proxies_file, explicit=args.proxy_str)
    via = "native ISP IP" if proxy is None else proxy["server"]

    if args.json:
        r = capture(args.url, proxy=proxy, headless=not args.headful)
        out = {"candidates": [c.__dict__ for c in r.candidates],
               "embedded": [b.__dict__ for b in r.embedded]}
        print(json.dumps(out, default=str, indent=2))
        return 0 if (r.candidates or r.embedded) else 1

    print(f"→ discovering internal APIs on {args.url}  (via {via}) ...\n")
    r = capture(args.url, proxy=proxy, headless=not args.headful)

    if r.candidates:
        print(f"found {len(r.candidates)} candidate endpoint(s), biggest first:\n")
        for i, c in enumerate(r.candidates, 1):
            print(f"[{i}] {c.method} {c.url}")
            print(f"    status {c.status} · {c.size:,} bytes · {c.shape}")
            auth = [k for k in c.request_headers
                    if k.lower() in ("authorization", "x-api-key", "cookie", "x-algolia-api-key")]
            if auth:
                print(f"    auth headers present: {auth}")
            print(f"    sample: {json.dumps(c.sample, default=str)[:160]}")
            print()
        return 0

    if r.embedded:
        print("no XHR API — data is SSR-embedded in the HTML. Inlined blob(s), "
              "biggest record set first:\n")
        for i, b in enumerate(r.embedded, 1):
            print(f"[{i}] {b.kind} · {b.size:,} bytes")
            print(f"    {b.records_count} records at  {b.records_path}")
            print(f"    sample: {json.dumps(b.sample, default=str)[:160]}")
            print()
        return 0

    print("no internal JSON API found and no inlined data blob — the API may fire "
          "on interaction (scroll/click), or the page is behind a block.")
    return 1


def _cmd_heal(args: argparse.Namespace) -> int:
    strategy = "static" if args.static else args.strategy
    print(f"→ self-healing capture of {args.url}  "
          f"(strategy={strategy}, start={args.start}, up to {args.max_attempts} attempts)\n")

    def on_attempt(att):
        v = att.verdict
        print(f"  attempt {att.n} via {att.via}")
        if v.blocked:
            print(f"    ✗ BLOCKED · {v.kind} · leaked layer: {v.layer}")
            print(f"      {v.signal}")
            if att.move not in ("done", ""):
                print(f"      → {att.move}")
        else:
            print(f"    ✓ through · {att.n_candidates} candidate endpoint(s)")

    result = resilient_capture(
        args.url, proxies_file=args.proxies_file, explicit=args.proxy_str,
        start=args.start, strategy=strategy, max_attempts=args.max_attempts,
        headless=not args.headful, on_attempt=on_attempt)

    print()
    if result.recovered:
        print(f"RECOVERED in {result.tries} attempt(s) — "
              f"{len(result.candidates)} endpoint(s) found.")
        for i, c in enumerate(result.candidates[:5], 1):
            print(f"  [{i}] {c.method} {c.url}  ({c.size:,} B · {c.shape})")
        return 0
    print(f"NOT RECOVERED after {result.tries} attempt(s). "
          f"Last block: {result.attempts[-1].verdict.kind}.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydra",
        description="Stealth-automation primitive on Camoufox — find a site's internal API.")
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="discover the internal JSON API on a URL")
    cap.add_argument("url")
    cap.add_argument("--json", action="store_true", help="emit candidates as JSON")
    cap.add_argument("--headful", action="store_true", help="show the browser window")
    _add_proxy_flags(cap)
    cap.set_defaults(func=_cmd_capture)

    heal = sub.add_parser("heal", help="capture with self-healing through blocks (v0.2)")
    heal.add_argument("url")
    heal.add_argument("--strategy", choices=("adaptive", "rotate"), default="adaptive",
                      help="adaptive = patience-first, layer-driven ladder (default); "
                           "rotate = fresh exit every attempt (naive)")
    heal.add_argument("--start", choices=("native", "proxy"), default="native",
                      help="start on your native IP (default, usually cleanest) or a proxy")
    heal.add_argument("--static", action="store_true",
                      help="one exit, no escalation — the baseline to beat")
    heal.add_argument("--max-attempts", type=int, default=4)
    heal.add_argument("--proxy-str", metavar="ip:port:user:pass",
                      help="use one explicit proxy as the pool")
    heal.add_argument("--proxies-file", metavar="PATH",
                      help="proxies.txt for escalation (or set PROXIES_FILE)")
    heal.add_argument("--headful", action="store_true", help="show the browser window")
    heal.set_defaults(func=_cmd_heal)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
