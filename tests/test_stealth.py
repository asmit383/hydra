from hydra import stealth
from hydra.discover import ApiCandidate, CaptureResult
from hydra.detect import Signals


class FakeSession:
    """Stand-in for HealSession — records lever calls, launches no real browser."""
    def __init__(self, *a, **k):
        self.page = object()
        self.levers = []

    def open(self):
        return self

    def close(self):
        pass

    def label(self):
        return "fake-exit"

    def patience(self, ms=0):
        self.levers.append("patience")

    def rotate(self):
        self.levers.append("rotate")
        return False          # no pool → the loop falls back to relaunch

    def drop_session(self):
        self.levers.append("drop_session")

    def relaunch(self):
        self.levers.append("relaunch")


def _wire(monkeypatch, capture_fn, fake=None, diagnose=None):
    fake = fake or FakeSession()
    monkeypatch.setattr(stealth, "HealSession", lambda *a, **k: fake)
    monkeypatch.setattr(stealth, "capture", capture_fn)
    if diagnose is not None:
        monkeypatch.setattr(stealth, "diagnose", diagnose)
    return fake


def test_detector_drives_rate_limit_to_rotate(monkeypatch):
    # a 429 with signals → detect classifies rate_limit → rotate lever, and diagnose is
    # NEVER consulted (the vendor-free detector drives).
    sig = Signals(oracle_count=0, nav_status=429, retry_after="5", server="cloudflare")
    res = CaptureResult([], 429, "", "", [], signals=sig)
    fake = _wire(monkeypatch, lambda url, **k: res,
                 diagnose=lambda r: (_ for _ in ()).throw(AssertionError("diagnose used")))
    moves = []
    stealth.resilient_capture("http://x", base_backoff=0, max_attempts=2,
                              on_attempt=lambda a: moves.append(a.move))
    assert "rotate" in fake.levers
    assert any("rotate" in m.lower() for m in moves)


def test_terminal_class_stops_without_spinning(monkeypatch):
    # an interactive captcha is NOT self-healable — stop after the first capture.
    sig = Signals(oracle_count=0, nav_status=403, interactive_captcha=True)
    n = []
    _wire(monkeypatch, lambda url, **k: (n.append(1),
          CaptureResult([], 403, "", "", [], signals=sig))[1])
    r = stealth.resilient_capture("http://x", base_backoff=0, max_attempts=5)
    assert not r.recovered
    assert len(n) == 1


def test_no_data_channel_is_not_a_block(monkeypatch):
    # 200 + real page + no API = SSR, not a block — stop, don't try to heal into an API.
    sig = Signals(oracle_count=0, nav_status=200, body_len=50000, content_type="text/html")
    n = []
    fake = _wire(monkeypatch, lambda url, **k: (n.append(1),
                 CaptureResult([], 200, "", "", [], signals=sig))[1])
    stealth.resilient_capture("http://x", base_backoff=0, max_attempts=5)
    assert len(n) == 1
    assert not fake.levers          # no lever fired — it's not a block


def test_clean_capture_recovers(monkeypatch):
    # oracle green + a candidate present → recovered on the first hit, no levers.
    cand = ApiCandidate("http://api", "GET", 200, 99, "dict", {}, None, {})
    sig = Signals(oracle_count=1, nav_status=200)
    fake = _wire(monkeypatch, lambda url, **k: CaptureResult([cand], 200, "", "", [], signals=sig))
    r = stealth.resilient_capture("http://x", base_backoff=0, max_attempts=3)
    assert r.recovered
    assert not fake.levers
