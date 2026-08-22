from hydra.discover import (_is_noise, _looks_like_data, _post_data, _shape, _challenge_title)


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
