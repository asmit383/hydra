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

from hydra.discover import discover
from hydra.session import pick_proxy


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
        candidates = discover(args.url, proxy=proxy, headless=not args.headful)
        print(json.dumps([c.__dict__ for c in candidates], default=str, indent=2))
        return 0 if candidates else 1

    print(f"→ discovering internal APIs on {args.url}  (via {via}) ...\n")
    candidates = discover(args.url, proxy=proxy, headless=not args.headful)

    if not candidates:
        print("no internal JSON API found — the site may be server-rendered "
              "(the HTML *is* the data), or the API fires on interaction (v0.1.1).")
        return 1

    print(f"found {len(candidates)} candidate endpoint(s), biggest first:\n")
    for i, c in enumerate(candidates, 1):
        print(f"[{i}] {c.method} {c.url}")
        print(f"    status {c.status} · {c.size:,} bytes · {c.shape}")
        auth = [k for k in c.request_headers
                if k.lower() in ("authorization", "x-api-key", "cookie", "x-algolia-api-key")]
        if auth:
            print(f"    auth headers present: {auth}")
        print(f"    sample: {json.dumps(c.sample, default=str)[:160]}")
        print()
    return 0


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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
