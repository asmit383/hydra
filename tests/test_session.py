from hydra.session import parse_proxy, load_proxies, pick_proxy, _geoip_for, _geo_align


def test_parse_proxy_forms():
    assert parse_proxy("1.2.3.4:8000:user:pass") == {
        "server": "http://1.2.3.4:8000", "username": "user", "password": "pass"}
    assert parse_proxy("1.2.3.4:8000") == {"server": "http://1.2.3.4:8000"}
    assert parse_proxy("http://1.2.3.4:8000")["server"] == "http://1.2.3.4:8000"
    assert parse_proxy("") is None
    assert parse_proxy("garbage") is None


def test_load_proxies_file(tmp_path):
    p = tmp_path / "px.txt"
    p.write_text("# comment\n1.1.1.1:80:u:p\n\n2.2.2.2:81\n")
    out = load_proxies(str(p))
    assert len(out) == 2
    assert out[0]["username"] == "u"


def test_load_proxies_missing_is_empty(tmp_path):
    assert load_proxies(str(tmp_path / "nope.txt")) == []


def test_pick_proxy_native_is_none():
    assert pick_proxy("native") is None


def test_geoip_native_is_true():
    assert _geoip_for(None) is True
    assert _geoip_for({"server": "http://5.6.7.8:9000"}) == "5.6.7.8"


def test_geo_align_ip_vs_gateway_hostname():
    # a static exit IP → align straight to it (no lookup)
    assert _geo_align("45.83.57.91") == "45.83.57.91"
    # a rotating-gateway HOSTNAME is NOT the exit → True (Camoufox detects the exit through the proxy),
    # never the hostname (which would throw 'Invalid IP address')
    assert _geo_align("fresi.hellworld.io") is True
    assert _geo_align(None) is True
    # and a gateway proxy dict resolves the same way end-to-end
    assert _geoip_for({"server": "http://gw.provider.io:10000"}) is True
