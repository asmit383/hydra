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
  endpoint + its auth, and generates a **browser-free client**.
- **Adaptive, self-healing stealth.** When Hydra gets blocked, it **diagnoses
  which fingerprint layer leaked** and **adapts** — instead of silently dying.

It's not a scraper — it's a **resilient stealth-automation primitive** that anyone
automating the web can build on, the way you build on Camoufox itself.

## Status
🚧 Early. See `phases.md`. **v0.1: internal-API discovery with stealth access.**

## Quick start (once v0.1 lands)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m camoufox fetch
python examples/find_api.py https://example.com
```

Built on [Camoufox](https://github.com/daijro/camoufox) — engine-level fingerprint
spoofing. Hydra is the *adaptive* layer above it.
