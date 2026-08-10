<div align="center">

# 🐍 Hydra

**A stealth-automation primitive on Camoufox — auto-discovers a site's internal
API and self-heals when detection breaks.**

*Cut off a head, two grow back.*

</div>

---

Most web automation is brittle and static: it scrapes the fragile **DOM**, and its
stealth is fixed — when a site's detection updates, it silently gets blocked and a
human has to re-patch it.

Hydra goes one level deeper and closes the loop:

- **Finds the internal API, not the DOM.** A site's internal JSON API rarely
  changes on a visual redesign — hit *that* and you don't break. Hydra drives a
  stealth browser (Camoufox), intercepts the XHR/fetch traffic, discovers the
  endpoint + its auth, and (v0.1.x) generates a **browser-free client**.
- **Adaptive, self-healing stealth** *(v0.2)*. When Hydra gets blocked, it
  **diagnoses which fingerprint layer leaked** and **adapts** — instead of
  silently dying.

It's not a scraper — it's a **resilient stealth-automation primitive** that anyone
automating the web can build on, the way you build on Camoufox itself.

## Status
🚧 Early, but the core works. See `phases.md`.

**v0.1 — internal-API discovery with stealth access: working.** Point Hydra at a
JS-heavy site (even one behind Akamai/Cloudflare, via a proxy) and it surfaces the
internal JSON endpoints — ranked biggest-first — with the request + auth headers
captured for replay. Remaining v0.1 piece: `client.py` (browser-free replay).

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .          # installs the `hydra` command
python -m camoufox fetch

# discover the internal API on your own ISP IP
hydra capture https://example.com
```

### It finds the endpoint the page hides
```
→ discovering internal APIs on https://example.com  (via native ISP IP) ...

found 6 candidate endpoint(s), biggest first:

[1] GET https://api.example.com/v1/catalog/listings?page=1
    status 200 · 412,088 bytes · list[240]
    auth headers present: ['authorization']
    sample: [{"id": 91823, "title": "...", "price": ...}, ...]
```
That's the real data endpoint the SPA calls at runtime — not the DOM. Trackers,
analytics, fonts, and consent/CMP config are filtered out automatically.

### Proxies — three modes
Some sites are geo-locked or gate by IP reputation. Hydra hands you Camoufox's
native geoip on your own IP, or routes through a proxy (geoip auto-aligned to the
proxy's exit IP so timezone/locale match):

```bash
# native — your ISP IP (default)
hydra capture <url>

# explicit — one proxy
hydra capture <url> --proxy explicit --proxy-str ip:port:user:pass

# file — random line from a proxies.txt (ip:port:user:pass per line)
PROXIES_FILE=./proxies.txt hydra capture <url> --proxy file
```

`--json` emits the candidates as JSON (for piping); `--headful` shows the browser.

Built on [Camoufox](https://github.com/daijro/camoufox) — engine-level fingerprint
spoofing. Hydra is the *adaptive* layer above it.
