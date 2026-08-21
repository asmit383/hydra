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
- [x] **Content-scored extraction** — rank record sets by content signal (money keys
      like price/sku/offers weighted 10× over name/author/rating), and sample the
      richest record — so the *product+price* wins over config/taxonomy/reviews.
      Fixed StockX/Vinted/Home Depot previewing config instead of the price.
- [x] **Behavioral healing** — warmup (jittered mouse/scroll/dwell) + slower humanize
      on the same exit for a diagnosed behavioral block (see below).

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

---

## Shipped since — detection rebuild, session-preserving heal, behavioral engine ✅

**Vendor-free block detection (`detect.py`, v0.3).** Replaced the `diagnose` vendor→layer
table with an **oracle-anchored** classifier: anchor on *did I get the data?* (the one signal
the adversary can't fake), then sub-classify the failure from vendor-free signals (status,
headers, clearance cookies, challenge-shape, edge-vs-origin) → block-class → cheapest lever.
Full signal→reasoning→verdict trace. Validated live (StockX/Zillow clean, G2 403-but-data →
clean, real 503 → rotate).

**Session-preserving self-heal (`heal.py` + `relay.py`, v0.4).** The truth-table levers now
execute on ONE persistent session: `patience` / `rotate` (a local **relay** swaps the exit IP
with NO relaunch, keeping fingerprint + warm clearance) / `drop_session` (clear cookies, keep
fp) / `relaunch` (nuclear, last). Proven: exit IP rotates while fingerprint + session cookie
survive. Cost-ordered ladder — touch the fingerprint *last* (it's the only cold lever).

**Behavioral engine — keystroke (`human.py`, v0.1).** The layer Camoufox does NOT own — its
`humanize` is a mouse *path* only; there is no typing model and no keystroke dataset anywhere
in it. A 3-level, **data-backed** keystroke model:
- **digraph latency** (same-finger slow / hand-alternation fast — a *multiplier* on a
  per-persona base, never a fixed ms),
- **per-bigram individuality** (this typist's `th` ≠ their `he`, each stable),
- **autocorrelated tempo** (Ornstein–Uhlenbeck drift — not IID), log-normal timing,
  boundary pauses, dwell, and typo→backspace→retype.
Never uses `fill()` (zero keystroke events = instant flag); drives real `keyboard` events
(protocol-injected → `isTrusted`, unlike a `dispatchEvent` bot). Pure-model tested, no browser.

**BehaviorForge (`behaviorforge.py`) + corpus pipeline (`corpus.py`).** The behavioral analog
of BrowserForge: sample a *coherent* persona (one per session, tied to the identity — new
fingerprint ⇒ new persona) from **real data**, not guessed independent ranges. The pipeline
extracts per-user Persona vectors from the **Aalto 136M-keystroke** dataset
(`vector_from_sections → build_corpus → PersonaGenerator.from_file`).
- **Ran it: 3000 real typists extracted, digraph model VALIDATED then CALIBRATED on real
  data.** Measured multipliers (bigram flight / typist's base): alternation **0.80**,
  same-hand **0.92**, same-finger **1.06** — `_digraph_mult` now uses these (I'd *guessed*
  0.85/1.15/1.6; same-finger was ~50% too strong → robotic typing). Also corrected: base↔dwell
  coupling is **weak in reality (~0.14)**, not the strong coupling I assumed; and my clamp
  bounds truncated real variance (pinned err/sigma → widened to the real range). **Measured >
  guessed, live — the data corrected my guesses three times.**
- **Scope: desktop-only, correctly** — Camoufox only generates desktop fingerprints
  (`os=('linux','macos','windows')`), so mobile typing would be *incoherent* with the fingerprint.

**Mouse behavioral layer — MouseForge (`mouseforge.py`).** Camoufox's `humanize` is ONE
algorithm → every agent moves identically → a fleet signature at scale. So the trajectory is
generated per-persona: **dense sampling** (~1 pt/4px — sparse sampling was a "botistic" tell),
ease-in-out velocity, sine-arc bow, small tremor, coherent with the typing persona (fast typist
→ fast mouse). **Proven diverse: 5000 sessions → 5000 distinct paths.** Plus `human.idle` — a
gentle idle drift that fills the LLM round-trip so the cursor isn't FROZEN between agent actions
(the agent-specific tell). **Honest:** mouse has no dataset yet — real motor-science models
(minimum-jerk/Fitts/tremor) with guessed params; structurally-human, not measured-human (the
Balabit/SapiMouse extraction is the mouse's Aalto, not done).

**Stealth benchmark run:** Sannysoft **30/31** (1 fail = Firefox correctly lacking
`window.chrome`); CreepJS **0% headless / 0% stealth-detected**. The *body* passes the standard
fingerprint gauntlets; the *behavioral* layer has no public scorer (validation = our own
KS-harness + real-target get-through, both pending).

**The SDK — SHIPPED (`hydra/sdk.py`).** `with Hydra(proxies=..., seed=...) as h:` — ONE
persistent stealth object an AI *or* a plain script drives (one object, three interfaces; the
AI is an optional consumer). Identity lifecycle baked in: one persona per session (Aalto),
persona+fp+session travel together, **humanize=OFF / behavior always ours, no user knob**.
Surface: `navigate · open/capture (discover+heal) · act (interaction) · observe (perception) ·
type/click/move_to/idle (humanized) · fetch (warm-session replay) · page/persona/exit`.
- **`observe()`** — visible, labeled interactive elements + **`box=[x,y,w,h]`** (disambiguate
  same-label links) + stable id + `oauth` flag. The AI's eyes.
- **`open()`/`act()` — context capture:** every discovered API tagged with the ACTION that
  fired it (`fired_on`) → the action→API map (the Sisal-class fix).
- **`fetch()`** — in-page `fetch(credentials:'include')` = warm-session replay.

**Proven on real paid work — the SDK pulled LIVE odds off two protected books:** Staryes
(Cloudflare, odds on load → `getTorneoCentrale`) and Sisal (Akamai+geo, warm→tree→card →
`schedaManifestazione`), each in ~5 lines. The agent traversal it teaches: **enter the base
page, warm, apply Hydra outward until the target — never cold-jump the deep URL** (the base
page sets the cookie the fetches need).

---

## The vision — a self-mapping stealth body for AI agents 🧭

Not a discovery tool — a **stealth body an AI agent drives** (fingerprint + self-adaptation +
human behavior), with one catch: **as the agent operates, the body opportunistically
reverse-engineers the site's internal API surface in the background.** So it *amortizes*:
- **First session:** the agent drives the browser to do the task, *and* Hydra discovers +
  classifies the APIs it passes.
- **Next session:** those APIs are known → skip crawling, hit the API directly → **faster and
  cheaper every session.**
- **No useful API?** The agent does it through the browser (crawl/click) — *still* discovering
  as it goes.

The browser is the **fallback**; the discovered API is the **fast path**; the cache **fills
itself** as the agent works. That's the differentiator vs a plain stealth body: it *learns the
site's shortcuts while it operates.*

**Built now:** the body (stealth + session-preserving self-heal), discovery + `gen`, the
**data-backed behavioral layer** (Aalto keystroke + MouseForge), and **the SDK** — `Hydra`
object with `observe`, context capture (`fired_on`), warm-session `fetch`, proven pulling live
odds off two protected books. **Designed, not built:** the amortization *store*, the MCP/agent
layer, the tier-3 "got the target?" check.

### The moat to build: the amortization engine (discover-once → replay-forever)
This is **already the manual workflow** (simone's own docstring: *"Endpoints discovered with
Hydra"* — session 1 discovers, session 2+ warm+fetch). The store just automates it. Needs:
1. **A persistent API store** — per-site: endpoints + classified auth + **warm-recipe** (base
   URL to warm + endpoint pattern), saved across sessions. (Context capture's `fired_on` +
   `fetch` are the ingredients; nothing persists them yet.)
2. **The router** — given a task: *known recipe? → warm+replay (fast). No? → traverse + discover.*
3. **Session-spanning discovery** — `h.context` accumulates within a run (built); persisting it
   across runs is the missing half.

### Also missing (prioritized)
- **Agent/MCP layer** — the LLM driving `observe → decide → act`. The SDK primitives exist
  (`observe`/`act`/`capture`/`fetch`); the brain-on-top is the remaining build. *(SDK itself:
  ✅ shipped.)*
- **The tier-3 "got the target?" check** — the semantic judgment that tells the traversal when
  to stop (LLM). Without it the agent doesn't know it's arrived.
- **Mouse realism — MECHANISM built (MouseForge), data model pending.** Per-persona generated
  trajectory (dense sampling, ease-in-out, sine bow, tremor, coherent with typing speed) +
  `human.idle` for the LLM-freeze gap; proven fleet-diverse (5000→5000). *Still needs:* the
  **data model** — real params off Balabit/SapiMouse (the mouse's Aalto), and external
  validation. Structurally-human today, not yet measured-human.
- **Warm-up / trust context** — arrive via homepage→browse→target (cookies + referrer +
  history) instead of cold-loading a deep URL. Cheap, high antibot ROI, not built (layer 6b).

---

## Next phases — prioritized build order 🎯

Re-ordered after an honest external review + a real run on a heavy, protected SPA.
Ordered by **ROI first**, not by how interesting the work is.

**Two tracks — pick by what you already know:**
- **Known-target** (recon done, you have the URL): `capture <url>` → a handful of
  candidates, trivial to distinguish. *Already solved — don't add machinery here.*
- **Exploratory** (unknown mechanism or URL): needs to *reach and trigger* the data
  — browse + AI curation. Everything below serves THIS track. Never force it on the
  known-target case (broad browsing = more noise + wasted time).

**Positioning (say it out loud):** the *browsing* is **commodity** — plenty of tools
do LLM-drives-a-browser. The wedge is **API-recon + replay** (find the internal
endpoint, classify its auth, hand back a *browser-free replayable client*) plus the
**stealth body** that survives Akamai/DataDome where a vanilla agent 403s. Brain =
the agent (bring your own key); **body = Hydra**.

| # | Phase | Why this slot |
|---|-------|---------------|
| 0.5 | **Sane defaults — kill the footgun.** `domcontentloaded` + bounded waits; heal is **reactive-only, never proactive**; heavy modes (scroll/interact/heal) opt-in with a time budget. | A real run hung **10 min** on default flags (networkidle + proactive heal + scroll on a heavy SPA). Cheap fix, burned me twice. |
| 1 | **Replay-verify + auth-classify + two replay paths.** Fire the captured request, assert same shape → candidate becomes **confirmed**. Label auth (`bearer`/`cookie`/`api-key`/**`signed-token`**) + TTL hint; flag paging params (`startIndex`/`offset`); detect **persisted-query GraphQL** (sha256-pinned → replay the exact `QueryName+hash`, never mutate). Two replay modes, chosen by auth-classify — **default is warm-session, browser-free is the exception:** **(a) warm-session** (`page.evaluate` fetch, `credentials:'include'`, session kept alive) is the **primary path** — most real targets need a clearance cookie (`_abck`/`_px`/`cf_clearance`) that is browser-bound + continuously re-minted by the page's sensor JS, so a lifted cookie 403s within seconds; **(b) browser-free** (httpx) only when `verify` *proves* the token is portable (anon Bearer, static API key, no clearance cookie). Guilty-until-proven-portable. | Highest ROI. Tells me *needs-warm-session (usual) vs headless-replayable (rare)*, and it's the exact primitive the MCP `fetch` tool needs. Warm-session replay is the generalization of how I actually scrape the hardest books (Goldbet: warm the page, let `_abck` settle, in-session fetch). |
| 2 | **Browse-and-capture.** Navigate a human path to *reach* the data, capture on arrival, tag each candidate by the action that fired it. | Data often fires only deep in the site; the agent can't type the URL. Reach it without drowning in transit noise. |
| 3 | **MCP + AI disambiguation.** Expose capture/heal/fetch/login/gen as tools; the agent picks which candidate is the data. | Depends on 1+2. This is "the AI does it by itself." |
| 4 | **Empirical layer attribution.** Instrument the heal ladder to log *what-changed → did-it-unblock*. | Upgrades `diagnose` from a canned vendor→layer table to a *learned* prior. Earns its slot once there's real block data. |
| 5 | **Productization + solver seam.** **Session-oriented SDK** (`with Hydra(...) as h: h.navigate/capture/fetch/heal` + raw `h.page`) — the *stateful session* the warm-`_abck` runtime needs, that **CLI / MCP / production scrapers all wrap** (one object, three interfaces). Then: pluggable human-verification seam, HAR regression tests, session-reuse/crawl, PyPI. | Lower urgency — **post-interview**. The warm-session requirement forces the SDK design anyway; build it once, get all three interfaces. |

**Near-term demo:** a thin **MCP layer** (~a weekend) so an agent can drive Hydra
live — the fastest way to *show* the loop rather than describe it.

**Honesty corrections baked in (from the review):**
- `diagnose` is a **vendor→layer playbook, not per-request detection** — a prior, not
  proof. Frame it as "names the vendor + applies a playbook"; *learn* the real layer
  via Phase 4.
- Capture stores headers "for replay" but nothing **verifies** replay yet → Phase 1.
- Auth is **dumped, not classified** → Phase 1.
- Ranking picks *biggest*, not *the data* — the human/AI disambiguates → Phase 3.

**Field finding — signed-token antibot (PerimeterX / HUMAN class).** Seen in the wild:
HTML loads **200** (fingerprint passed), but every data XHR returns **412 Precondition
Failed** because the API requires a `_px` cookie + a **signed token minted by the live
browser's sensor** — a crafted or out-of-session replay never carries it. Actions:
- `diagnose`: treat **412 on XHR while the HTML is 200** as a distinct signature →
  "signed-token antibot; data needs an in-session fetch, not a crafted replay."
- auth-classify (Phase 1) labels it **browser-minted / short-TTL → not
  headless-replayable** → route to **warm-session replay**, not `gen`.
- This is also the first real **behavioral wall** to validate the warmup ladder
  against (the honest gap in §2 below) — the passive-fingerprint books never trip it.

---

## Detection is 6 layers — fingerprint spoofing defeats ONE 🧱

An Amazon probe made this concrete: engine-level fingerprint spoofing (Camoufox)
nails the static fingerprint, but that's **one** of six layers. The others are what
"self-heal" has to reason about — and knowing which are *ceilings* is the honest edge.

| # | Layer | Camoufox? | Move | Fixable / ceiling |
|---|-------|-----------|------|-------------------|
| 1 | Network / TLS (JA3/JA4) | ✅ | — | solved |
| 2 | Browser / JS fingerprint | ✅ | — | solved |
| 3 | **Behavioral** (keystroke timing, mouse, scroll, dwell) | ❌ | **keystroke: SHIPPED — data-backed (Aalto, digraph calibrated)**; **mouse: SHIPPED — MouseForge (per-persona trajectory, fleet-diverse) + LLM-freeze idle**; mouse *data model* (Balabit) pending | **mechanism done; measured-mouse + external validation next** |
| 4 | **Automation instrumentation** (CDP/Juggler driving tells) | partial | human-timed actions, minimal `evaluate` surface | **hard ceiling** (sensor watches *how you drive* — the 412 wall) |
| 5 | **Headless environment** (software GPU, no display/media) | partial | **run headful** | **mostly ceiling** (GPU-less box has physical tells) |
| 6a | **IP reputation** | ❌ | rotate exits + **don't hammer** | **fixable + footgun** |
| 6b | **Session / trust context** (cold: no cookies/referrer/account) | ❌ | **warm-context** (homepage→browse→target) | **fixable** |

### Cheap wins (buildable fast — the pre-interview / near-term shortlist) ⚡
- **Probe-pacing (layer 6a) — highest-value footgun fix.** Discovery that hammers a
  target *burns the IP reputation it depends on* ("hammered Amazon all night → risk
  climbed"). Pace/budget probes + rotate exits *while probing*, not just scraping.
  Folds into **Phase 0.5** (sane defaults).
- **Headful for hard targets (layer 5).** A lot of "headless detection" is just
  detecting headless *mode*; `headless=False` kills that tell for ~free. Residual
  software-GPU ceiling documented, not hidden.
- **Warm-context mode (layer 6b).** Visit homepage → accept cookies → browse a step →
  hit target, carrying cookies + a real **referrer chain**. This is **Phase 2
  (browse-and-capture) doing double duty** — reaches the deep page *and* builds trust
  context. One primitive, two payoffs.
- **Behavioral entropy (layer 3).** Micro-jitter on top of humanize + scroll/dwell as
  default warmup — refines the §2 behavioral remediation (entropy + purpose, not volume).

Honest ceilings to **name, not claim**: automation-instrumentation (4) and machine
signals (5) aren't beaten by spoofing harder — you beat them with a good environment
and by not looking automated. That's the Akamai/PX sensor-VM territory.

---

## Phase 4 deep-dive — empirical attribution via orthogonal levers 🔬

*(The design for making `diagnose` universal. **Not built** — today it's the canned
table. This is "how I'd make it learn," not "how it works.")*

**Key on the block, not the brand.** A signal (`429`) maps to *multiple* layers (IP /
API-key / fingerprint / session), so it only gives **suspects**. The **culprit** comes
from the empirical loop: a block is a **free binary oracle** — change one lever,
re-request, the site labels it cleared/not-cleared. Change ONE lever holding the rest
constant → if it clears, that dimension was the cause (recover + attribute at once) →
log it → the table becomes a **learned prior** the measurement can overrule. Works on
vendors never seen. **It's a contextual bandit, not full RL** (state=signal,
arms=levers, reward=cleared; no sequential credit assignment).

**The orthogonal-lever problem + fix.** Attribution needs to vary one factor holding
others constant — but Camoufox sets factors at launch and **relaunch resets everything
+ re-rolls the fingerprint** (can't hold it constant or repeat it). Fix: **move factors
off the launch lifecycle onto a live session** — 4 of 5 levers become *hot*:

| Lever | Isolate via | Hot/Cold |
|---|---|---|
| IP / exit | **local proxy relay** (browser → `localhost`; swap upstream behind it) | 🔥 |
| Session | `clear_cookies` / save+restore `storage_state` | 🔥 |
| Auth token | fetch fresh token, swap header | 🔥 |
| Behavioral | same session, drive differently | 🔥 |
| Fingerprint | **pin it** (BrowserForge config) → relaunch changes *only* it, restore rest | ❄️ |

Payoffs: **cost-ordering falls out** (hot=cheap, test first; fingerprint=expensive,
last), and it **forces the session SDK** — orthogonal attribution is impossible with
one-shot CLI calls; it needs a warm session with independent knobs. (Ties Phase 4 to
the Phase-5 `Hydra` SDK — same substrate.)

**Irreducible ceilings (name, don't claim to beat):** TLS-JA3 vs JS-fingerprint are
coupled to the build (one engine = both); **server cross-binding** — Akamai binds the
token to IP+TLS, so rotating IP alone kills the token (you orthogonalize *your* inputs,
not *their* bindings); data-starved (only learns on real blocks → Amazon = training data).

---

## NOT covered yet ⬜  (honest gaps — real mechanisms, not edge cases)

### 1. Typed-search interaction
APIs that fire only on **keystrokes** — Algolia, autocomplete, search-as-you-type
(the YC/DocSearch case). The scroll pass doesn't trigger them.
- Approach: `--type "<query>"` — focus a search input, type, wait, intercept.

### 2. Behavioral-layer remediation — BUILT (mechanism), live-validation pending
> **Update:** *keystroke* behavioral realism is now a full **data-backed engine**
> (`human.py` + BehaviorForge + Aalto corpus — see "Shipped since"). This §2 covers the
> **mouse warmup** remediation, which remains the weaker limb (see vision → *Mouse realism*).

A diagnosed behavioral block (PerimeterX) now gets a **distinct** remediation, not
the fingerprint bucket: on the SAME exit it runs a **warmup** (jittered mouse moves
that Camoufox humanizes + back-and-forth scroll + variable dwell) and bumps
**humanize to a slower cursor** — proving there's a human, not swapping IPs. Only
after `behavioral_retries_before_rotate` does it rotate the exit. (`discover._behavioral_warmup`,
`stealth` behavioral branch; unit-tested in `test_stealth.py`.)
- **Honest gap:** validated only in unit tests — I haven't hit a live PerimeterX
  behavioral block to confirm the warmup actually clears one in the wild. The
  mechanism is real; the field proof is pending a real block.
- **Next refinement:** the warmup moves to *random* coordinates. A real human moves
  *toward things* — buttons, images, the price. Bias the moves toward visible
  interactive elements (`page.locator("a, button").bounding_box()` → move near
  those) so the cursor drifts over real targets, not empty space. And make the
  warmup **progressive** — each retry: more moves + slower humanize.

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

## Credibility
- [x] Unit suite — 29 tests, ~fast, no browser; covers discover/embed/diagnose/
      session/gen/cli/stealth and encodes the fixed bugs so they can't regress.
- [x] Breadth harness — `examples/battle_test.py` runs capture over a URL list and
      reports ok/empty/error per site (the "hold up in the wild" test).
- [~] CI — `.github/workflows/tests.yml` written but **not committed** (push token
      lacks GitHub `workflow` scope); add it via the GitHub UI.
- [ ] README demo gif; Show HN.
- [ ] **6-layer stress harness (Amazon, dev-only, PACED).** Amazon trips all six
      layers at once → the ideal punching-bag to develop behavioral/pacing/warm-context
      against. **Must be paced** (dogfood the probe-pacing fix — hammering burns the IP
      and gives a false negative). Dev + war-story only; **never** a live-demo target.
- [ ] **Live-demo kit** — three-pane contrast (`curl` vs vanilla Chromium vs Hydra),
      a summonable-block ladder (429 / local controlled harness), `heal_bench` runner,
      + an **asciinema recording** as the wifi-dies backup. (See interview.md §12.)

---

## Reality check
Request/response discovery is near-universal now: on-load / on-scroll APIs, SSR,
RSC, **any content-type**, behind a login, geo-gated. The genuine frontier is
**streaming (WebSocket/SSE)** and **input-driven discovery (type/click)**. Keep
the public repo generic — no client-specific targets or endpoints.
