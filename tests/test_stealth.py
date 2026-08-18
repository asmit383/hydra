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


def test_detector_drives_decision_when_signals_present(monkeypatch):
    # when a capture carries rich signals, detect.py DRIVES the decision (truth table),
    # not the old vendor table. A 429 → rate_limit → rotate, and diagnose is never called.
    from hydra.detect import Signals
    sig = Signals(oracle_count=0, nav_status=429, retry_after="5", server="cloudflare")
    monkeypatch.setattr(stealth, "capture",
                        lambda url, **kw: CaptureResult([], 429, "", "", [], signals=sig))
    monkeypatch.setattr(stealth, "diagnose",
                        lambda r: (_ for _ in ()).throw(AssertionError("diagnose used despite signals")))
    moves = []
    stealth.resilient_capture("http://x", proxies_file=None, max_attempts=2,
                              on_attempt=lambda a: moves.append(a.move))
    assert any("rotate" in m.lower() for m in moves)


def test_terminal_class_stops_without_spinning(monkeypatch):
    # an auth_required / hard_verify block is NOT self-healable — the loop must stop,
    # not burn all its attempts.
    from hydra.detect import Signals
    sig = Signals(oracle_count=0, nav_status=403, interactive_captcha=True)
    n_calls = []
    monkeypatch.setattr(stealth, "capture",
                        lambda url, **kw: (n_calls.append(1), CaptureResult([], 403, "", "", [], signals=sig))[1])
    r = stealth.resilient_capture("http://x", proxies_file=None, max_attempts=5)
    assert not r.recovered
    assert len(n_calls) == 1          # stopped after the first capture — didn't spin 5x
