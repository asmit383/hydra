"""Pilot (LLM decision loop) — tested WITHOUT a browser or API key, via a scripted decider
and a fake Hydra. Proves the plumbing: the loop dismisses/clicks/scrolls the ids the decider
picks, captures via act(), and stops on done. The real Claude decider just replaces the script."""
import types

from hydra.pilot import format_state, parse_action, pilot


def test_parse_action_tolerates_fences_and_prose():
    assert parse_action('```json\n{"action":"click","id":34,"why":"prematch"}\n```') == \
        {"action": "click", "id": 34, "why": "prematch"}
    assert parse_action('Sure! {"action":"done","why":"odds visible"} ')["action"] == "done"
    assert parse_action("no json here")["action"] == "stop"          # graceful
    assert parse_action('{"action":"teleport","id":1}')["action"] == "stop"  # unknown → stop


def test_format_state_shows_goal_overlays_and_elements():
    snap = {"overlays": [{"id": 9, "label": "Accetta tutti"}],
            "scroll": {"y": 0, "height": 4000, "hasMore": True},
            "elements": [{"id": 34, "role": "link", "label": "PREMATCH"}]}
    s = format_state("reach the odds", snap, 1, 14)
    assert "GOAL: reach the odds" in s and "[9] Accetta tutti" in s
    assert "[34] link 'PREMATCH'" in s and "more below = yes" in s


class _FakeH:
    """Records what pilot does; snapshot() is canned."""
    def __init__(self):
        self.calls, self.context = [], []
        self.session = types.SimpleNamespace(
            page=types.SimpleNamespace(wait_for_timeout=lambda ms: None))

    def snapshot(self, *, limit=40):
        return {"overlays": [{"id": 9, "label": "Accetta tutti"}],
                "scroll": {"y": 0, "height": 4000, "hasMore": True},
                "elements": [{"id": 34, "role": "link", "label": "PREMATCH"}]}

    def act(self, tid, label="", *, wait_ms=0):
        self.calls.append(("act", tid))
        self.context.append({"fired_on": label, "url": f"/api/x?after={tid}"})

    def scroll(self, *, steps=0):
        self.calls.append(("scroll", steps))


def _scripted(actions):
    it = iter(actions)
    return lambda state_text: next(it)


def test_pilot_executes_the_deciders_actions_then_stops_on_done():
    h = _FakeH()
    decide = _scripted([
        {"action": "click", "id": 9, "why": "dismiss cookie bar"},
        {"action": "scroll", "why": "need to see more"},
        {"action": "click", "id": 34, "why": "into prematch"},
        {"action": "done", "why": "odds on screen"},
    ])
    ctx = pilot(h, "reach the football odds", decide, max_steps=8, log=lambda *_: None)
    assert h.calls == [("act", 9), ("scroll", 3), ("act", 34)]     # dismissed, scrolled, clicked
    assert [c["fired_on"] for c in ctx] == ["llm:dismiss cookie bar", "llm:into prematch"]


def test_openai_decider_builds_request_and_parses(monkeypatch):
    import httpx
    from hydra.pilot import openai_decider
    seen = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": '{"action":"click","id":7,"why":"go"}'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    decide = openai_decider(model="gpt-4o-mini", base_url="https://openrouter.ai/api/v1", api_key="k")
    action = decide("GOAL: x")
    assert action == {"action": "click", "id": 7, "why": "go"}          # parsed the model reply
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"  # OpenAI-compatible path
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["body"]["model"] == "gpt-4o-mini" and seen["body"]["messages"][0]["role"] == "system"


def test_pilot_stops_on_unparseable_and_respects_max_steps():
    h = _FakeH()
    ctx = pilot(h, "x", lambda s: {"action": "stop", "why": "give up"}, max_steps=8, log=lambda *_: None)
    assert h.calls == [] and ctx == []                              # stopped immediately, no actions

    h2 = _FakeH()
    pilot(h2, "x", lambda s: {"action": "click", "id": 1, "why": "loop"}, max_steps=3, log=lambda *_: None)
    assert len(h2.calls) == 3                                       # never exceeds max_steps
