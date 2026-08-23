"""SDK surface tests — browser-free (no session opened). Verifies the object model +
the baked-in rules without launching Camoufox."""
from hydra import Hydra
from hydra.human import Persona


def test_constructs_without_opening_a_browser():
    h = Hydra(seed=7)                        # __init__ must NOT open a session
    assert h.session is None and h.human is None
    assert h._exits == []                    # no proxy given → native


def test_proxy_given_starts_on_proxy():
    # a proxies path that doesn't exist → load_proxies returns [] → no exits (graceful)
    h = Hydra(proxies="/no/such/file.txt")
    assert h._on_proxy is False              # empty pool → won't force proxy start


def test_resolve_maps_observe_id_to_selector():
    h = Hydra()
    assert h._resolve(3) == '[data-hydra-id="3"]'    # AI picks id 3 → data attr selector
    assert h._resolve("#email") == "#email"          # a real selector passes through


def test_persona_falls_back_to_guessed_without_corpus():
    from hydra.sdk import _make_persona
    p = _make_persona(seed=7, corpus_path="/no/such/corpus.json")
    assert isinstance(p, Persona) and p.base_ms > 0  # guessed fallback, still a valid persona


class _FakePage:
    """Scripts perceive() element-counts and (optionally) page.url, one per poll iteration."""
    def __init__(self, counts, urls=None):
        self._counts, self._last, self.waits = list(counts), 0, 0
        self._urls, self._url = (list(urls) if urls is not None else None), "u0"

    def wait_for_load_state(self, *a, **k):
        pass

    def evaluate(self, _js):
        if self._counts:
            self._last = self._counts.pop(0)
        return {"els": list(range(self._last))}

    @property
    def url(self):
        if self._urls:
            self._url = self._urls.pop(0)
        return self._url

    def wait_for_timeout(self, _ms):
        self.waits += 1


def _hydra_with_page(page):
    h = Hydra(seed=7)
    h.session = type("S", (), {"page": page})()   # inject a fake session (no browser)
    return h


def test_wait_ready_returns_once_quiescent():
    # a steady page (any size) → ready after the signature holds for settle_polls reads
    h = _hydra_with_page(_FakePage([12] * 10))
    assert h.wait_ready(poll_ms=1, timeout_ms=2000, settle_polls=3) == 12


def test_wait_ready_resets_when_content_still_changing():
    # content keeps changing, then holds at 4 → must return 4 (the settled value), not an earlier one
    h = _hydra_with_page(_FakePage([1, 2, 3, 4, 4, 4]))
    assert h.wait_ready(poll_ms=1, timeout_ms=2000, settle_polls=2) == 4


def test_wait_ready_url_change_resets_settle_window():
    # a stub (3 els) that then REDIRECTS (URL changes) to a different page (9) — the URL change
    # resets the window, so we never trust the stub: must return 9, not 3. Site-agnostic.
    page = _FakePage([3, 3, 9, 9, 9], urls=["stub", "stub", "next", "next", "next"])
    h = _hydra_with_page(page)
    assert h.wait_ready(poll_ms=1, timeout_ms=2000, settle_polls=2) == 9


class _FakeWS:
    def __init__(self, url):
        self.url, self._h = url, {}
    def on(self, ev, fn):
        self._h[ev] = fn
    def fire(self, ev, payload):
        if ev in self._h:
            self._h[ev](payload)


class _WSPage:
    def __init__(self):
        self._ws_handler = None
    def on(self, ev, fn):
        if ev == "websocket":
            self._ws_handler = fn
    def open_ws(self, url):
        ws = _FakeWS(url)
        self._ws_handler(ws)
        return ws


def test_watch_streams_captures_websocket_frames():
    h = _hydra_with_page(_WSPage())
    h.streams, h._streams_page = [], None
    h._watch_streams()
    ws = h.session.page.open_ws("wss://bet365/odds")
    ws.fire("framesent", "subscribe tennis")
    ws.fire("framereceived", "Djokovic 1.42 | Nadal 3.10")
    assert len(h.streams) == 1
    s = h.streams[0]
    assert s["url"] == "wss://bet365/odds" and s["n_received"] == 1
    assert s["sent"] == ["subscribe tennis"] and s["received"] == ["Djokovic 1.42 | Nadal 3.10"]
    h.session.page.open_ws("wss://bet365/odds")          # same URL again → deduped, still one
    assert len(h.streams) == 1


def test_wait_ready_is_bounded_when_page_never_settles():
    # never non-empty → give up at timeout (return 0), not hang
    h = _hydra_with_page(_FakePage([0] * 100))
    assert h.wait_ready(poll_ms=1, timeout_ms=200) == 0


def _healable_hydra(tmp_path, seed=1):
    """A browser-free Hydra with a 2-exit pool (so the full ladder incl. rotate_exit is live) and
    stubbed session/human/persona — enough for open_healed()'s loop without launching Camoufox."""
    from hydra import Hydra
    px = tmp_path / "p.txt"
    px.write_text("1.1.1.1:8000:u:p\n2.2.2.2:8000:u:p\n")
    h = Hydra(proxies=str(px), seed=seed)
    assert h._ladder == ("patience", "rotate_exit", "drop_session", "relaunch")
    h.human = type("H", (), {"_rng": None})()
    h.persona = type("P", (), {"base_ms": 135.0})()
    h.session = type("S", (), {"page": object()})()
    h._seen, h.context = set(), []
    return h


class _Res:
    def __init__(self, sig):
        self.signals, self.candidates = sig, []


def _script_capture(monkeypatch, signals_seq):
    """Make hydra.sdk._capture return a scripted Signals per navigate; count the calls."""
    import hydra.sdk as sdk
    calls = {"n": 0}

    def fake(url, **k):
        i = min(calls["n"], len(signals_seq) - 1)
        calls["n"] += 1
        return _Res(signals_seq[i])
    monkeypatch.setattr(sdk, "_capture", fake)
    return calls


def test_open_healed_escalates_then_stops_when_recovered(monkeypatch, tmp_path):
    from hydra import Hydra
    from hydra.detect import Signals
    h = _healable_hydra(tmp_path)
    # 429 rate-limit twice, then the data arrives (oracle GREEN) → healed, stop.
    calls = _script_capture(monkeypatch, [
        Signals(oracle_count=0, nav_status=429, retry_after="5", body_len=600),
        Signals(oracle_count=0, nav_status=429, retry_after="5", body_len=600),
        Signals(oracle_count=2, nav_status=200, body_len=9000)])
    heals = []
    monkeypatch.setattr(Hydra, "_heal", lambda self, lever: heals.append(lever))
    _cands, v = h.open_healed("http://x", max_heal=4)
    assert calls["n"] == 3                          # navigated 3x: block, block, clean
    assert heals == ["rotate_exit", "drop_session"]  # rate_limit lever, then escalate one rung
    assert v is None                                # recovered → no surviving block


def test_open_healed_does_not_heal_a_thin_but_fine_page(monkeypatch, tmp_path):
    from hydra import Hydra
    from hydra.detect import Signals
    h = _healable_hydra(tmp_path)
    # 200, tiny body, no API, no challenge → classify() says `unknown` (blocked) — but it's NOT a
    # nav-block, so a plain navigate must LEAVE IT ALONE (the example.com false-positive).
    calls = _script_capture(monkeypatch, [Signals(oracle_count=0, nav_status=200, body_len=800)])
    heals = []
    monkeypatch.setattr(Hydra, "_heal", lambda self, lever: heals.append(lever))
    _cands, v = h.open_healed("http://x", max_heal=4)
    assert calls["n"] == 1 and heals == [] and v is None   # navigated once, no heal, not flagged


def test_open_healed_returns_the_verdict_when_a_block_outlives_the_ladder(monkeypatch, tmp_path):
    from hydra import Hydra
    from hydra.detect import Signals
    h = _healable_hydra(tmp_path)
    # a 403 that never clears → after max_heal the standing verdict comes back (so MCP can tell the brain)
    calls = _script_capture(monkeypatch, [
        Signals(oracle_count=0, nav_status=403, body_len=500, first_request_block=True)])
    monkeypatch.setattr(Hydra, "_heal", lambda self, lever: None)
    _cands, v = h.open_healed("http://x", max_heal=3)
    assert calls["n"] == 3                          # exhausted the 3 attempts
    assert v is not None and v.block_class == "ip_block"


def test_humanize_is_off_and_not_a_user_knob():
    import inspect
    from hydra.sdk import Hydra as H
    params = inspect.signature(H.__init__).parameters
    assert "humanize" not in params           # rule 3: no user knob
    src = inspect.getsource(H.__enter__)
    assert "humanize=False" in src            # baked in


def test_auth_summary_flags_but_never_leaks_secrets():
    from hydra.sdk import _auth_of
    tags = _auth_of({"Authorization": "Bearer supersecret.jwt.token",
                     "Cookie": "_abck=SECRETVALUE; session=xyz", "X-Api-Key": "k-123"})
    assert set(tags) == {"bearer", "cookie", "api-key"}     # presence flagged
    assert not any("supersecret" in t or "SECRETVALUE" in t or "k-123" in t for t in tags)  # NO values


def test_context_capture_surface_exists():
    from hydra import Hydra
    for m in ("open", "act", "capture", "observe"):
        assert callable(getattr(Hydra, m, None))     # open()/act() = context-tagged capture


def test_seed_is_pinned_even_without_one():
    from hydra import Hydra
    assert isinstance(Hydra()._seed, int)             # #4: concrete seed → coherent keys+mouse


def test_escalation_ladder_is_ordered():
    from hydra.sdk import _LADDER
    # cost-ordered, cheapest→dearest; no "behave" rung (behavior is always on → patience is a
    # humanized wait, not a separate "act human" lever)
    assert _LADDER == ("patience", "rotate_exit", "drop_session", "relaunch")


def test_native_and_single_exit_drop_the_rotate_rung():
    from hydra import Hydra
    # nothing to rotate to → the rotate rung is a no-op; the ladder must not include it
    assert Hydra()._ladder == ("patience", "drop_session", "relaunch")              # native
    assert Hydra(proxy="1.2.3.4:8000:u:p")._ladder == ("patience", "drop_session", "relaunch")  # 1 exit


def test_patience_is_humanized_not_a_frozen_wait():
    import inspect
    from hydra.sdk import Hydra as H
    src = inspect.getsource(H._heal)
    assert "behave" not in src                       # the orphan rung is gone
    # patience heals via the behavioral engine (idle/drift), not a dead page wait
    assert 'lever == "patience"' in src and "self.human.idle" in src


def test_capture_composes_with_traversal_and_tags():
    import inspect
    from hydra import Hydra
    params = inspect.signature(Hydra.capture).parameters
    assert "navigate" in params and "label" in params   # #6 navigate=False · #3 label


def test_merge_feeds_context_dedups_by_body_and_summarizes_auth():
    from hydra import Hydra
    from hydra.discover import ApiCandidate
    h = Hydra(); h._seen = set(); h.context = []
    def cand(body, hdrs):
        return ApiCandidate(url="http://x/a", method="POST", status=200, size=9, shape="dict",
                            request_headers=hdrs, post_data=body, sample={})
    class R: candidates = [cand("q1", {"Cookie": "secret"})]
    h._merge(R(), "load")
    assert len(h.context) == 1 and h.context[0]["fired_on"] == "load"
    assert h.context[0]["auth"] == ["cookie"]          # #3: summary, not the secret value
    h._merge(R(), "load")                              # same (url, body) → deduped
    assert len(h.context) == 1
    R.candidates = [cand("q2", {})]                    # same URL, different GraphQL body → kept
    h._merge(R(), "act")
    assert len(h.context) == 2


def test_replay_forwards_auth_but_not_browser_headers():
    from hydra.sdk import _replay_headers
    fwd = _replay_headers({"Authorization": "Bearer tok", "Content-Type": "application/json",
                           "X-Api-Key": "k1", "Cookie": "_abck=x", "Host": "site.com",
                           "Origin": "https://site.com", "sec-fetch-mode": "cors",
                           "User-Agent": "Mozilla"})
    assert set(fwd) == {"Authorization", "Content-Type", "X-Api-Key"}   # auth + content-type
    # cookies (credentials:'include') + browser-managed headers are NOT forwarded
    assert not any(k.lower() in ("cookie", "host", "origin", "sec-fetch-mode", "user-agent") for k in fwd)


# ── perception core: the page map — ranking/dedup/filters (browser-free, synthetic records) ─
# NO keywords anywhere: observe() just maps the DOM structurally; the agent decides what to click.
def _rec(id, label="", role="button", overlay=False, inVp=True, occ=False, box=(0, 0, 40, 20)):
    x, y, w, h = box
    return {"id": id, "label": label, "role": role, "overlay": overlay,
            "inVp": inVp, "occ": occ, "box": list(box), "pageY": y}


def test_rank_drops_occluded_elements():
    from hydra.sdk import _rank
    out = _rank([_rec(1, "A"), _rec(2, "B", occ=True)], 1000, 800)
    assert [e["id"] for e in out] == [1]               # covered element is not clickable → dropped


def test_rank_in_viewport_filter():
    from hydra.sdk import _rank
    out = _rank([_rec(1, "A", inVp=True), _rec(2, "B", inVp=False)], 1000, 800, in_viewport=True)
    assert [e["id"] for e in out] == [1]


def test_rank_dedups_twins_and_keeps_the_onscreen_one():
    from hydra.sdk import _rank
    recs = [_rec(1, "Menu", inVp=False, box=(0, 0, 50, 20)),
            _rec(2, "Menu", inVp=True, box=(0, 0, 50, 20))]   # identical label/role/size = twin
    out = _rank(recs, 1000, 800)
    assert len(out) == 1 and out[0]["id"] == 2         # collapsed; kept the on-screen twin


def test_rank_orders_onscreen_before_offscreen():
    from hydra.sdk import _rank
    recs = [_rec(1, "content", role="link", inVp=False, box=(0, 3000, 100, 20)),
            _rec(2, "near-center", role="link", inVp=True, box=(470, 390, 100, 20)),
            _rec(3, "top nav", role="link", inVp=True, box=(0, 0, 40, 20))]
    ids = [e["id"] for e in _rank(recs, 1000, 800)]
    assert ids.index(2) < ids.index(1)                 # on-screen outranks off-screen
    assert ids.index(3) < ids.index(1)


def test_rank_filters_role_contains_and_overlay():
    from hydra.sdk import _rank
    recs = [_rec(1, "Calcio", role="link"), _rec(2, "Tennis", role="link"),
            _rec(3, "go", role="button"), _rec(4, "popup btn", role="button", overlay=True)]
    assert [e["id"] for e in _rank(recs, 1000, 800, contains="cal")] == [1]
    assert {e["id"] for e in _rank(recs, 1000, 800, role="button")} == {3, 4}
    assert [e["id"] for e in _rank(recs, 1000, 800, overlay=True)] == [4]   # keyword-free overlay filter
