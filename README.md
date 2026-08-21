<div align="center">

# 🐍 Hydra

**A stealth automation *body* for AI agents (and scripts) on Camoufox — it beats antibot,
discovers a site's internal API, drives the page with humanized behavior, and self-heals
when detection breaks.**

*Cut off a head, two grow back.*

<br>

![Hydra humanized cursor movement](assets/movement.gif)

<sub>Hydra's cursor — a per-session persona, generated from real human-movement models,
distinct for every agent (no two move alike).</sub>

</div>

---

Most web automation is brittle and static: it scrapes the fragile **DOM**, drives the
browser like a robot (instant clicks, fixed-length scrolls, no typing rhythm), and when a
site's detection updates it silently gets blocked and a human re-patches it.

Hydra is the layer that fixes all three:

- **Finds the data, not the DOM.** Drives a fingerprint-hardened browser (Camoufox),
  intercepts the XHR/fetch traffic, and discovers the internal JSON endpoint + its auth —
  or reads SSR-inlined data / live WebSocket streams. A site's API rarely breaks on a
  redesign; the DOM does.
- **Moves like a human, not a bot.** Keystroke timing (digraph latency, dwell, typos +
  corrections) modeled from a **real 136M-keystroke dataset**, and mouse trajectories
  (velocity, curvature, tremor, overshoot) generated per-session — so **10,000 agents don't
  all move identically** (which is itself a mass-block signal). One coherent persona per
  session: fast typist ⇒ fast mouse.
- **Self-heals through blocks.** Detects a block **vendor-free** (anchored on *did I get the
  data?*, not on recognizing a brand), and heals on a **live session** with a cost-ordered
  ladder — patience → rotate exit → drop session → relaunch — cheapest fix first.

It's not a scraper — it's a **stealth body** an AI *or* a plain script can drive.

## Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installs the `hydra` command + the `hydra` package
python -m camoufox fetch    # one-time browser download
```

---

## The SDK — `Hydra`

One stateful object holds a persistent stealth session. An AI drives it (via `observe`), or
you script it directly — same object, no LLM required.

```python
from hydra import Hydra

with Hydra(proxies="proxies.txt", seed=7) as h:   # persistent session, one persona per session
    result = h.capture("https://example.com")      # stealth + discover + self-heal, all handled
    for c in result.candidates:                    # the discovered endpoints (ranked biggest-first)
        print(c.method, c.status, c.shape, c.url)
```

**Baked-in rules (not configurable):** one persona per session (from real data) · persona +
fingerprint + session travel together (a `relaunch` mints a new identity, hot levers keep it)
· **behavior is always ours** — the humanized engine drives every mouse move, keystroke, and
scroll (no "be less stealthy" knob; raw `h.page` is the only escape hatch).

### 1 · Discover an internal API + replay it (warm-session)
```python
with Hydra(proxies="proxies.txt", seed=7) as h:
    r = h.capture("https://example.com/listing")
    endpoint = r.candidates[0]                     # ranked biggest-first
    data = h.fetch(endpoint)                        # replay it IN-SESSION (carries the clearance cookie)
    print(data["status"], data.get("json"))
```
`fetch()` replays **GET, POST, and GraphQL** — it sends the captured method, POST body, and
header-auth (bearer / api-key), while `credentials:'include'` carries the browser-minted
clearance cookie a plain `httpx` call can't.

### 2 · Drive the page with humanized behavior (no AI)
```python
with Hydra(seed=7) as h:
    h.navigate("https://example.com/login")
    h.type("#email", "me@example.com")             # per-keystroke timing, occasional typo+correction
    h.type("#password", "hunter2", secret=True)    # secret → no typos in a password field
    h.click("button[type=submit]")                 # curved, variable-speed mouse (never a teleport)
    h.scroll(steps=4)                              # variable-distance, persona-paced
    r = h.capture("https://example.com/dashboard")
```
Every action goes through the behavioral engine — keystroke, mouse, scroll, and idle are one
coherent persona. Never uses `fill()` (which fires zero keystroke events = an instant flag).

### 3 · Interaction-gated data + context capture
Some data only fires *after* a click (a market tab, a sport switch, opening a match). `open()`
+ `act()` capture the APIs an action **triggers**, tagged with the action that revealed them.
```python
with Hydra(proxies="proxies.txt", seed=7) as h:
    h.open("https://example.com")                  # capture on-load APIs (tagged "load")
    h.act("#tab-details", label="open details")    # click → capture what THAT fires
    for c in h.context:
        print(c["fired_on"], "→", c["url"])         # e.g. "open details → /api/getDetails"
```

### 4 · Let an AI decide (optional) — the action space
`observe()` turns the DOM into a small, labeled, **spatial** menu (visible elements only, each
with `box=[x,y,w,h]` to disambiguate duplicates, a stable id, and an `oauth` trap flag). The AI
reads it, picks an `id`, and the SDK acts on it — humanized.
```python
with Hydra(seed=7) as h:
    h.navigate("https://example.com")
    actions = h.observe()
    # → [{"id":1,"kind":"a","label":"Tennis","box":[110,140,54,41],"oauth":false}, ...]
    # your LLM picks id 1 given the goal, then:
    h.click(1)                                      # act by observe() id
```
> The AI is an **optional** consumer of `observe()`. Everything else — `navigate`, `capture`,
> `type`, `click`, `scroll`, `fetch` — is deterministic and callable directly, no LLM.

### 5 · Behind a login
Log in once by hand, then reuse the saved session:
```bash
hydra login https://example.com/login --state s.json   # a browser opens; log in, press Enter
```
```python
with Hydra(state="s.json", seed=7) as h:
    r = h.capture("https://example.com/account")
```
The session file holds cookies + tokens — Hydra writes it `chmod 600` and gitignores the
common names. Keep it secret.

### 6 · Proxies
```python
Hydra(proxies="proxies.txt")                 # rotate through a file (ip:port:user:pass per line)
Hydra(proxy="ip:port:user:pass")             # one explicit exit
Hydra()                                       # native IP (no proxy)
```
Geoip is auto-aligned to the exit (timezone/locale match where the traffic appears from). Give
it a proxy and the session **starts on the exit** — required for geo-locked sites.

### 7 · The escape hatch
Need raw control? `h.page` is the live Playwright page.
```python
with Hydra(seed=7) as h:
    h.navigate("https://example.com")
    h.page.evaluate("() => document.title")
```

**Object surface:** `navigate` · `capture` · `open` · `act` · `observe` · `type` / `click` /
`move_to` / `idle` / `scroll` · `fetch` · properties `page` / `persona` / `exit` / `context`.

---

## The behavioral engine — humanized, from real data

Camoufox spoofs the fingerprint (the body *at rest*). Hydra owns the body *in motion*, and
generates it **per session** — so 10,000 agents don't share one movement algorithm (identical
motion across a fleet is itself a signature):

- **Keystroke** — a 3-level model (digraph-pair latency, per-bigram individuality,
  Ornstein-Uhlenbeck tempo drift), log-normal timing, boundary pauses, dwell, and
  typo→backspace→retype. Parameters **measured** from the Aalto *136M keystrokes* dataset.
- **Mouse (MouseForge)** — per-session trajectory: dense sampling, ease-in-out velocity, a
  sine-arc bow, small tremor, overshoot-and-correct. **5,000 sessions → 5,000 distinct paths.**
- **Coherence** — one persona drives typing *and* mouse *and* scroll *and* idle; a slow typist
  is slow everywhere. `h.idle(ms)` even keeps the cursor alive during LLM think-time (a frozen
  cursor between agent actions is the loudest agent tell).

Honest edge: the mouse is built on real *motor-science models* (minimum-jerk, Fitts, tremor)
with parameters not yet calibrated to a mouse dataset — structurally human, not yet
measured-human. Keystroke is measured.

## Self-healing through blocks

Detected **vendor-free** — the one signal an adversary can't fake is *did I get the data?* —
then mapped to the cheapest lever on a **live session**, escalating down the ladder if a block
recurs:

| detected block | lever | keeps |
|---|---|---|
| transient JS challenge / behavioral flag | **patience** — a *humanized* wait (cursor drifts while it clears, never a frozen page) | fp + session + IP |
| rate-limit / IP | **rotate exit** (hot relay swap) | fp + session |
| session / quota | **drop session** (clear cookies) | fp + IP |
| fingerprint | **relaunch** (new identity, last resort) | — |
| auth / hard captcha | **stop** — needs a human | — |

Cost-ordered: touch the fingerprint *last* (it's the only lever that burns the warm clearance
you fought to earn). There's no separate "act human" rung — behavior is always on, so even
*waiting* is humanized. On a **native or single-proxy** session the rotate rung is dropped
(nothing to rotate to): `patience → drop session → relaunch`.

## What it discovers

| how the site serves data | Hydra's mechanism |
|---|---|
| **API on load** | intercepts the XHR/fetch response (any content-type, incl. JSON-as-text/plain) |
| **API on interaction** | a humanized scroll/click pass triggers it, then intercepts |
| **API on a click** (`act`) | tags the endpoint with the action that fired it |
| **POST / GraphQL** | kept as distinct operations (dedup by url **+** body), replayable via `fetch` |
| **SSR** — `__NEXT_DATA__` / Apollo / `ld+json` | extracts the blob, points at the biggest record set |
| **Next.js App Router** (RSC `__next_f`) | reassembles the stream, harvests records |
| **live streams** — WebSocket / SSE | captures the URL, subscribe frames, a data sample |

Trackers, analytics, fonts, consent/CMP, payment SDKs are filtered out automatically.

## CLI

The SDK is the main interface, but a CLI wraps it for quick one-offs:
```bash
hydra capture https://example.com              # JSON of discovered endpoints → stdout
hydra capture https://example.com --pretty     # colored boxed view
hydra capture https://example.com --proxy file --proxies-file proxies.txt   # via a proxy exit
hydra login https://example.com/login --state s.json                        # save a session
hydra gen https://example.com --endpoint /api/items --out client.py         # codegen a client
```

## Status

🚧 Early, but the core works and is **proven on live, hard targets** (it pulls data off
Cloudflare/Akamai-gated sites). Built: the `Hydra` SDK, vendor-free detection, session-
preserving self-heal, data-backed humanized keystroke + MouseForge, discovery
(API/SSR/RSC/WebSocket, POST/GraphQL), context capture, `observe`, warm-session replay.
Honest edges: the self-heal's live-recovery rate on the hardest probabilistic blocks is
unvalidated; the mouse isn't dataset-calibrated yet; the amortization store (discover-once →
replay-forever) and the MCP/agent layer are designed, not built. See `phases.md`.

Built on [Camoufox](https://github.com/daijro/camoufox) — engine-level fingerprint spoofing.
Hydra is the *adaptive, behavioral* layer above it.

> Use responsibly: capture your own data or genuinely public data, respect each site's terms
> and rate limits.
