from hydra.discover import (_has_captcha, _is_captcha_wall, _is_noise, _looks_like_data,
                            _post_data, _shape, _challenge_title)
from hydra.detect import Signals, classify


class _BinReq:
    """A request whose post_data raises (binary/gzip body) — like an antibot telemetry beacon."""
    @property
    def post_data(self):
        raise UnicodeDecodeError("utf-8", b"\x1f\x8b", 0, 1, "invalid start byte")
    post_data_buffer = b"\x1f\x8b\x08\x00binary-beacon"


def test_post_data_survives_binary_body():
    # a binary/gzipped POST must NOT crash the listener (it used to kill discovery for the page)
    assert _post_data(_BinReq()) is not None          # falls back to the buffer, stable dedup key


def test_noise_filters_known_junk():
    assert _is_noise("https://www.google-analytics.com/collect")
    assert _is_noise("https://js.stripe.com/v3/")
    assert _is_noise("https://ekr.zdassets.com/x")           # zendesk
    assert _is_noise("https://widgets.sir.sportradar.com/x")  # stats widget
    assert not _is_noise("https://www.staryes.it/XSportDatastore/getEventoPerMacrogruppo")


def test_looks_like_data():
    assert _looks_like_data([{"a": 1}])
    assert _looks_like_data({"results": [1, 2, 3]})          # wraps a non-empty list
    assert _looks_like_data({"a": 1, "b": 2, "c": 3})        # >=3 keys
    assert not _looks_like_data([])
    assert not _looks_like_data({"ok": True})                # 1 scalar key


def test_shape_surfaces_data_bearing_key_over_status_wrapper():
    # the envelope-API bug: {Success, Value} must preview Value, not Success
    env = {"Id": 0, "Success": True, "Error": "", "ErrorCode": 0, "Guid": "",
           "Value": {"events": [{"id": 1, "odds": 1.85}]}}
    shape, sample = _shape(env)
    assert shape == "dict(6 keys)"
    assert "Value" in sample                                 # data key surfaced
    assert list(sample)[0] == "Value"                        # …and shown first


def test_shape_list_and_scalar():
    assert _shape([1, 2, 3])[0] == "list[3]"
    assert _shape("hi") == ("str", "hi")


def test_challenge_title():
    assert _challenge_title("Just a moment...") == "just a moment"
    assert _challenge_title("Machine Learning Engineer Jobs") is None


def test_has_captcha_detects_widgets():
    assert _has_captcha('<div class="h-captcha" data-sitekey="x"></div>')            # hCaptcha
    assert _has_captcha('<div class="g-recaptcha"></div>')                            # reCAPTCHA
    assert _has_captcha('<iframe src="https://challenges.cloudflare.com/turnstile/"></iframe>')
    assert _has_captcha('<script src="https://hcaptcha.com/1/api.js"></script>')
    assert not _has_captcha('<html><body>a normal page, no captcha here</body></html>')
    assert not _has_captcha("")


def test_captcha_wall_vs_incidental_widget():
    wall = '<div class="h-captcha"></div>'
    assert _is_captcha_wall(wall, "just a moment", 403)      # challenge title → wall
    assert _is_captcha_wall(wall, None, 403)                 # block status → wall
    assert _is_captcha_wall(wall, None, 200)                 # thin 200 page → wall
    # a big normal 200 content page that merely embeds a reCAPTCHA form → NOT a wall
    big = '<div class="g-recaptcha"></div>' + "x" * 20000
    assert not _is_captcha_wall(big, None, 200)
    assert not _is_captcha_wall("x" * 100, None, 403)        # no widget → never a wall


def test_captcha_routes_to_hard_verify_not_patience():
    # the regression the review flagged: a captcha wall MUST be hard_verify (stop for a
    # human/solver) — even when it also looks challenge-shaped — never transient/patience.
    v = classify(Signals(oracle_count=0, nav_status=403, challenge_shape=True,
                         interactive_captcha=True))
    assert v.block_class == "hard_verify" and v.self_heal is False

    # and the control: WITHOUT the captcha flag, a challenge-shape is (correctly) transient —
    # which is exactly why the flag has to be set in the live path, not just the demo.
    v2 = classify(Signals(oracle_count=0, nav_status=503, challenge_shape=True))
    assert v2.block_class == "transient" and v2.self_heal is True


def test_first_request_block_flag_reaches_verdict():
    # pre-emptive 403 on request #1 → still ip_block, but the reason must now actually fire
    v = classify(Signals(oracle_count=0, nav_status=403, first_request_block=True))
    assert v.block_class == "ip_block"
    assert any("request #1" in reason for reason in v.reasons)
