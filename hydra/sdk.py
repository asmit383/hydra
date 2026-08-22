"""Hydra — the stateful SDK object. ONE persistent stealth session an AI *or* a script drives.

Wraps session (heal) + discovery (discover) + detection (detect) + behavior (human) into one
object. The identity lifecycle is BAKED IN and not user-configurable:

  1. ONE persona per session, sampled when the identity is born (from the Aalto corpus;
     falls back to a guessed persona if the corpus isn't present).
  2. persona + fingerprint + session travel together — `relaunch` mints a new identity
     (new persona), hot levers (patience / rotate / drop_session) keep it.
  3. behavior is OURS — `humanize=False` always, `Human` always drives, NO user knob.
     The only escape hatch to raw input is `h.page`.

CLI, MCP, and hand-written scrapers all wrap this SAME object. The AI is an OPTIONAL consumer
(via `observe()`); everything else — navigate / capture / type / click / heal / fetch — is
deterministic and callable directly, no LLM required.
"""
from __future__ import annotations

import random

from hydra.detect import classify
from hydra.discover import (_BLOCK_HOSTS, _is_noise, _looks_like_data, _shape,
                            capture as _capture)
from hydra.heal import HealSession
from hydra.human import Human
from hydra.session import load_proxies, parse_proxy

# cost-ordered heal ladder (cheapest → dearest, by what you lose) — used to ESCALATE when a
# lever fails and the block recurs, instead of repeating the same failing lever. `patience` is
# a humanized wait (drift, not a frozen cursor) — behavior is always on, so there is no separate
# "act human" rung. `rotate_exit` is dropped for native / single-exit sessions (nothing to
# rotate to) — see `_ladder` in __init__.
_LADDER = ("patience", "rotate_exit", "drop_session", "relaunch")


def _auth_of(headers: dict) -> list[str]:
    """Summarize the auth on a request WITHOUT echoing secret values (never leak cookies)."""
    h = {k.lower(): str(v) for k, v in headers.items()}
    tags = []
    if h.get("authorization", "").lower().startswith("bearer"):
        tags.append("bearer")
    if "cookie" in h:
        tags.append("cookie")
    if any("api-key" in k or "x-api" in k or "apikey" in k for k in h):
        tags.append("api-key")
    return tags


def _replay_headers(headers: dict) -> dict:
    """Which captured request headers to FORWARD on a warm-session replay: auth + content-type
    only. Cookies ride `credentials:'include'`; browser-managed headers (host / origin / sec-*
    / user-agent) must NOT be set from JS (forbidden/ignored), so we drop everything else."""
    fwd = {}
    for k, v in (headers or {}).items():
        lk = k.lower()
        if lk in ("authorization", "content-type") or "api-key" in lk or "x-api" in lk:
            fwd[k] = v
    return fwd


def _make_persona(seed, corpus_path):
    """A coherent persona from real Aalto data; fall back to the guessed sampler if the
    corpus isn't available (e.g. a fresh clone without the gitignored dataset)."""
    try:
        from hydra.behaviorforge import PersonaGenerator
        return PersonaGenerator.from_file(corpus_path).generate(seed=seed)
    except Exception:
        from hydra.human import sample_persona
        return sample_persona(seed)


# ── perception core (v2) ────────────────────────────────────────────────────────
# One DOM pass → a rich element model. Two consumers project from it: the SDK (rich,
# filterable dicts via observe()) and the MCP layer (token-lean snapshot()). Ranks by
# relevance (never truncates by DOM order), sees real on-screen state (viewport +
# occlusion), dedups, and flags BLOCKERS (consent bars / popups) with the verb to clear
# them — size-independent, because real ones aren't role=dialog (measured on Sisal).
_PERCEIVE_JS = r"""() => {
  const vw = innerWidth, vh = innerHeight;
  const ACCEPT = /accetta|acconsent|consenti|ho capito|allow all|accept all|accept/i;
  const CLOSE  = /chiudi|^\s*[×✕✖xX]\s*$|close|no,? grazie|salta|dismiss|not now/i;
  const REJECT = /rifiuta|reject|nega|decline/i;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const fixedRoot = (el) => {                       // nearest overlay-ish ancestor, any size
    let n = el, hop = 0;
    while (n && hop++ < 12) {
      const c = getComputedStyle(n);
      if (c.position === 'fixed' || c.position === 'sticky' ||
          (c.position === 'absolute' && (parseInt(c.zIndex) || 0) >= 1000) ||
          (n.getAttribute && n.getAttribute('role') === 'dialog')) return n;
      n = n.parentElement;
    }
    return null;
  };
  const els = [...document.querySelectorAll('a,button,input,select,textarea,[role=button]')];
  const out = []; let id = 0;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || !el.offsetParent) continue;   // real size + laid out
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const inVp = r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
    let occ = false;                                 // covered by something else at its center?
    if (inVp) {
      const cx = Math.min(vw - 1, Math.max(0, r.left + r.width / 2));
      const cy = Math.min(vh - 1, Math.max(0, r.top + r.height / 2));
      const t = document.elementFromPoint(cx, cy);
      occ = !(t && (t === el || el.contains(t) || t.contains(el)));
    }
    el.setAttribute('data-hydra-id', String(++id));
    let label = clean(el.getAttribute('aria-label') || el.innerText || el.value ||
                      el.placeholder || el.title || el.name || el.alt);
    if (!label) { const s = el.querySelector && el.querySelector('title');   // icon-only fallback
                  label = clean(s && s.textContent); }
    let verb = null, overlayText = '';
    if (ACCEPT.test(label) || CLOSE.test(label) || REJECT.test(label)) {
      const fr = fixedRoot(el);                      // a dismiss-ish label INSIDE an overlay = blocker
      if (fr) { overlayText = clean(fr.innerText).slice(0, 80);
                verb = ACCEPT.test(label) ? 'accept' : (REJECT.test(label) ? 'reject' : 'close'); }
    }
    const tag = el.tagName.toLowerCase();
    const role = verb ? 'dismiss'
      : (tag === 'input' || tag === 'select' || tag === 'textarea') ? 'field'
      : (el.getAttribute('role') === 'tab') ? 'tab'
      : (tag === 'a') ? 'link' : 'button';
    const oauth = /google|apple|facebook|microsoft|github|\bsso\b/i.test(label);
    out.push({id, tag, type: el.type || null, label, role, verb, overlayText, oauth,
              inVp, occ, box: [Math.round(r.x), Math.round(r.y),
                               Math.round(r.width), Math.round(r.height)]});
  }
  return {vw, vh, scrollY: Math.round(scrollY),
          scrollHeight: document.documentElement.scrollHeight, els: out};
}"""

_VERB_PREC = {"accept": 0, "close": 1, "reject": 2}   # clear consent (accept) before popups


def _rank(recs, vw, vh, *, in_viewport=None, role=None, contains=None, limit=60):
    """Dedup + filter + RANK the raw perception records by relevance (blocker > on-screen-center
    > labeled > content), then take the top `limit`. Pure — takes records, returns records."""
    cx0, cy0 = vw / 2, vh / 2
    diag = max(1.0, (vw * vw + vh * vh) ** 0.5)
    best, order = {}, []
    for e in recs:
        if e.get("occ"):                                   # covered → not actually clickable
            continue
        if in_viewport and not e["inVp"]:
            continue
        if role and e["role"] != role:
            continue
        if contains and contains.lower() not in (e["label"] or "").lower():
            continue
        lbl = e["label"]
        key = (lbl, e["role"], e["box"][2], e["box"][3]) if lbl else None   # dedup identical twins
        if key is not None and key in best:
            j = best[key]
            if e["inVp"] and not order[j]["inVp"]:         # keep the on-screen twin
                order[j] = e
            continue
        if key is not None:
            best[key] = len(order)
        order.append(e)

    def score(e):
        x, y, w, h = e["box"]
        s = 100.0 if e.get("verb") else 0.0                # a blocker to clear = top priority
        if e["inVp"]:
            s += 5
        dist = (((x + w / 2) - cx0) ** 2 + ((y + h / 2) - cy0) ** 2) ** 0.5
        s += 2 * max(0.0, 1 - dist / diag)                 # centrality 0..2
        if e["label"]:
            s += 1
        if e["role"] in ("link", "button", "tab", "field"):
            s += 0.5
        return -s
    order.sort(key=score)
    return order[:limit]


def _pick_blockers(recs):
    """The controls that gate the page — one per overlay, preferring ACCEPT (a consent bar's
    accept also mints the cookie the API needs) > CLOSE > REJECT. Ordered accept-first."""
    best = {}
    for e in recs:
        if not e.get("verb") or e.get("occ"):
            continue
        k = e["overlayText"] or e["label"]
        if k not in best or _VERB_PREC[e["verb"]] < _VERB_PREC[best[k]["verb"]]:
            best[k] = e
    return sorted(best.values(), key=lambda e: _VERB_PREC[e["verb"]])


class Hydra:
    def __init__(self, *, proxies: str | None = None, proxy: str | None = None,
                 seed: int | None = None, headful: bool = False, state: str | None = None,
                 corpus: str = "data/aalto_corpus.json"):
        exits = [parse_proxy(proxy)] if proxy else (load_proxies(proxies) if proxies else [])
        self._exits = [e for e in exits if e]
        self._on_proxy = bool(self._exits)            # start on the exit if any proxy was given
        # native / single exit has no pool → the rotate rung is a dead no-op; drop it so the
        # ladder is honest: patience(humanized) → drop_session → relaunch. A pool keeps rotate.
        self._ladder = _LADDER if len(self._exits) >= 2 else tuple(l for l in _LADDER if l != "rotate_exit")
        # pin a concrete seed even if the user didn't → keystroke AND mouse share ONE identity
        self._seed = seed if seed is not None else random.randrange(1, 2**31)
        self._corpus, self._headful, self._state = corpus, headful, state
        self.session: HealSession | None = None
        self.persona = None
        self.human: Human | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def __enter__(self):
        self.persona = _make_persona(self._seed, self._corpus)
        self.session = HealSession(self._exits, headless=not self._headful,
                                   storage_state=self._state,
                                   humanize=False).open(on_proxy=self._on_proxy)  # rule 3: humanize OFF
        self._bind_human()
        self._seen: set = set()           # (url, body) keys already captured this session (dedup)
        self.context: list[dict] = []     # every candidate + WHICH action fired it
        return self

    def __exit__(self, *a):
        if self.session:
            self.session.close()

    def _bind_human(self):
        """(Re)bind Human to the current session page. Seed the mouse from the PERSONA's own
        seed so keystroke + mouse are the same person — and a relaunch's fresh persona gets a
        fresh mouse too (rule 2), instead of the old identity's mouse."""
        self.human = Human(self.session.page, persona=self.persona, seed=self.persona.seed)

    # ── properties (the state) ────────────────────────────────────────────────
    @property
    def page(self):                       # raw Playwright page — the only escape hatch
        return self.session.page

    @property
    def exit(self) -> str:
        return self.session.label()

    # ── navigation + discovery ────────────────────────────────────────────────
    def navigate(self, url: str, *, wait_until: str = "domcontentloaded", timeout: int = 30000):
        self.session.page.goto(url, wait_until=wait_until, timeout=timeout)
        return self

    def capture(self, url: str, *, label: str = "capture", navigate: bool = True,
                interact: bool = True, scroll_steps: int = 6,
                challenge_wait_ms: int = 6000, max_heal: int = 4):
        """Discover the page's data (APIs / SSR / streams), self-healing through blocks on the
        PERSISTENT session with an **escalating** cost ladder (patience → rotate → drop_session →
        relaunch; rotate is dropped when there's no proxy pool) — walk DOWN a rung when the same
        block recurs, instead of
        repeating a failing lever). Findings are merged into `h.context` (tagged `label`,
        dedup'd with open/act). `navigate=False` discovers the CURRENT page without
        re-navigating (composes with an open→act traversal). Returns the CaptureResult."""
        result, rung, last_class, do_nav = None, -1, None, navigate
        for attempt in range(1, max_heal + 1):
            result = _capture(url, page=self.session.page, interact=interact,
                              scroll_steps=scroll_steps, challenge_wait_ms=challenge_wait_ms,
                              scroll_rng=self.human._rng, scroll_scale=self.persona.base_ms / 135.0,
                              navigate=do_nav)
            self._merge(result, label)                          # #3: ONE recorder — feed context/_seen
            v = classify(result.signals) if result.signals is not None else None
            if v is None or not v.blocked or not v.self_heal or attempt >= max_heal:
                return result                                   # got it, or terminal, or out of tries
            # #5 escalate: same block recurs (lever didn't clear it) → next rung; else start at
            # the diagnosed lever's rung — on THIS session's ladder.
            if v.block_class == last_class:
                rung = min(rung + 1, len(self._ladder) - 1)
            elif v.lever in self._ladder:
                rung = self._ladder.index(v.lever)
            elif v.lever == "rotate_exit":       # native/1-exit: no IP to rotate → relaunch is the only card
                rung = len(self._ladder) - 1
            else:                                # unknown / cost_ladder → walk the ladder from the top
                rung = 0
            last_class = v.block_class
            reopened = self._heal(self._ladder[rung])
            do_nav = navigate or reopened                       # #6: re-nav only if asked, or reopened
        return result

    def _merge(self, result, label: str):
        """#3: fold a CaptureResult's candidates into the ONE shared recorder (context/_seen),
        tagged `label`, dedup'd by (url, body) — so capture() and open()/act() never double-report."""
        for c in getattr(result, "candidates", None) or []:
            key = (c.url, c.post_data)
            if key in self._seen:
                continue
            self._seen.add(key)
            self.context.append({"url": c.url, "method": c.method, "status": c.status,
                                 "shape": c.shape, "sample": c.sample, "size": c.size,
                                 "auth": _auth_of(c.request_headers), "fired_on": label,
                                 "request_headers": c.request_headers, "post_data": c.post_data})

    def _heal(self, lever: str) -> bool:
        """Apply a lever on the live session; RETURN whether the page was reopened (so capture
        knows it must re-navigate). Only a relaunch mints a new identity (rule 2)."""
        reopened = False
        if lever == "patience":                   # humanized wait: the challenge clears while the
            self.human.idle(4000)                 # cursor drifts — never a frozen page (behavior is default)
        elif lever == "drop_session":
            self.session.drop_session()
        elif lever == "rotate_exit":
            r = self.session.rotate()
            if r == "cold":                       # native→proxy relaunch (page changed)
                reopened = True
            elif r is None:                       # no pool → relaunch
                self.session.relaunch(); self._reidentify(); reopened = True
        else:                                     # relaunch / fingerprint / unknown
            self.session.relaunch(); self._reidentify(); reopened = True
        if reopened:
            self._bind_human()
        return reopened

    def _reidentify(self):
        """A relaunch = a new device = a new person (rule 2): fresh persona AND fresh mouse —
        a new concrete seed so the whole new identity is coherent (keystroke + mouse together)."""
        self.persona = _make_persona(random.randrange(1, 2**31), self._corpus)

    # ── context capture: tag each discovered API with the ACTION that fired it ──
    def _record(self, do, label, wait_ms):
        """Run `do()` (a navigate or a click) while intercepting responses, and capture the
        NEW data endpoints it triggers — each TAGGED with `label` (the action). Reuses the
        discovery filters (noise / looks-like-data / shape). Dedup'd across the session."""
        import json as _json
        page, new = self.session.page, []

        def on_resp(response):
            try:
                u, low = response.url, response.url.lower()
                key = (u, response.request.post_data)   # dedup by URL+body (keep POST/GraphQL ops)
                if key in self._seen or _is_noise(u) or any(b in low for b in _BLOCK_HOSTS):
                    return
                ctype = (response.headers or {}).get("content-type", "").lower()
                if any(b in ctype for b in ("image/", "font/", "video/", "audio/",
                                            "text/css", "javascript")):
                    return
                data = response.json()
                if not _looks_like_data(data):
                    return
                self._seen.add(key)
                shape, sample = _shape(data)
                req = response.request
                cand = {"url": u, "method": req.method, "status": response.status,
                        "shape": shape, "sample": sample, "size": len(_json.dumps(data)),
                        "auth": _auth_of(req.headers), "fired_on": label,       # ← the CONTEXT
                        "request_headers": dict(req.headers), "post_data": req.post_data}  # for replay
                new.append(cand)
                self.context.append(cand)
            except Exception:
                pass

        page.on("response", on_resp)
        try:
            do()
            page.wait_for_timeout(wait_ms)
        finally:
            page.remove_listener("response", on_resp)
        return new

    def open(self, url: str, *, label: str = "load", wait_ms: int = 3000) -> list[dict]:
        """Navigate + capture the APIs that fire on LOAD, tagged `label`. Like navigate(),
        but records what fired (the start of a context-tagged interaction session)."""
        return self._record(
            lambda: self.session.page.goto(url, wait_until="domcontentloaded", timeout=30000),
            label, wait_ms)

    def act(self, target, label: str = "", *, wait_ms: int = 2500) -> list[dict]:
        """Click `target` (a selector or an observe() id) and capture the APIs that click
        TRIGGERS, tagged with `label`. This is how interaction-gated data — odds behind a
        click, a market tab, a sport switch — gets discovered *with the action that reveals
        it*. New candidates are returned and appended to `h.context`."""
        return self._record(lambda: self.click(target), label, wait_ms)

    # ── behavioral actions (delegate to Human; act by selector OR observe() id) ─
    def _resolve(self, target):
        return f'[data-hydra-id="{target}"]' if isinstance(target, int) else target

    def type(self, target, text: str, **kw):
        return self.human.type(self._resolve(target), text, **kw)

    def click(self, target):
        return self.human.click(self._resolve(target))

    def move_to(self, target):
        return self.human.move_to(self._resolve(target))

    def idle(self, ms: float):
        return self.human.idle(ms)

    def scroll(self, **kw):
        return self.human.scroll(**kw)

    # ── replay (warm-session in-page fetch, credentials included) ──────────────
    def fetch(self, candidate):
        """Replay a discovered endpoint from INSIDE the live session — GET, **POST, or
        GraphQL**. Sends the captured method, POST body, and header-auth (bearer / api-key /
        content-type); `credentials:'include'` carries the browser-minted clearance cookie a
        crafted httpx call can't. Accepts an ApiCandidate OR a context dict (from open/act)."""
        def g(k, default=None):
            return candidate.get(k, default) if isinstance(candidate, dict) else getattr(candidate, k, default)
        url = g("url")
        method = (g("method") or "GET").upper()
        body = g("post_data")                                  # POST / GraphQL body
        headers = _replay_headers(g("request_headers") or {})  # bearer / api-key / content-type
        return self.session.page.evaluate(
            """async ([url, method, body, headers]) => {
                const opt = {method, credentials: 'include', headers};
                if (body && method !== 'GET' && method !== 'HEAD') opt.body = body;
                const r = await fetch(url, opt);
                const t = await r.text();
                try { return {status: r.status, json: JSON.parse(t)}; }
                catch { return {status: r.status, text: t.slice(0, 200000)}; }
            }""", [url, method, body, headers])

    # ── AI action space (OPTIONAL — only when the caller doesn't know the flow) ─
    def observe(self, *, role=None, contains=None, in_viewport=None, limit=60):
        """The eyes (v2). RANKED, deduped interactive elements — each with WHAT it is
        (`label`/`role`), WHERE it is (`box=[x,y,w,h]` + `inVp`), whether it's actually
        clickable (occluded ones dropped), a `verb` if it's a blocker (accept/close/reject),
        an `oauth` trap flag, and a stable `data-hydra-id` to act on (`h.click(id)`). Ranked by
        relevance (blocker > on-screen-center > labeled > content) — NOT truncated by DOM order.
        Filters: `role=` ('link'/'button'/'field'/'tab'/'dismiss'), `contains=` (label
        substring), `in_viewport=True` (only what's on screen)."""
        m = self.session.page.evaluate(_PERCEIVE_JS)
        return _rank(m["els"], m["vw"], m["vh"], in_viewport=in_viewport,
                     role=role, contains=contains, limit=limit)

    def blockers(self):
        """The overlays gating the page (consent bars / popups), one control per overlay with
        the `verb` to clear it — accept-first. Empty when nothing is blocking."""
        m = self.session.page.evaluate(_PERCEIVE_JS)
        return _pick_blockers(m["els"])

    def dismiss_blockers(self, *, max_rounds=4):
        """Clear ALL overlays before navigating — a consent bar wants ACCEPT (it also mints the
        cookie the odds API needs), a promo/AI popup wants CLOSE. Handles several at once by
        clearing one, re-scanning (the DOM changes), and repeating. Returns what it dismissed."""
        cleared = []
        for _ in range(max_rounds):
            bl = self.blockers()
            if not bl:
                break
            b = bl[0]                                  # accept-first ordering
            try:
                self.click(b["id"])
            except Exception:
                break
            cleared.append(b["label"])
            self.session.page.wait_for_timeout(900)
        return cleared

    def snapshot(self, *, limit=30):
        """The MCP projection — the SAME perception, token-lean for an LLM: what's blocking (+
        how to clear it), whether there's more below the fold (→ scroll), and the ranked menu
        with click points. Same ids/coords as observe(), so a model's pick maps 1:1 to an
        action. Carries no headers/tokens — safe to hand to the model."""
        m = self.session.page.evaluate(_PERCEIVE_JS)
        els = _rank(m["els"], m["vw"], m["vh"], limit=limit)
        below = sum(1 for e in m["els"] if e["box"][1] >= m["vh"])
        return {
            "blocking": [{"id": b["id"], "verb": b["verb"], "label": b["label"]}
                         for b in _pick_blockers(m["els"])],
            "scroll": {"y": m["scrollY"], "height": m["scrollHeight"],
                       "hasMore": below > 0, "below": below},
            "viewport": [m["vw"], m["vh"]],
            "elements": [{"id": e["id"], "role": e["role"], "label": e["label"],
                          "at": [e["box"][0] + e["box"][2] // 2, e["box"][1] + e["box"][3] // 2]}
                         for e in els],
        }


__all__ = ["Hydra"]
