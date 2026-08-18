<div align="center">

# 🐍 Hydra

**A stealth-automation primitive on Camoufox — auto-discovers a site's internal
data (API or server-rendered) and self-heals when detection breaks.**

*Cut off a head, two grow back.*

<br>

![Hydra humanized cursor movement](assets/movement.gif)

<sub>Hydra's cursor — real Camoufox humanize, driven by a mostly-direct human approach:
efficient by default, occasional overshoot, never a fixed pattern.</sub>

</div>

---

Most web automation is brittle and static: it scrapes the fragile **DOM**, and its
stealth is fixed — when a site's detection updates, it silently gets blocked and a
human has to re-patch it.

Hydra goes one level deeper and closes the loop:

- **Finds the data, not the DOM.** It drives a stealth browser (Camoufox),
  intercepts the XHR/fetch traffic, and discovers the internal JSON endpoint +
  its auth. If there's no API (server-rendered pages), it reads the data inlined
  in the HTML instead — including modern Next.js App Router streams.
- **Adaptive, self-healing stealth.** When it hits a block it detects it
  **vendor-free** — anchoring on whether it actually got the data, not on recognizing a
  vendor — classifies *which* block it is from the response, and heals on a **live
  session**: rotate the exit (keeping the fingerprint + warm session), drop the session,
  wait it out, or relaunch — the cheapest fix first, instead of blindly cycling proxies.

It's not a scraper — it's a **resilient automation primitive** that anyone
automating the web can build on, the way you build on Camoufox itself.

## Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installs the `hydra` command
python -m camoufox fetch    # one-time browser download
```

## Quick start
```bash
hydra capture https://example.com            # JSON of the discovered endpoints → stdout
hydra capture https://example.com > api.json # progress goes to stderr, so this stays clean JSON
hydra capture https://example.com --pretty   # colored, boxed human view instead
```
Output is **JSON by default** — a clean array of the discovered endpoints
(`method`, `url`, `status`, `size`, `shape`, `auth`, `sample`) — so you can pipe
it to `jq`, save it, or feed a replay. `--pretty` gives a colored boxed view.

`capture` **self-heals by default** — it starts on your own IP, and only if it
diagnoses a block does it escalate (wait the challenge out → fresh fingerprint →
rotate to a proxy). It stays quiet when nothing's wrong, and narrates (on stderr)
when it fights.

## What it finds

A site can ship its data four ways. Hydra covers all four:

| how the site serves data | Hydra's mechanism |
|---|---|
| **API on load** | intercepts the XHR/fetch response |
| **API on interaction** (infinite scroll, pagination) | a scroll pass triggers it, then intercepts |
| **SSR** — inlined in the HTML (`__NEXT_DATA__`, Apollo, `ld+json`) | extracts the blob, points at the biggest record set |
| **Next.js App Router** — React Server Component streams (`__next_f`) | reassembles the stream and harvests the records |
| **live streams** — WebSocket / SSE (live odds, tickers) | captures the URL, subscribe frames, and a data sample |

Example — an infinite-scroll site, where the data only loads as you scroll:
```
$ hydra capture https://quotes.toscrape.com/scroll
[
  {
    "method": "GET",
    "url": "https://quotes.toscrape.com/api/quotes?page=2",
    "status": 200, "size": 4793, "shape": "dict(5 keys)", "auth": [],
    "sample": { "has_next": true, "page": 2, "quotes": [ ... ] }
  },
  ...
]
```
Trackers, analytics, fonts, consent/CMP config, and payment SDKs are filtered out
automatically. Each API candidate is captured **with its request + auth headers**,
so it can be replayed.

It also **doesn't trust `content-type`** — JSON served as `text/plain` or
`text/html` (common on legacy Java/PHP/enterprise backends) is captured too, not
silently dropped.

## Self-healing through blocks

`capture` heals automatically. It detects a block **vendor-free** — anchoring on the
one signal an adversary can't fake (*did I get the data?*), then reading the response
(status, headers, clearance cookies, challenge shape) to classify *which* block it is
— and maps it to the cheapest lever on a **persistent session**:

| detected block | lever | keeps |
|---|---|---|
| transient JS challenge | **patience** — wait it out | fingerprint + session |
| rate-limit / IP | **rotate exit** (swappable relay) | fingerprint + session |
| session / quota | **drop session** — clear cookies | fingerprint |
| fingerprint | **relaunch** — new identity (last resort) | — |
| auth / hard captcha | **stop** — needs a human | — |
| no API (SSR) | not a block — just parse the page | — |

The ladder is **patience-first**, and rotation is *hot*: a local relay swaps the exit IP
**without relaunching**, so the warm clearance cookie survives. Blindly rotating a proxy
often makes a fingerprint challenge *worse* — a clean native IP + a fresh fingerprint
often beats a flagged proxy.

**Watch it react to each block on command** (a local simulator mints each block class —
real antibot blocks are probabilistic, so this is the only way to demo every lever):
```bash
python examples/blocksim.py --ip          # 403 → rotate exit
python examples/blocksim.py --session      # 412 → drop session, keep fingerprint
python examples/blocksim.py --transient     # "Just a moment" → patience, same session
python examples/blocksim.py --auth          # → stops cleanly (needs a human)
python examples/blocksim.py                 # unclassifiable block → cost-ladder fallback
```
`examples/relay_rotate.py` proves the hot rotation end-to-end: the exit IP changes while
the fingerprint *and* the session cookie are preserved. `hydra heal <url>` prints the
full per-attempt trace for a single URL.

## Proxies

Point Hydra at a proxy file or a single proxy — the mode is **inferred**, so you
don't pass `--proxy` yourself:

```bash
hydra capture <url>                                # native IP, escalate to proxies only if blocked
hydra capture <url> --proxies-file p.txt           # rotate through a proxy file (any name)
hydra capture <url> --proxy-str ip:port:user:pass  # one explicit proxy
hydra capture <url> --proxy native                 # force native only (no proxy)
```
A proxy file is one `ip:port:user:pass` (or `ip:port`) per line; `--proxies-file`
defaults to `./proxies.txt` (or `$PROXIES_FILE`). Geoip is auto-aligned to the
proxy's exit IP so timezone/locale match where the traffic appears to come from.

If you **ask** for a proxy (`--proxies-file` / `--proxy-str` / `--proxy file`) but
none loads, Hydra **aborts** rather than falling back to your native IP — so a
missing proxy file can't accidentally hit a geo-locked site from your real IP.

> Proxy files hold credentials — keep them out of the repo. The default
> `proxies.txt` / `proxies*.txt` are gitignored; a custom name is **not**, so add
> it to `.gitignore` if you name it something else.

## Geo-gated / thin results

A wrong-country exit often returns a **200 that's thin** — the page renders but
withholds the real data. That's not a *block*, so self-heal won't fire on its own.
Tell Hydra what "good" looks like and it rotates exits until it gets there:

```bash
hydra capture <url> --proxies-file p.txt --min-endpoints 5    # until ≥5 endpoints fire
hydra capture <url> --proxies-file p.txt --expect /api/items  # until an endpoint URL matches
```
`--min-endpoints` needs no endpoint name (use it during discovery); `--expect`
targets a known endpoint. Pair with `--attempts N` to bound the hunt.

## From capture to a runnable client — `hydra gen`

Turn a discovery into a standalone, browser-free scraper:
```bash
hydra gen <url> --endpoint /api/items --out client.py
python client.py            # fetches the data with httpx — no browser
```
It emits one `httpx` function per discovered endpoint with the captured auth
(cookies / bearer / api-key) embedded, so it works immediately. The file holds
credentials — it's written `chmod 600`; re-run `hydra gen` when the auth expires.

## Behind a login

Data behind an auth wall is invisible to a logged-out browser. Log in once by
hand, then capture with the saved session:
```bash
hydra login https://site.com/login --state s.json     # a browser opens; log in, press Enter
hydra capture https://site.com/dashboard --state s.json
```
The session file holds cookies + tokens — it's a **credential**. Hydra writes it
`chmod 600` and gitignores the common names; keep it secret.

## Options (capture)
| flag | what |
|---|---|
| `--proxies-file PATH` | rotate through a proxy file (implies proxy mode) |
| `--proxy-str ip:port:user:pass` | one explicit proxy (implies proxy mode) |
| `--proxy auto\|native\|file\|explicit` | force a mode (default `auto`: native, escalate if blocked) |
| `--min-endpoints N` / `--expect SUBSTR` | rotate exits until the result is rich / a wanted endpoint fires |
| `--attempts N` / `--no-heal` | max self-heal attempts / single-shot |
| `--no-interact` / `--scrolls N` | skip or tune the scroll pass |
| `--state PATH` | capture with a saved login session (`hydra login`) |
| `--pretty` | colored boxed view instead of the default JSON |
| `--headful` | show the browser window |

## Status
🚧 Early, but the core works: discovery (API on load/scroll + SSR + RSC, any
content-type, **plus WebSocket/SSE live streams**), **vendor-free block detection**
(oracle-anchored, keyed on the response not the brand), **session-preserving self-heal**
(a persistent session + hot exit rotation via a relay that keeps fingerprint + clearance),
proxies with geo-gated retry, authenticated capture, and **`hydra gen`** (browser-free
client codegen). Honest edges: the self-heal's *mechanisms* are proven (see the demos)
but its live-recovery rate on real hard blocks is unvalidated — real blocks are
probabilistic. Not yet covered: **WS replay** (capture works, codegen doesn't),
typed-search, click-gated data, and the SDK/MCP layer — see `phases.md`.

Built on [Camoufox](https://github.com/daijro/camoufox) — engine-level fingerprint
spoofing. Hydra is the *adaptive* layer above it.

> Use responsibly: capture your own data or genuinely public data, and respect
> each site's terms and rate limits.
