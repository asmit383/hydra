"""Demo: point Hydra at a site, print the discovered internal API(s). (v0.1)

Usage:
  python examples/find_api.py <url>
  python examples/find_api.py <url> --proxy file                    # random from proxies.txt
  python examples/find_api.py <url> --proxy explicit ip:port:user:pass
  PROXIES_FILE=~/simone/proxies.txt python examples/find_api.py <url> --proxy file
"""
import argparse
import json
import sys

sys.path.insert(0, __file__.rsplit("/examples/", 1)[0])  # run without installing
from hydra.discover import discover
from hydra.session import pick_proxy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--proxy", choices=("native", "file", "explicit"), default="native")
    ap.add_argument("--proxy-str", help="ip:port:user:pass for --proxy explicit")
    ap.add_argument("--proxies-file", help="path to proxies.txt for --proxy file")
    args = ap.parse_args()

    proxy = pick_proxy(args.proxy, proxies_file=args.proxies_file, explicit=args.proxy_str)
    via = "native ISP IP" if proxy is None else proxy["server"]
    print(f"→ discovering internal APIs on {args.url}  (via {via}) ...\n")

    candidates = discover(args.url, proxy=proxy)

    if not candidates:
        print("no internal JSON API found — the site may be server-rendered "
              "(the HTML *is* the data), or the API fires on interaction (v0.1.1).")
        return

    print(f"found {len(candidates)} candidate endpoint(s), biggest first:\n")
    for i, c in enumerate(candidates, 1):
        print(f"[{i}] {c.method} {c.url}")
        print(f"    status {c.status} · {c.size:,} bytes · {c.shape}")
        auth = [k for k in c.request_headers
                if k.lower() in ("authorization", "x-api-key", "cookie", "x-algolia-api-key")]
        if auth:
            print(f"    auth headers present: {auth}")
        print(f"    sample: {json.dumps(c.sample)[:160]}")
        print()


if __name__ == "__main__":
    main()
