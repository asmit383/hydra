"""HealSession — a persistent Camoufox session with HOT levers (v0.4).

The production substrate for session-preserving self-heal (and the SDK). ONE browser
stays alive across heal attempts; the levers mutate the LIVE session instead of
relaunching, so the truth table executes as designed:

  patience      wait, change nothing                (transient challenge)
  rotate        swap the exit via the relay         (rate-limit / IP) — keeps fp + session
  drop_session  clear cookies, keep fingerprint     (session / quota) — a fresh visit
  relaunch      new browser = new fp + new session  (fingerprint) — the nuclear last resort

Only `relaunch` pays for a fresh fingerprint (and loses the warm `_abck`/clearance).
The other three are HOT — the browser process (fingerprint + session + clearance) is
untouched. That's the whole point of the truth table: cheap targeted moves, and the
expensive relaunch only when the *fingerprint itself* is what leaked.
"""
from __future__ import annotations

from hydra.relay import Relay
from hydra.session import launch


def _exit_parts(ex: dict) -> tuple[str, str, str, str]:
    """(host, port, user, pass) from a Camoufox proxy dict {'server':'http://ip:port',…}."""
    hostport = ex["server"].split("://", 1)[-1]
    host, _, port = hostport.rpartition(":")
    return host, port, ex.get("username", ""), ex.get("password", "")


class HealSession:
    """Hold one Camoufox browser alive and drive the levers on it. If `exits` are given,
    the browser routes through a local relay whose upstream is swappable (rotate without
    relaunch); native otherwise."""

    def __init__(self, exits: list[dict] | None = None, *, headless: bool = True,
                 storage_state: str | None = None, humanize=True):
        self.exits = exits or []
        self._i = -1                        # -1 = native ISP IP; 0+ = proxy pool index
        self.headless = headless
        self.storage_state = storage_state
        self.humanize = humanize
        self.relay: Relay | None = None
        self._cm = None
        self.page = None

    # ---- lifecycle -----------------------------------------------------------
    def open(self) -> "HealSession":
        self._launch(proxy=None, geo=None)  # NATIVE first — the patient default (§thesis)
        return self

    def _launch(self, proxy, geo) -> None:
        self._cm = launch(proxy=proxy, headless=self.headless,
                          storage_state=self.storage_state, humanize=self.humanize, geoip=geo)
        self.page = self._cm.__enter__()

    def close(self) -> None:
        if self._cm:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:
                pass
            self._cm = None
        if self.relay:
            self.relay.stop()
            self.relay = None
        self.page = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()

    # ---- the levers ----------------------------------------------------------
    def label(self) -> str:
        return "native ISP IP" if self._i < 0 else f"exit#{self._i + 1}/{len(self.exits)}"

    def patience(self, ms: int = 4000) -> None:
        """transient challenge → wait it out, change nothing (returning user)."""
        try:
            self.page.wait_for_timeout(ms)
        except Exception:
            pass

    def rotate(self) -> str | None:
        """rate-limit / IP → moved network. Returns:
          "cold" — native→proxy (a genuine ISP→proxy change; re-launches to reset geoip,
                   so this one does NOT keep the session),
          "hot"  — proxy→proxy swap via the relay, keeping fp + session,
          None   — no pool to rotate within (caller falls back to relaunch)."""
        if not self.exits:
            return None
        if self._i < 0:                     # native → first proxy (cold: proxy+geoip are launch params)
            self._i = 0
            host, port, user, pw = _exit_parts(self.exits[0])
            self.relay = Relay()
            self.relay.set_upstream(host, port, user, pw)
            self.relay.start()
            self._reopen({"server": self.relay.server_url()}, host)
            return "cold"
        self._i = (self._i + 1) % len(self.exits)   # proxy → next proxy — HOT, keeps fp+session
        host, port, user, pw = _exit_parts(self.exits[self._i])
        self.relay.set_upstream(host, port, user, pw)
        return "hot"

    def _reopen(self, proxy, geo) -> None:
        if self._cm:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:
                pass
        self._launch(proxy, geo)

    def drop_session(self) -> None:
        """session / quota → clear cookies, keep the fingerprint (a fresh incognito
        visit on the same device)."""
        try:
            self.page.context.clear_cookies()
        except Exception:
            pass

    def relaunch(self) -> None:
        """fingerprint → the NUCLEAR lever: tear down the browser and re-open = new
        fingerprint + new session, on the CURRENT exit. Loses the warm clearance, so
        it's the last resort — only for a diagnosed fingerprint block."""
        if self._i < 0:                     # native
            self._reopen(None, None)
        else:                               # current proxy (relay already up)
            host = _exit_parts(self.exits[self._i])[0]
            self._reopen({"server": self.relay.server_url()}, host)
