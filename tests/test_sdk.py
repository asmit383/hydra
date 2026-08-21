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
