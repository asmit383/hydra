# Hydra — phases

> Build discipline: **ship v0.1 before touching v0.2.** No 4th idea, no re-scope.
> The strategy is settled — the next win is *code that runs*, not a better spec.

---

## v0.1 — API-finder with stealth access ⬜  ← BUILD THIS FIRST
The concrete, demonstrable kernel. Stealth is already in it (Camoufox); no
adaptive loop yet, no DOM extraction.

- [ ] `session.py` — launch Camoufox (headless, humanize, geoip), optional proxy.
- [ ] `discover.py` — navigate to a target URL, **intercept every XHR/fetch
      response** (`page.on("response")`), collect JSON candidates that look like
      the target data (non-trivial size, arrays/records).
- [ ] Capture each candidate's **request**: URL, method, headers, params, and any
      **auth token/key** (the YC `AlgoliaOpts` move — extract what the page hands
      the browser at runtime).
- [ ] `client.py` — generate a **browser-free client**: replay the request
      directly (httpx) to pull the data, no Camoufox needed after discovery.
- [ ] `examples/find_api.py` — demo: point at a JSON-API-backed site → prints the
      discovered endpoint + a runnable client.

**Done when:** point Hydra at a real site → it finds the internal API → the
generated client pulls the data *without a browser*. That's the whole thesis,
proven.

**The demo that sells it:** show the API-client keeps working after a site's
*layout* would have broken a DOM scraper. (Articulate it even if hard to stage.)

---

## v0.2 — Adaptive / self-healing stealth ⬜  (the novel flagship)
Add the loop *on top of a working v0.1*. This is the differentiator.

- [ ] Detect a block: 403 / CAPTCHA / challenge page / empty-data response.
- [ ] `diagnose.py` — **which layer leaked?** Diff Hydra's fingerprint/behavior
      vs a real-browser baseline (probe a detection-test endpoint, e.g. CreepJS),
      identify the offending signal. (LLM-Doc/kdoc DNA → applied to anti-detection.)
- [ ] `stealth.py` — **adapt**: rotate fingerprint / swap proxy / adjust the
      leaking signal → retry until through. Self-healing.
- [ ] **Measure it:** recovery-rate vs a static (non-adaptive) baseline. That
      measured "self-heal beats static" number *is* the proof (leankv rigor).

**Done when:** a real block is *diagnosed* and *recovered from* automatically,
and the recovery-rate beats static, measured.

---

## v0.3 — DOM fallback + broaden ⬜  (only after v0.1 + v0.2 ship)
- [ ] LLM-DOM extraction fallback for sites with **no usable API** (commodity —
      don't over-invest; it's the boring part you don't love).
- [ ] Package as a clean library/CLI; write the README pitch; **ship a Show HN /
      r/LocalLLaMA post** (visibility — the thing that gets stars).

---

## Reality check
Primary lane is still **inference (flint / the MTP follow-up owed to Nicolas)**.
Hydra is the **secondary-lane flagship** (automation/stealth — the lane you love).
Timebox them; don't let Hydra eat the promised flint work. But Hydra is the piece
that gets *broad* visibility (a tool anyone into automation can use), so it earns
real time. **Ship v0.1, then decide.**
