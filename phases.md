# Hydra — phases

> Build discipline: **ship each slice before starting the next.** The strategy is
> settled — the next win is *code that runs*, not a better spec.

---

## v0.1 — API discovery with stealth access ✅
The concrete, demonstrable kernel. Stealth is in it (Camoufox); no adaptive loop.

- [x] `session.py` — launch Camoufox (headless, humanize, geoip), 3 proxy modes.
- [x] `discover.py` — navigate, **intercept every XHR/fetch** (`page.on("response")`),
      collect JSON candidates that look like data, filter tracker/analytics noise.
- [x] Capture each candidate's **request** — URL, method, headers, auth token/key.
- [x] `hydra capture` CLI + packaging (`pip install -e .`).

## v0.1.1 — SSR / embedded-data extraction ✅
- [x] `embed.py` — when there's no XHR API, read data inlined in the HTML:
      `__NEXT_DATA__`, `__APOLLO_STATE__`, `ld+json`, generic `application/json`.
- [x] Point at the biggest record set inside the blob.

## v0.1.2 — interaction pass ✅
- [x] Scroll pass (`scrollTo(bottom)`) to fire infinite-scroll / paginated APIs.
      This is what makes it near-universal for content sites.

## v0.1.3 — Next.js App Router (RSC) ✅
- [x] Reassemble `self.__next_f.push(...)` streams, harvest record objects by
      anchoring on content keys + string-aware brace matching, cluster by shape,
      surface the richest-content group (isolates the item list from taxonomy).

## v0.2 — adaptive / self-healing stealth ✅  (the flagship)
- [x] Detect a block: DataDome / Cloudflare / PerimeterX / 403 / 429 / challenge.
- [x] `diagnose.py` — classify the **vendor** and **which layer leaked** (ip /
      fingerprint / behavioral), with a recommended adaptation.
- [x] `stealth.py` — **patience-first** heal ladder: wait the challenge out →
      fresh fingerprint (relaunch) → rotate exit last. `capture` heals by default;
      `hydra heal` shows the per-attempt trace.
- [x] `examples/heal_bench.py` — measured recovery-rate, adaptive vs static.

## Auth ✅
- [x] `hydra login` (headful, save session) + `capture --state` (reuse it) to reach
      data behind a login. Session files are chmod 600 + gitignored.

---

## Next
- [ ] `client.py` / `hydra gen` — codegen a **browser-free replay client** from a
      capture, with a one-shot Camoufox re-auth fallback when the token expires.
      The adoption hook: "point at a site → get a runnable client."
- [ ] `--out data.json` — save the full discovered records, not just a sample.
- [ ] Typed-search + click interaction (Algolia/autocomplete; "load more").
- [ ] Consent/modal auto-dismiss (some feeds gate behind a cookie banner / geo modal).
- [ ] Tests + CI; README demo gif; Show HN.

## Reality check
Discovery (API + SSR + RSC), self-healing, proxies, and authenticated capture all
work. The remaining wins are **usability** (`gen`, `--out`) and **coverage edges**
(typed search, consent). Keep the public repo generic — no client-specific targets
or endpoints.
