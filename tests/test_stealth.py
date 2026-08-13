from hydra import stealth
from hydra.discover import CaptureResult
from hydra.diagnose import Verdict


def _blocked(kind, layer):
    return lambda r: Verdict(True, kind, layer, "sig", "act")


def test_behavioral_block_warms_up_same_exit(monkeypatch):
    # a behavioral block should escalate human presence (warmup) on the SAME exit,
    # not rotate immediately — the distinct behavioral remediation.
    calls = []
    monkeypatch.setattr(stealth, "capture",
                        lambda url, **kw: (calls.append(kw), CaptureResult([], 200, "", "", []))[1])
    monkeypatch.setattr(stealth, "diagnose", _blocked("perimeterx", "behavioral"))

    moves = []
    stealth.resilient_capture("http://x", max_attempts=2, on_attempt=lambda a: moves.append(a.move))

    assert any("warm up" in m for m in moves)          # behavioral remediation kicked in
    assert calls[1].get("warmup") is True              # 2nd attempt actually warms up
    assert calls[1].get("humanize") == 2.0             # …with slower humanize


def test_ip_block_rotates_not_warmup(monkeypatch):
    # an IP-layer block (DataDome/403) should rotate, not warm up
    calls = []
    monkeypatch.setattr(stealth, "capture",
                        lambda url, **kw: (calls.append(kw), CaptureResult([], 403, "", "", []))[1])
    monkeypatch.setattr(stealth, "diagnose", _blocked("datadome", "ip"))

    moves = []
    stealth.resilient_capture("http://x", proxies_file=None, max_attempts=2,
                              on_attempt=lambda a: moves.append(a.move))
    assert any("rotate" in m for m in moves)
    assert not any("warm up" in m for m in moves)
