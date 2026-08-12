from hydra.diagnose import diagnose
from hydra.discover import CaptureResult


def _res(signals):
    return CaptureResult([], 200, "", "", signals)


def test_datadome_is_ip_layer():
    v = diagnose(_res(["host:captcha-delivery.com", "status:403"]))
    assert v.blocked and v.kind == "datadome" and v.layer == "ip"


def test_cloudflare_is_fingerprint_layer():
    v = diagnose(_res(["title:just a moment"]))
    assert v.blocked and v.kind == "cloudflare" and v.layer == "fingerprint"


def test_ratelimit_and_forbidden():
    assert diagnose(_res(["status:429"])).kind == "ratelimit"
    assert diagnose(_res(["status:403"])).kind == "forbidden"


def test_clean_load_not_blocked():
    v = diagnose(_res([]))
    assert not v.blocked and v.kind == "none"
