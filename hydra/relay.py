"""Swappable local proxy relay — rotate the exit IP WITHOUT relaunching the browser.

The browser's proxy is set ONCE to this relay (localhost). The relay forwards to an
upstream residential proxy with preemptive Basic auth, and its upstream is
**swappable at runtime**: call `set_upstream()` and the *next* connection routes
through the new exit — the browser (fingerprint + session + clearance cookies) never
restarts.

This is the primitive behind the truth table's *"rotate exit (relay), keep
fp+session"*: IP becomes a **hot** lever you turn on a live session, instead of the
nuclear relaunch (which burns the warm session / `_abck` you fought to earn).

Sync-friendly: the asyncio forwarding server runs in a background thread; `start()`
/ `set_upstream()` / `stop()` are called from the (sync) Hydra code. It also solves
the same 407-vs-502 preemptive-auth quirk the simone relay was built for.
"""
from __future__ import annotations

import asyncio
import base64
import threading


class Relay:
    def __init__(self) -> None:
        self._up = None            # (host, port, auth_b64) — reassigned atomically → thread-safe
        self._loop = None
        self._server = None
        self._thread = None
        self._ready = threading.Event()
        self._conns: set = set()   # active client writers — closed on a swap
        self.port: int | None = None

    # ---- the API the heal loop uses ------------------------------------------
    def set_upstream(self, host: str, port: int, username: str = "", password: str = "") -> None:
        """Point the relay at a new residential exit and DROP the live tunnels, so the
        browser re-connects through the new exit on its next request. The browser
        process (fingerprint + session + cookies) is untouched — only the sockets
        under it are recycled. Atomic tuple reassignment = thread-safe."""
        auth = base64.b64encode(f"{username}:{password}".encode()).decode() if username else ""
        self._up = (host, int(port), auth)
        if self._loop:                       # force the browser off the old exit's tunnels
            self._loop.call_soon_threadsafe(self._drop_conns)

    def _drop_conns(self) -> None:
        for w in list(self._conns):
            try:
                w.close()
            except Exception:
                pass
        self._conns.clear()

    def server_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> int:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("relay failed to start")
        return self.port

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ---- the asyncio forwarding server (runs in its own thread) ---------------
    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())
        self._loop.run_forever()

    async def _serve(self) -> None:
        self._server = await asyncio.start_server(self._spawn, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        self._ready.set()

    def _spawn(self, creader, cwriter) -> None:
        asyncio.ensure_future(self._handle(creader, cwriter))

    async def _handle(self, creader, cwriter) -> None:
        up = self._up                       # snapshot the CURRENT upstream for this connection
        uwriter = None
        self._conns.add(cwriter)            # track so a swap can drop this tunnel
        try:
            if up is None:
                return
            uhost, uport, auth_b64 = up
            header = await asyncio.wait_for(creader.readuntil(b"\r\n\r\n"), timeout=30)
            line, _, rest = header.partition(b"\r\n")
            authhdr = f"Proxy-Authorization: Basic {auth_b64}\r\n".encode() if auth_b64 else b""
            ureader, uwriter = await asyncio.open_connection(uhost, uport)
            if line.upper().startswith(b"CONNECT"):
                # HTTPS tunnel: send our own CONNECT with preemptive auth, relay the
                # upstream's reply, then pipe raw TLS bytes both ways.
                uwriter.write(line + b"\r\n" + authhdr + b"Proxy-Connection: Keep-Alive\r\n\r\n")
                await uwriter.drain()
                resp = await ureader.readuntil(b"\r\n\r\n")
                cwriter.write(resp)
                await cwriter.drain()
            else:
                uwriter.write(line + b"\r\n" + authhdr + rest)
                await uwriter.drain()
            await asyncio.gather(self._pipe(creader, uwriter), self._pipe(ureader, cwriter))
        except Exception:
            pass
        finally:
            self._conns.discard(cwriter)
            for w in (cwriter, uwriter):
                try:
                    if w:
                        w.close()
                except Exception:
                    pass

    @staticmethod
    async def _pipe(reader, writer) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
