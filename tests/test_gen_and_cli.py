import json

from hydra.discover import ApiCandidate
from hydra.gen import generate_client
import hydra.cli as cli


def _cand(url, method="GET", headers=None, post=None):
    return ApiCandidate(url=url, method=method, status=200, size=10, shape="list[1]",
                        request_headers=headers or {}, post_data=post, sample=[{"id": 1}])


def test_generated_client_is_valid_python_with_auth():
    c = _cand("https://x.com/api/items?page=1",
              headers={"cookie": "a=b", "authorization": "Bearer z", "x-noise": "no"})
    code = generate_client("https://x.com", [c])
    compile(code, "<gen>", "exec")            # must be valid Python
    assert "def items(" in code               # function named from endpoint
    assert "'cookie': 'a=b'" in code          # auth carried in
    assert "Bearer z" in code
    assert "x-noise" not in code              # non-auth header dropped


def test_generated_client_handles_post():
    c = _cand("https://x.com/gen", method="POST", post='{"page":0}')
    code = generate_client("https://x.com", [c])
    compile(code, "<gen>", "exec")
    assert "client.request('POST'" in code
    assert '{"page":0}' in code


def test_preview_caps_at_256():
    big = {"blob": "M" * 5000}
    out = cli._preview(big)
    assert len(out) <= 257 and out.endswith("…")


def test_color_json_plain_when_no_color(monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    s = json.dumps({"a": 1})
    assert "\033[" not in cli._color_json(s)   # no escape codes when piped


def test_color_json_highlights_when_color(monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", True)
    assert "\033[" in cli._color_json('{"a": 1}')


def test_box_borders_align(monkeypatch):
    monkeypatch.setattr(cli, "_COLOR", False)
    box = cli._box("title", ["a short row", "a much longer row here"])
    lines = box.splitlines()
    assert len(set(len(x) for x in lines)) == 1  # all borders same visible width


def test_endpoint_name():
    assert cli._endpoint_name("https://x.com/api/getOdds?id=1") == "getodds" \
        or cli._endpoint_name("https://x.com/api/getOdds?id=1") == "getOdds"
