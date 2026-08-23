"""Calibrate MouseForge from a real mouse-dynamics dataset (SapiMouse — Apache-2.0, 120 users).

Turns raw `(timestamp, button, state, x, y)` mouse logs into a **measured** `MousePersona` corpus —
ONE coherent vector per user — as JSON that `MouseForge.from_file()` loads. This is the honest
answer to the project's own edge ("mouse not dataset-calibrated"): the persona *range* stops being
4 hand-picked archetypes and becomes 120 real humans. Coherence is free — each vector is one real
person, so `generate()` sampling a random user + jitter draws from the empirical JOINT distribution
(no fitted copula needed; the real vectors *are* the joint).

Feature mapping (raw trajectory → the MousePersona schema MouseForge already uses):
  speed     = move_time / (50 + dist*0.34)     ← the trajectory() time-model's own multiplier
  curve     = max perpendicular deviation / distance          (the sine-arc bow magnitude)
  overshoot = fraction of movements that project PAST the target then correct
  tremor    = median high-frequency jitter, px  (|p[i] - midpoint(p[i-1], p[i+1])|)
  settle_ms = dwell before the click

Usage:
  # download SapiMouse: https://ms.sapientia.ro/~manyi/sapimouse/  (github.com/margitantal68/sapimouse)
  python -m hydra.mouse_calibrate /path/to/sapimouse --out data/mouse_corpus.json
  # then:  MouseForge.from_file("data/mouse_corpus.json")   → calibrated, measured-not-guessed

Layout assumption: one folder per user, each holding that user's session CSV(s). Adjust if the
release nests differently — the per-user grouping is `--group-depth` (default: the leaf folder).
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics

# MousePersona valid ranges — MUST match hydra.mouseforge._clamp bounds (so from_file loads clean).
_RANGES = {"speed": (0.5, 1.7), "curve": (0.05, 0.5), "overshoot": (0.02, 0.45),
           "tremor": (0.3, 2.5), "settle_ms": (30.0, 180.0)}
_MIN_DIST = 40.0        # skip micro-jitters — a "movement" must actually travel
_MIN_PTS = 5            # too few samples → no shape to measure
_PAUSE_MS = 250.0       # a gap this long closes a movement (arrival / new intent)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def parse_log(path: str) -> list[tuple]:
    """Read a SapiMouse CSV → [(t_ms, x, y, state)]. Tolerant of a header row and column order;
    normalizes the timestamp to milliseconds (SapiMouse's client timestamp is in seconds)."""
    rows, header = [], None
    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            for i, r in enumerate(csv.reader(f)):
                if not r:
                    continue
                if i == 0 and any(c.strip() and not _isnum(c) for c in r):   # header line
                    header = [c.strip().lower() for c in r]
                    continue
                try:
                    if header and "x" in header and "y" in header:
                        d = dict(zip(header, r))
                        t = float(d.get("timestamp") or d.get("client timestamp") or d.get("t"))
                        x, y = float(d["x"]), float(d["y"])
                        st = (d.get("state") or "").lower()
                    else:                                    # positional: t, button, state, x, y
                        t, st = float(r[0]), (r[2].lower() if len(r) > 2 else "")
                        x, y = float(r[-2]), float(r[-1])
                except (ValueError, IndexError, KeyError):
                    continue
                rows.append((t, x, y, st))
    except OSError:
        return []
    if len(rows) < 2:
        return []
    dts = [rows[i + 1][0] - rows[i][0] for i in range(min(200, len(rows) - 1))]
    med = statistics.median([d for d in dts if d > 0] or [1.0])
    scale = 1000.0 if med < 1.0 else 1.0                     # seconds → ms
    return [(t * scale, x, y, st) for (t, x, y, st) in rows]


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def segment(events: list[tuple]) -> list[tuple]:
    """Split the event stream into point-to-point MOVEMENTS: a run of samples that ends at a click
    (state contains 'press'/'down') or a pause. Returns [(points, clicked_bool), ...]."""
    out, cur = [], []
    for (t, x, y, st) in events:
        if cur and (t - cur[-1][0] > _PAUSE_MS):            # pause → close (no click)
            if len(cur) >= _MIN_PTS:
                out.append((cur, False))
            cur = []
        cur.append((t, x, y))
        if "press" in st or "down" in st:                   # click → close (with target)
            if len(cur) >= _MIN_PTS:
                out.append((cur, True))
            cur = []
    if len(cur) >= _MIN_PTS:
        out.append((cur, False))
    return out


def _perp(px, py, ax, ay, bx, by) -> float:
    """Perpendicular distance of (px,py) from the line a→b."""
    dx, dy = bx - ax, by - ay
    return abs((px - ax) * dy - (py - ay) * dx) / (math.hypot(dx, dy) or 1.0)


def features(movement: tuple) -> dict | None:
    """One movement → its persona features (or None if too small to be meaningful)."""
    pts, clicked = movement
    (t0, x0, y0), (t1, x1, y1) = pts[0], pts[-1]
    dist, move_time = math.hypot(x1 - x0, y1 - y0), (pts[-1][0] - pts[0][0])
    if dist < _MIN_DIST or move_time <= 0:
        return None
    curve = max(_perp(x, y, x0, y0, x1, y1) for (_, x, y) in pts) / dist
    ux, uy = (x1 - x0) / dist, (y1 - y0) / dist              # axis start→end
    projs = [(x - x0) * ux + (y - y0) * uy for (_, x, y) in pts]
    overshoot = 1.0 if max(projs) > dist * 1.02 else 0.0     # went past the target then corrected
    jit = [math.hypot(pts[i][1] - (pts[i - 1][1] + pts[i + 1][1]) / 2,
                      pts[i][2] - (pts[i - 1][2] + pts[i + 1][2]) / 2)
           for i in range(1, len(pts) - 1)]
    tremor = statistics.median(jit) if jit else 0.0
    speed = move_time / (50.0 + dist * 0.34)                 # the trajectory() time-model multiplier
    settle = (pts[-1][0] - pts[-2][0]) if clicked and len(pts) >= 2 else None
    return {"speed": speed, "curve": curve, "overshoot": overshoot,
            "tremor": tremor, "settle_ms": settle}


def persona_from(feats: list[dict]) -> dict | None:
    """A user's per-movement features → one clamped MousePersona vector (medians; overshoot=rate)."""
    if not feats:
        return None

    def med(key, default):
        vals = [f[key] for f in feats if f.get(key) is not None]
        return statistics.median(vals) if vals else default

    raw = {"speed": med("speed", 1.0), "curve": med("curve", 0.2),
           "overshoot": statistics.mean(f["overshoot"] for f in feats),
           "tremor": med("tremor", 1.0), "settle_ms": med("settle_ms", 80.0)}
    return {k: round(_clamp(v, *_RANGES[k]), 4) for k, v in raw.items()}


def user_features(csv_paths: list[str]) -> list[dict]:
    """All movement-features for one user (across their session files)."""
    feats: list[dict] = []
    for p in csv_paths:
        feats += [f for f in (features(m) for m in segment(parse_log(p))) if f]
    return feats


def build_corpus(root: str, min_movements: int = 3) -> list[dict]:
    """Walk the dataset — one MousePersona per user (a folder of session CSVs)."""
    corpus = []
    for dirpath, _dirs, files in os.walk(root):
        csvs = [os.path.join(dirpath, f) for f in files if f.lower().endswith(".csv")]
        if not csvs:
            continue
        feats = user_features(csvs)
        if len(feats) >= min_movements:
            corpus.append(persona_from(feats))
    return corpus


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Extract a MouseForge persona corpus from SapiMouse.")
    ap.add_argument("root", help="path to the extracted SapiMouse dataset (user folders of CSVs)")
    ap.add_argument("--out", default="mouse_corpus.json", help="output JSON path")
    a = ap.parse_args(argv)
    corpus = build_corpus(a.root)
    if not corpus:
        print(f"no personas extracted from {a.root!r} — check the layout (one folder per user).")
        return 1
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2)
    print(f"{len(corpus)} measured personas → {a.out}   (load with MouseForge.from_file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
