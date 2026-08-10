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
# Next.js App Router streams server data as chunks: self.__next_f.push([1,"...esc..."])
_RSC_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', re.DOTALL)
_NUXT_RE = re.compile(r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_APOLLO_RE = re.compile(r'window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;', re.DOTALL)
_LDJSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL | re.I)
_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.DOTALL | re.I)

# keys that mark a record as real *content* (a product/post/listing) rather than
# taxonomy/config — used to pick the item list out of a mixed RSC stream.
_CONTENT_KEYS = frozenset({
    "price", "brand", "brand_title", "photo", "photos", "image", "thumbnail",
    "currency", "size_title", "favourite_count", "author", "description", "content",
})


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


def _extract_json_at(text: str, start: int, cap: int = 20000) -> str | None:
    """Return the balanced {...} object beginning at `text[start]`, string-aware
    (braces inside strings don't count). None if it doesn't close within `cap`."""
    depth = 0
    in_str = esc = False
    for k in range(start, min(start + cap, len(text))):
        c = text[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:k + 1]
    return None


def _obj_start(text: str, pos: int, cap: int = 40000) -> int:
    """Backtrack from `pos` to the opening `{` of the object that directly contains
    it (so a content key anywhere in a record leads back to the record's start)."""
    depth = 0
    lo = max(0, pos - cap)
    for i in range(pos, lo - 1, -1):
        c = text[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i
            depth -= 1
    return -1


# content keys used as harvest anchors — a record has one *as a key*, and it may
# sit anywhere in the object, so we anchor on it and backtrack to the object start.
_HARVEST_ANCHORS = ('"price":', '"photos":', '"photo":', '"thumbnail":', '"image":',
                    '"brand_title":', '"author":', '"description":', '"total_item_price":')


def _harvest_records(text: str) -> list[dict]:
    """Pull record-like JSON objects out of a noisy blob (an RSC stream isn't clean
    JSON). Anchor on content keys, backtrack to each object's start, balance-match."""
    out: list[dict] = []
    seen: set[int] = set()
    for anchor in _HARVEST_ANCHORS:
        i = 0
        while len(out) < 3000:
            j = text.find(anchor, i)
            if j == -1:
                break
            i = j + len(anchor)
            s = _obj_start(text, j)
            if s == -1 or s in seen:
                continue
            seen.add(s)
            frag = _extract_json_at(text, s, cap=60000)
            if not frag:
                continue
            try:
                obj = json.loads(frag)
                if isinstance(obj, dict) and len(obj) >= 5:
                    out.append(obj)
            except (json.JSONDecodeError, ValueError):
                pass
    return out


def _rsc_blob(html: str) -> EmbeddedBlob | None:
    """Reassemble the __next_f RSC stream and harvest its biggest record set."""
    parts = _RSC_RE.findall(html)
    if not parts:
        return None
    chunks = []
    for p in parts:
        try:
            chunks.append(json.loads('"' + p + '"'))   # decode the JS string escapes
        except (json.JSONDecodeError, ValueError):
            chunks.append(p)
    stream = "".join(chunks)
    records = _harvest_records(stream)
    if len(records) < 5:
        return None
    # A stream mixes taxonomy, config, users, items… — cluster by key-shape, then
    # prefer the group that looks like *content* (has price/photo/brand-type keys)
    # over a merely-large one (a category tree can outnumber the actual items).
    groups: dict[tuple, list] = {}
    for r in records:
        groups.setdefault(tuple(sorted(r.keys())), []).append(r)

    def score(group):
        # richer content signal wins over mere size: a category tree may outnumber
        # the items but carries far fewer content keys (1 vs 4+).
        n_content = len(set(group[0].keys()) & _CONTENT_KEYS)
        return (n_content, len(group))

    main = max(groups.values(), key=score)
    if len(main) < 5:
        return None
    return EmbeddedBlob(kind="__next_f (RSC)", size=len(stream),
                        records_path=f"(RSC stream · {len(groups)} object shapes)",
                        records_count=len(main), sample=main[0])


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

    rsc = _rsc_blob(html)            # Next.js App Router RSC stream
    if rsc:
        blobs.append(rsc)

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
