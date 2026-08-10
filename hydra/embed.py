"""SSR / embedded-data extraction. (v0.1.1)

Server-rendered sites (Next.js, Nuxt, anything shipping Apollo/Redux state) don't
call a data API — they bake the data straight into the HTML. There's no XHR for
`discover()` to intercept, so it comes up empty. This module reads the *document*
instead: pull the inlined JSON blob (`__NEXT_DATA__`, `__APOLLO_STATE__`,
`ld+json`, or any `application/json` script) and point at the biggest record set
inside it — the analog of "biggest API candidate", for the HTML case.

This is the boring-but-necessary half: Hydra's edge is API discovery, but a lot
of the web is SSR, and "nothing found" is a worse answer than "here's the blob."
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_NUXT_RE = re.compile(r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_APOLLO_RE = re.compile(r'window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;', re.DOTALL)
_LDJSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL | re.I)
_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.DOTALL | re.I)


@dataclass
class EmbeddedBlob:
    kind: str            # "__NEXT_DATA__" | "__APOLLO_STATE__" | "ld+json" | "inline-json"
    size: int            # bytes of the blob's JSON
    records_path: str    # best-effort path to the biggest record set inside it
    records_count: int   # how many records live there
    sample: object       # one record, to confirm it's the data


def _biggest_records(obj, path: str = "$", depth: int = 0) -> tuple[str, int, object]:
    """Walk nested JSON, return (path, count, sample) of the largest collection of
    record-like dicts. Handles both plain arrays and Apollo-style normalized caches
    (a dict whose *values* are the records). Bounded so huge blobs stay cheap."""
    best = (path, 0, None)
    if depth > 6:
        return best

    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if len(dicts) > best[1]:
            best = (path, len(dicts), dicts[0] if dicts else None)
        for i, x in enumerate(obj[:50]):
            cand = _biggest_records(x, f"{path}[{i}]", depth + 1)
            if cand[1] > best[1]:
                best = cand
    elif isinstance(obj, dict):
        # normalized cache: {"Type:id": {...record...}, ...} — count the record values
        vals = [v for v in obj.values() if isinstance(v, dict) and len(v) >= 2]
        if len(vals) >= 3 and len(vals) > best[1]:
            best = (path, len(vals), vals[0])
        for k, v in list(obj.items())[:100]:
            cand = _biggest_records(v, f"{path}.{k}", depth + 1)
            if cand[1] > best[1]:
                best = cand
    return best


def _blob(kind: str, raw: str) -> EmbeddedBlob | None:
    raw = raw.strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    path, count, sample = _biggest_records(data)
    return EmbeddedBlob(kind=kind, size=len(raw), records_path=path,
                        records_count=count, sample=sample)


def extract_embedded(html: str) -> list[EmbeddedBlob]:
    """Find inlined data blobs in an HTML document, biggest record set first."""
    blobs: list[EmbeddedBlob] = []

    for kind, rx in (("__NEXT_DATA__", _NEXT_RE), ("__NUXT_DATA__", _NUXT_RE),
                     ("__APOLLO_STATE__", _APOLLO_RE)):
        m = rx.search(html)
        if m:
            b = _blob(kind, m.group(1))
            if b:
                blobs.append(b)

    for m in _LDJSON_RE.finditer(html):
        b = _blob("ld+json", m.group(1))
        if b and b.size > 40:        # skip trivial {"@context": ...} stubs
            blobs.append(b)

    # generic application/json scripts (Remix/SvelteKit/etc.) — only if nothing above
    if not blobs:
        for m in _JSON_SCRIPT_RE.finditer(html):
            b = _blob("inline-json", m.group(1))
            if b and b.records_count >= 1:
                blobs.append(b)

    blobs.sort(key=lambda b: b.records_count, reverse=True)
    return blobs
