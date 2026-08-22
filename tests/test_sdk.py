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


# ── perception core v2: ranking + blocker detection (browser-free, synthetic records) ─
def _rec(id, label="", role="button", verb=None, overlay="", inVp=True, occ=False, box=(0, 0, 40, 20)):
    return {"id": id, "label": label, "role": role, "verb": verb, "overlayText": overlay,
            "oauth": False, "inVp": inVp, "occ": occ, "box": list(box)}


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


def test_rank_floats_blockers_then_viewport_over_offscreen():
    from hydra.sdk import _rank
    recs = [_rec(1, "content", role="link", inVp=False, box=(0, 3000, 100, 20)),
            _rec(2, "Chiudi", role="dismiss", verb="close", overlay="popup", box=(470, 390, 60, 20)),
            _rec(3, "nav", role="link", inVp=True, box=(0, 0, 40, 20))]
    ids = [e["id"] for e in _rank(recs, 1000, 800)]
    assert ids[0] == 2                                 # a blocker outranks everything
    assert ids.index(3) < ids.index(1)                 # on-screen outranks off-screen


def test_rank_role_and_contains_filters():
    from hydra.sdk import _rank
    recs = [_rec(1, "Calcio", role="link"), _rec(2, "Tennis", role="link"), _rec(3, "go", role="button")]
    assert [e["id"] for e in _rank(recs, 1000, 800, contains="cal")] == [1]
    assert [e["id"] for e in _rank(recs, 1000, 800, role="button")] == [3]


def test_pick_blockers_accept_first_one_per_overlay():
    from hydra.sdk import _pick_blockers
    recs = [_rec(1, "Accetta tutti", role="dismiss", verb="accept", overlay="cookie privacy"),
            _rec(2, "Rifiuta", role="dismiss", verb="reject", overlay="cookie privacy"),
            _rec(3, "Chiudi", role="dismiss", verb="close", overlay="Ehi Sisal popup")]
    bl = _pick_blockers(recs)
    assert [b["id"] for b in bl] == [1, 3]             # accept wins its overlay; one per overlay; accept-first


def test_pick_blockers_ignores_non_blockers_and_occluded():
    from hydra.sdk import _pick_blockers
    recs = [_rec(1, "login", verb=None),
            _rec(2, "Chiudi", verb="close", overlay="x", occ=True)]
    assert _pick_blockers(recs) == []
