# Hydra — project spec

> **A stealth-automation primitive on Camoufox: auto-discovers a site's internal
> API and self-heals when detection breaks. Usable by anyone automating the web.**

Cut off a head, two grow back. Block Hydra, it diagnoses what leaked and adapts.

---

## The thesis
Most web automation is **brittle + static**:
- It scrapes the **DOM**, which breaks on every layout change.
- Its stealth is **static** — configure it once; when a site's detection updates,
  it silently gets blocked and a human has to re-diagnose and re-patch.

Hydra fixes both by going one level deeper and closing the loop:
1. **Go for the stable internal API, not the brittle DOM.** A site's internal
   JSON API rarely changes on a visual redesign — hit *that* and you don't break.
2. **Make the stealth adaptive.** When Hydra gets blocked, it **diagnoses which
   fingerprint layer leaked** (its LLM-Doc/kdoc DNA, applied to anti-detection)
   and **adapts** — instead of silently dying.

## Why it's a *tool*, not a scraper
Bound to scraping → only scrapers use it. Framed as **adaptive stealth +
automated internal-API discovery on Camoufox** → it's a **primitive anyone doing
web automation composes** (scraping, form automation, AI browser agents). Same
model as Camoufox itself: **universally positioned, narrowly built.**

## Positioning: broad audience, focused build
- **Position broadly** (README/pitch): a resilient stealth-automation primitive.
- **Build narrow + deep** (this repo): one clean primitive — API discovery +
  adaptive stealth on Camoufox. Broad applicability *emerges* from the clean
  primitive; we do NOT build every automation use-case (that's the shallow stall).

## Architecture
```
target site
   │
   ▼  Camoufox (engine-level stealth — the base Hydra sits on)
[1] STEALTH ACCESS        get past the defenses (static stealth, v0.1)
   │
   ▼
[2] API DISCOVERY         intercept XHR/fetch → find the internal JSON API
   │                      → capture auth/params → generate a browser-free client
   ▼
[3] ADAPTIVE STEALTH      on block: diagnose which layer leaked → adapt → recover
   │                      (the novel, self-healing flagship — v0.2)
   ▼
returns: a working, resilient client to the site's data channel
```

## What Hydra is NOT (non-goals)
- **Not a DOM scraper.** DOM extraction (parsing data out) is a trivial downstream
  step, not the point. A minimal LLM-DOM fallback is optional (v0.3), for sites
  with no usable API — never the focus.
- **Not a general automation platform.** It's a *primitive*, not an app that does
  form-filling + agents + everything. Others build those *on* it.
- **Not a CAPTCHA solver.** It *avoids* triggering detection and adapts; it does
  not solve interactive puzzles.
- **Not an Apollo/SaaS-paywall bypass.** Public sites only; legit use.

## Built on
- **Camoufox** (Firefox, engine-level fingerprint spoofing) — the static-stealth
  base. Hydra is the *adaptive* layer above it.

_Related: leankv/flint (kernel work — the other lane) · Prospector (the finder's
grounded-extraction DNA reused for API discovery)._
