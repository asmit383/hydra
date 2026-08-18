from hydra.relay import Relay


def test_relay_starts_swaps_stops():
    # mechanical: starts on a real port, accepts upstream swaps, stops cleanly.
    # (no network — just the lifecycle the heal loop drives.)
    r = Relay()
    r.set_upstream("1.2.3.4", 8080, "user", "pass")
    port = r.start()
    try:
        assert isinstance(port, int) and port > 0
        assert r.server_url() == f"http://127.0.0.1:{port}"
        r.set_upstream("5.6.7.8", 9090, "u2", "p2")     # a swap must not raise
    finally:
        r.stop()
