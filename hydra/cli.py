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
import os
import re
import sys

from hydra.discover import capture
from hydra.session import load_proxies, parse_proxy, pick_proxy
from hydra.stealth import resilient_capture

# --- terminal colors (auto-off when piped / NO_COLOR) --------------------------
_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def bold(s):   return _c("1", s)
def dim(s):    return s   # no faded gray anywhere — normal text (bold or normal only)
def red(s):    return _c("31", s)
def green(s):  return _c("32", s)
def yellow(s): return _c("33", s)
def cyan(s):   return _c("36", s)
def magenta(s): return _c("35", s)

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _vis(s: str) -> int:
    """Visible length, ignoring ANSI color codes."""
    return len(_ANSI.sub("", s))


def _box(title: str, rows: list[str], col=cyan) -> str:
    """A titled box: ┌─ title ─────┐ / │ rows │ / └────────┘ (ANSI-width aware)."""
    inner = max([_vis(r) for r in rows] + [_vis(title) + 4])
    top = col("┌─ ") + bold(title) + " " + col("─" * max(0, inner - _vis(title) - 1) + "┐")
    body = [col("│ ") + r + " " * (inner - _vis(r)) + col(" │") for r in rows]
    bot = col("└" + "─" * (inner + 2) + "┘")
    return "\n".join([top] + body + [bot])


def _endpoint_name(url: str) -> str:
    """The last path segment (getEventoPerMacrogruppo) — the human-readable handle."""
    return url.split("?")[0].rstrip("/").split("/")[-1] or url


def _add_proxy_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--proxy", choices=("native", "file", "explicit"), default="native",
                   help="native = your ISP IP (default); file = random from proxies.txt; "
                        "explicit = one proxy via --proxy-str")
    p.add_argument("--proxy-str", metavar="ip:port:user:pass",
                   help="proxy for --proxy explicit")
    p.add_argument("--proxies-file", metavar="PATH",
                   help="proxies.txt for --proxy file (or set PROXIES_FILE)")


def _cmd_capture(args: argparse.Namespace) -> int:
    # map the proxy mode to a start exit + escalation pool for the self-healing loop:
    #   auto     → start native, escalate to proxies.txt if a wall is hit (default)
    #   native   → native only, no proxy escalation
    #   file     → start on a proxies.txt exit
    #   explicit → use --proxy-str
    # infer the mode from what you actually pass: giving a proxies file or an
    # explicit proxy already means "use a proxy" — no need to also say --proxy file.
    if args.proxy_str:
        heal_kw = dict(start="proxy", explicit=args.proxy_str)
    elif args.proxies_file or args.proxy == "file":
        heal_kw = dict(start="proxy", proxies_file=args.proxies_file)
    elif args.proxy == "native":
        heal_kw = dict(start="native", proxies_file=None)
    else:  # auto
        heal_kw = dict(start="native", proxies_file=args.proxies_file)

    # If you EXPLICITLY asked for a proxy but none resolves, abort — never silently
    # fall back to your native IP (that can leak your real IP on a geo-locked/client
    # site). Only `--proxy auto` (the default, nothing requested) uses native freely.
    if args.proxy_str:
        if not parse_proxy(args.proxy_str):
            print(f"{red('✗')} invalid --proxy-str {bold(args.proxy_str)} "
                  f"(expected ip:port:user:pass or ip:port).", file=sys.stderr)
            return 2
    elif args.proxy == "explicit":
        print(f"{red('✗')} --proxy explicit needs --proxy-str ip:port:user:pass.", file=sys.stderr)
        return 2
    elif args.proxies_file or args.proxy == "file":
        if not load_proxies(args.proxies_file):
            src = args.proxies_file or os.getenv("PROXIES_FILE") or "./proxies.txt"
            print(f"{red('✗')} you asked for a proxy but none loaded from {bold(src)} — "
                  f"aborting (refusing to fall back to your native IP).", file=sys.stderr)
            return 2

    attempts = 1 if args.no_heal else args.attempts
    use_json = args.json or not args.pretty
    ps = sys.stderr if use_json else sys.stdout   # progress → stderr in json mode

    heal = "no-heal" if args.no_heal else f"self-healing · up to {attempts} attempts"
    print(f"{cyan('🐍 hydra')} {bold('capture')} {args.url}  ({heal})\n", file=ps)

    def on_attempt(att):
        # stay quiet on a clean first hit; narrate only when actually healing
        if att.verdict.blocked:
            print(f"  {red('✗')} attempt {att.n} {att.via}  "
                  f"{red(att.verdict.kind)} · layer {att.verdict.layer} → {yellow(att.move)}", file=ps)
        elif "rotate exit" in att.move:
            print(f"  {yellow('~')} attempt {att.n} {att.via}  {yellow(att.move)}", file=ps)
        elif att.n > 1:
            print(f"  {green('✓')} attempt {att.n} {att.via}  {green('through')}", file=ps)

    r = resilient_capture(args.url, max_attempts=attempts, headless=not args.headful,
                          interact=not args.no_interact, scroll_steps=args.scrolls,
                          storage_state=args.state, expect=args.expect,
                          min_candidates=args.min_endpoints, on_attempt=on_attempt, **heal_kw)

    def _auth(c):
        return [k for k in c.request_headers
                if k.lower() in ("authorization", "x-api-key", "cookie", "x-algolia-api-key")]

    # ---- JSON output (default) — a clean array to stdout, progress on stderr ----
    if use_json:
        if not r.recovered:
            want = f"'{args.expect}'" if args.expect else f"{args.min_endpoints}+ endpoints"
            print(f"{yellow('⚠')} did not reach {want} after {r.tries} attempt(s) — "
                  f"emitting what fired", file=sys.stderr)
        out = []
        for c in r.candidates:
            d = {"method": c.method, "url": c.url, "status": c.status, "size": c.size,
                 "shape": c.shape, "auth": _auth(c), "sample": c.sample}
            if c.post_data:
                d["post_data"] = c.post_data
            out.append(d)
        for b in r.embedded:
            out.append({"kind": b.kind, "records": b.records_count, "size": b.size,
                        "path": b.records_path, "sample": b.sample})
        print(json.dumps(out, default=str, indent=2))
        return 0 if out else 1

    # ---- pretty view (--pretty) -------------------------------------------------
    if not r.recovered:
        want = f"'{args.expect}'" if args.expect else f"{args.min_endpoints}+ endpoints"
        if (args.expect or args.min_endpoints > 1) and (r.candidates or r.embedded):
            print(f"\n{yellow('⚠')} never reached {yellow(want)} after {r.tries} exit(s) — showing what did fire\n")
        else:
            print(f"\n{red('✗ blocked')} after {r.tries} attempt(s) · last: {r.attempts[-1].verdict.kind}. "
                  f"Try --proxies-file, or raise --attempts.")
            return 1

    big = [b for b in r.embedded if b.records_count >= 5]

    def _print_candidate(i, c):
        status = "" if c.status == 200 else f" · {red(str(c.status))}"
        keys = (green('🔑 ' + ','.join(_auth(c))) + '   ' if _auth(c) else '')
        print(f"{bold(green(f'[{i}]'))} {bold(c.method)} {bold(cyan(_endpoint_name(c.url)))}"
              f"   {bold(yellow(f'{c.size:,} B'))} · {c.shape}{status}")
        print(f"    {bold(cyan(c.url))}")
        print(f"    {keys}{json.dumps(c.sample, default=str)[:120]}\n")

    def _print_blob(tag, b):
        print(f"{bold(magenta(f'[{tag}]'))} {bold(b.kind)}   "
              f"{bold(yellow(f'{b.records_count} records'))} · {b.size:,} B · {b.records_path}")
        print(f"    {json.dumps(b.sample, default=str)[:120]}\n")

    if r.candidates:
        head = f"{len(r.candidates)} endpoint" + ("s" if len(r.candidates) != 1 else "")
        if big:
            head += f" + {len(big)} SSR blob" + ("s" if len(big) != 1 else "")
        if r.recovered and r.tries > 1:
            head += f"  ·  recovered in {r.tries}"
        print(_box(f"🐍 {head}", [bold(args.url)], col=green) + "\n")
        for i, c in enumerate(r.candidates, 1):
            _print_candidate(i, c)
        if big:
            print(bold(magenta("── also inlined in the HTML (SSR) ──")) + "\n")
            for i, b in enumerate(big, 1):
                _print_blob(f"S{i}", b)
        return 0

    if r.embedded:
        print(_box(f"🐍 SSR-embedded · {len(r.embedded)} blob(s)", [bold(args.url)], col=magenta) + "\n")
        for i, b in enumerate(r.embedded, 1):
            _print_blob(i, b)
        return 0

    print(f"{yellow('∅')} no internal JSON API and no inlined blob — the API may fire "
          f"{dim('on interaction (scroll/click), or the page is behind a block.')}")
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


def _cmd_login(args: argparse.Namespace) -> int:
    """Open a real browser, let the user log in by hand, and save the session
    (cookies + localStorage) so `capture --state` can reach data behind the login."""
    from camoufox.sync_api import Camoufox
    from hydra.session import _geoip_for, parse_proxy

    proxy = parse_proxy(args.proxy_str) if args.proxy_str else None
    # force English UI for the manual login (geoip locale can serve a regional
    # language); the saved cookies are locale-independent, so capture is unaffected.
    with Camoufox(headless=False, humanize=True, geoip=_geoip_for(proxy),
                  proxy=proxy, os=["windows", "macos"], locale=args.lang) as browser:
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(args.url)
        input("\nLog in in the browser window, then press Enter here to save the session… ")
        ctx.storage_state(path=args.state)
    try:
        os.chmod(args.state, 0o600)   # it holds cookies + tokens — owner-only
    except OSError:
        pass
    print(f"session saved → {args.state}  (chmod 600 — it's a credential; keep it secret,\n"
          f"                    it's gitignored by default)\n"
          f"now:  hydra capture <url-behind-login> --state {args.state}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydra",
        description="Stealth-automation primitive on Camoufox — find a site's internal API.")
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="discover the internal JSON API on a URL "
                                         "(self-heals through blocks by default)")
    cap.add_argument("url")
    cap.add_argument("--proxy", choices=("auto", "native", "file", "explicit"), default="auto",
                     help="auto = native, escalate to proxies.txt if blocked (default); "
                          "native = native only; file = start on a proxies.txt exit; "
                          "explicit = --proxy-str")
    cap.add_argument("--proxy-str", metavar="ip:port:user:pass", help="proxy for --proxy explicit")
    cap.add_argument("--proxies-file", metavar="PATH",
                     help="path to a proxies file (implies file mode — no --proxy needed)")
    cap.add_argument("--attempts", type=int, default=3, help="max self-heal attempts")
    cap.add_argument("--no-heal", action="store_true",
                     help="single shot — don't heal through a block")
    cap.add_argument("--json", action="store_true",
                     help="force JSON output (already the default)")
    cap.add_argument("--pretty", action="store_true",
                     help="colored boxed view instead of JSON")
    cap.add_argument("--headful", action="store_true", help="show the browser window")
    cap.add_argument("--no-interact", action="store_true",
                     help="skip the scroll pass (only catch APIs that fire on load)")
    cap.add_argument("--scrolls", type=int, default=6,
                     help="how many scroll steps to trigger lazy/infinite-scroll APIs")
    cap.add_argument("--state", metavar="PATH",
                     help="saved session from `hydra login` — capture behind a login")
    cap.add_argument("--min-endpoints", type=int, default=1, metavar="N",
                     help="keep rotating exits until at least N endpoints are found "
                          "(defeats geo-degraded 200s — no endpoint name needed)")
    cap.add_argument("--expect", metavar="SUBSTR",
                     help="like --min-endpoints, but wait for an endpoint URL to "
                          "contain this substring (when you know the endpoint name)")
    cap.set_defaults(func=_cmd_capture)

    login = sub.add_parser("login", help="log in by hand once and save the session "
                                         "for `capture --state`")
    login.add_argument("url", help="the site's login page")
    login.add_argument("--state", metavar="PATH", default="hydra_session.json",
                       help="where to save the session (default hydra_session.json)")
    login.add_argument("--proxy-str", metavar="ip:port:user:pass",
                       help="log in through this proxy (match the exit you'll capture from)")
    login.add_argument("--lang", default="en-US", help="UI locale for the login window")
    login.set_defaults(func=_cmd_login)

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
