# Hydra — phases

> Build discipline: **ship each slice before starting the next.** The strategy is
> settled — the next win is *code that runs*, not a better spec.

---

## Shipped ✅

**Discovery**
- [x] Intercept XHR/fetch, rank JSON candidates, capture request + auth headers.
- [x] Filter noise (analytics, trackers, fonts, CMP/consent, payment SDKs, chat
      widgets, Sportradar/stats widgets).
- [x] **Content-type agnostic** — parse JSON even when served as `text/plain` /
      `text/html` (legacy Java/PHP/enterprise backends). This was a silent-failure
      class: without it, such sites return only their JSON-typed nav and look
      "empty".
- [x] Interaction pass — scroll to fire infinite-scroll / paginated APIs.
- [x] SSR extraction — `__NEXT_DATA__`, `__APOLLO_STATE__`, `ld+json`.
- [x] Next.js **App Router (RSC)** — reassemble `__next_f` streams, harvest records.

**Stealth / access**
- [x] Camoufox launch, 3 proxy modes (native/file/explicit), geoip aligned to exit.
- [x] Self-healing loop — diagnose vendor + leaked layer, patience-first ladder
      (wait challenge out → fresh fingerprint → rotate exit last). `capture` heals
      by default; `hydra heal` shows the trace.
- [x] Authenticated capture — `hydra login` + `capture --state` (session reuse).
- [x] Geo-gated retry — `--min-endpoints N` / `--expect SUBSTR` rotate exits until
      the result is rich / the wanted endpoint fires (defeats geo-degraded 200s).

---

## NOT covered yet ⬜  (honest gaps — real mechanisms, not edge cases)

### 1. WebSocket / SSE  ← the biggest gap
Live/streaming data (live betting odds, live scores, trading tickers, chat) is
pushed over **WebSocket** or **Server-Sent Events**, not XHR. Hydra intercepts
neither, so it's blind to anything real-time. Prematch/static data = caught; live
data = missed.
- Approach: `page.on("websocket")` → capture the connection URL, subprotocol, and
  a sample of frames (sent + received); surface it as a streaming "endpoint".
  Same idea for SSE (`text/event-stream` responses — currently they'd fail JSON
  parse and be dropped).

### 2. Typed-search interaction
APIs that fire only on **keystrokes** — Algolia, autocomplete, search-as-you-type
(the YC/DocSearch case). The scroll pass doesn't trigger them.
- Approach: `--type "<query>"` — focus a search input, type, wait, intercept.

### 3. Click-gated data
Data behind a **button/tab click** with no distinct URL — "load more", market
tabs, expandable sections, "show odds". Scroll doesn't reach it.
- Approach: `--click "<selector-or-text>"` — click named element(s) before/while
  intercepting. Careful: clicking can navigate away (see Vinted's country link).

### 4. Consent / geo modals that trap interaction
Some sites won't activate their feed until a **cookie banner** or **country modal**
is dismissed (Vinted's "Where do you live?" blocked the feed entirely).
- Approach: a dismiss pass — click common consent buttons
  (`#onetrust-accept-btn-handler`, etc.) before the scroll/interaction pass.

### 5. Hard human-verification
If a site *requires solving* a CAPTCHA (not just presenting a JS challenge that
auto-clears), patience + rotation won't get through. Out of scope by design —
Hydra heals from detection, it doesn't solve CAPTCHAs.

### 6. Auth beyond a saved session
`--state` reuses a hand-login. Not covered: programmatic login, token refresh when
a saved session expires mid-run, OAuth flows that some providers block in
automation.

---

## Usability (built discovery, not yet a "tool") ⬜
- [ ] `client.py` / `hydra gen` — codegen a **browser-free replay client** from a
      capture, with a one-shot Camoufox re-auth fallback when the token expires.
      The adoption hook: "point at a site → get a runnable client."
- [ ] `--out data.json` — save the **full** discovered records, not just a sample.
- [ ] Collapse paginated `?page=1..N` candidates into one parameterized endpoint.

## Credibility ⬜
- [ ] Tests + CI (the `tests/` dir is a stub).
- [ ] README demo gif; Show HN.

---

## Reality check
Request/response discovery is near-universal now: on-load / on-scroll APIs, SSR,
RSC, **any content-type**, behind a login, geo-gated. The genuine frontier is
**streaming (WebSocket/SSE)** and **input-driven discovery (type/click)**. Keep
the public repo generic — no client-specific targets or endpoints.
