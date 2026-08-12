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

## Shipped since ✅

### WebSocket / SSE capture
Live/streaming data (live odds, tickers) is pushed over **WebSocket** / SSE.
`page.on("websocket")` now captures each stream: URL, the client's **subscribe
frames** (for replay), and a sample of received data frames; `text/event-stream`
responses are recorded as SSE endpoints. Surfaced in JSON + pretty output.
- Still open: **WS replay** — reconnect + re-subscribe + merge delta frames into
  current state is site-specific and much harder than REST; `hydra gen` doesn't
  emit WS clients yet (capture shows the subscribe frames to build one by hand).

## NOT covered yet ⬜  (honest gaps — real mechanisms, not edge cases)

### 1. Typed-search interaction
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

## Usability
- [x] `hydra gen <url>` — codegen a **browser-free replay client** from a capture:
      one httpx function per endpoint, captured auth embedded, `--out` writes it
      (chmod 600). "Point at a site → get a runnable client." Verified end-to-end.
- [x] JSON output by default (numbered, sample capped, syntax-highlighted); the
      colored boxed view is `--pretty`.
- [ ] One-shot Camoufox re-auth fallback inside the generated client when the
      token expires (currently: re-run `hydra gen`).
- [ ] `--out data.json` on `capture` — save the **full** records, not just samples.
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
