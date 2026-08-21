"""Corpus extraction — turn a real keystroke dataset into Persona vectors (v0.1).

This is BehaviorForge's data pipeline (rung 8, Path A): read a real keystroke dataset,
compute one motor-parameter vector per participant, write a corpus JSON that
`PersonaGenerator` loads in place of the placeholder archetypes.

Target dataset: **Aalto "136M Keystrokes"** (Dhakal et al. 2018) — 168k participants, TSV
logs of per-keystroke PRESS_TIME / RELEASE_TIME / LETTER / KEYCODE, grouped by
TEST_SECTION_ID (one typed sentence). 168k participants → 168k vectors = a real corpus.

    raw keydown/keyup events ──► per-participant features ──► corpus.json ──► PersonaGenerator

── HONEST STATE ────────────────────────────────────────────────────────────────────────
- The COLUMN MAP + backspace keycodes below are written from the dataset's documented
  schema — **verify against the actual files** and adjust `COLUMNS` if they differ.
- Well-defined features (base_ms, flight/dwell sigma, error_rate, the per-bigram table)
  are extracted directly. `tempo_theta/sigma`, `think_ms`, `shift_ms` are **approximated**
  from the data (marked ~) — good enough for the sampler, refine later.
- The per-bigram table is extracted and stored, but not yet consumed (that's the rung-3
  upgrade: `_bigram_offset` hash → measured lookup). It rides along in the JSON for then.
- Aalto has no mouse → `mouse_settle` gets a default; mouse params need a mouse dataset.
- Licensing: Aalto is research-use — fine for a portfolio; verify rights before shipping.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import statistics as st

from hydra.human import Persona, _clamp

# Adjust to match the real files if the schema differs.
COLUMNS = {
    "participant": "PARTICIPANT_ID", "section": "TEST_SECTION_ID",
    "press": "PRESS_TIME", "release": "RELEASE_TIME",
    "letter": "LETTER", "keycode": "KEYCODE",
}
_BACKSPACE = {"8", "backspace", "bksp"}      # keycode 8 / letter, lowercased
_SPACE = {"32", "space", " "}


def _median(xs: list[float]) -> float:
    return st.median(xs)


def _log_std(xs: list[float]) -> float:
    """Std of log(x) — the log-normal sigma estimate (matches how the model samples)."""
    logs = [math.log(x) for x in xs if x > 0]
    return st.pstdev(logs) if len(logs) > 1 else 0.25


def _lag1(xs: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(n - 1))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else 0.0


def vector_from_sections(sections: list[list[tuple]], *, min_keys: int = 150) -> dict | None:
    """PURE: participant's keystrokes (grouped by section) → one motor vector, or None if
    too little data. Each keystroke is (press_ms, release_ms, letter, keycode_str).
    Flights are press→press *within* a section (never across); afk/absurd values dropped."""
    flights: list[float] = []
    dwells: list[float] = []
    shifted_flights: list[float] = []
    bigrams: dict[str, list[float]] = {}
    n_keys = n_back = 0
    sec_acfs: list[float] = []

    for sec in sections:
        prev_press = None
        prev_letter = None
        sec_flights: list[float] = []
        for press, release, letter, keycode in sec:
            kc = str(keycode)
            letter = str(letter)
            if kc in _BACKSPACE or letter.lower() in _BACKSPACE:
                n_keys += 1
                n_back += 1
                prev_press = prev_letter = None      # a correction breaks the flight chain
                continue
            if len(letter) != 1:                     # SHIFT/CTRL/ENTER/… — skip, keep chain
                continue                             # (so flights stay letter→letter)
            n_keys += 1
            d = release - press
            if 10 <= d <= 1000:
                dwells.append(d)
            if prev_press is not None:
                f = press - prev_press
                if 0 < f <= 2000:                    # drop afk gaps + non-positive
                    flights.append(f)
                    sec_flights.append(f)
                    bigrams.setdefault(prev_letter + letter, []).append(f)
                    if letter.isupper() or letter in '~!@#$%^&*()_+{}|:"<>?':
                        shifted_flights.append(f)
            prev_press, prev_letter = press, letter
        if len(sec_flights) >= 5:
            sec_acfs.append(_lag1(sec_flights))

    if n_keys < min_keys or len(flights) < 50:
        return None

    base_ms = _median(flights)
    flight_cv = (st.pstdev(flights) / st.mean(flights)) if len(flights) > 1 else 0.3
    acf = st.mean(sec_acfs) if sec_acfs else 0.0
    p85 = sorted(flights)[min(len(flights) - 1, int(0.85 * len(flights)))]
    shift = (_median(shifted_flights) - base_ms) if len(shifted_flights) >= 20 else 55.0

    return {
        "base_ms": round(_clamp(base_ms, 60, 300), 1),
        "flight_sigma": round(_clamp(_log_std(flights), 0.15, 0.40), 3),
        "dwell_ms": round(_clamp(_median(dwells) if dwells else 85, 40, 140), 1),
        "dwell_sigma": round(_clamp(_log_std(dwells) if dwells else 0.2, 0.12, 0.30), 3),
        "error_rate": round(_clamp(n_back / max(n_keys, 1), 0.002, 0.05), 4),
        # ~approximated (marked): tempo from autocorrelation, think from the pause tail
        "tempo_theta": round(_clamp(1.0 - acf, 0.05, 0.15), 3),
        "tempo_sigma": round(_clamp(flight_cv * 0.2, 0.04, 0.09), 3),
        "think_ms": round(_clamp(p85, 100, 650), 1),
        "shift_ms": round(_clamp(shift, 25, 120), 1),
        "mouse_settle": 0.08,                        # default — Aalto has no mouse
        # extracted, not yet consumed — the rung-3 measured per-bigram table:
        "bigram_ms": {bg: round(_median(fs), 1) for bg, fs in bigrams.items() if len(fs) >= 5},
    }


def _parse_tsv(fileobj):
    """Stream (participant, section, press, release, letter, keycode) from a TSV stream."""
    c = COLUMNS
    for row in csv.DictReader(fileobj, delimiter="\t"):
        try:
            yield (row[c["participant"]], row[c["section"]],
                   float(row[c["press"]]), float(row[c["release"]]),
                   row[c["letter"]], row[c["keycode"]])
        except (KeyError, ValueError, TypeError):     # ragged/blank row → skip
            continue


def _read_rows(path: str):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        yield from _parse_tsv(f)


def build_corpus(inputs: list[str], out_path: str, *, limit: int | None = None,
                 min_keys: int = 150) -> int:
    """Read Aalto TSV(s), group by participant→section, write a corpus JSON. Returns the
    number of vectors written. `limit` caps participants (a few thousand is plenty)."""
    # group rows by participant, then section (streaming, one participant flushed at a time
    # would need sorted input; here we buffer — fine for a capped `limit`).
    people: dict[str, dict[str, list[tuple]]] = {}
    for path in inputs:
        for pid, sec, press, release, letter, keycode in _read_rows(path):
            if limit and pid not in people and len(people) >= limit:
                continue
            people.setdefault(pid, {}).setdefault(sec, []).append((press, release, letter, keycode))

    vectors = []
    for pid, secs in people.items():
        v = vector_from_sections(list(secs.values()), min_keys=min_keys)
        if v is not None:
            vectors.append(v)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(vectors, f)
    return len(vectors)


def build_corpus_from_zip(zip_path: str, out_path: str, *, limit: int | None = None,
                          min_keys: int = 150, member_glob: str = "*.txt") -> int:
    """Extract WITHOUT unzipping the 16GB — read participant files straight from the zip,
    one at a time (peak disk = the 1.4GB zip only). Each member file is treated as its own
    participant(s); grouped by section, vectorized, streamed out. `limit` caps vectors."""
    import fnmatch
    import io
    import zipfile
    vectors = []
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.namelist()
                   if fnmatch.fnmatch(os.path.basename(m).lower(), member_glob)
                   and "readme" not in m.lower() and not m.endswith("/")]
        for m in members:
            if limit and len(vectors) >= limit:
                break
            people: dict[str, dict[str, list[tuple]]] = {}
            with z.open(m) as fh:
                for pid, sec, press, release, letter, keycode in _parse_tsv(
                        io.TextIOWrapper(fh, encoding="utf-8", errors="replace")):
                    people.setdefault(pid, {}).setdefault(sec, []).append(
                        (press, release, letter, keycode))
            for secs in people.values():
                v = vector_from_sections(list(secs.values()), min_keys=min_keys)
                if v is not None:
                    vectors.append(v)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(vectors, f)
    return len(vectors)


def load_corpus(path: str) -> list[Persona]:
    """Load a corpus JSON → list[Persona] for PersonaGenerator. Ignores extra keys
    (e.g. `bigram_ms`) so the file can carry more than Persona holds today."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    fields = Persona.__dataclass_fields__
    out = []
    for v in raw:
        out.append(Persona(**{k: v[k] for k in fields if k in v}))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract a BehaviorForge corpus from Aalto TSVs")
    ap.add_argument("inputs", nargs="+", help="TSV file(s)/globs, or one .zip with --zip")
    ap.add_argument("--zip", action="store_true", help="inputs is a Keystrokes.zip (no unzip)")
    ap.add_argument("--out", default="aalto_corpus.json")
    ap.add_argument("--limit", type=int, default=None, help="cap participants (e.g. 3000)")
    ap.add_argument("--min-keys", type=int, default=150)
    args = ap.parse_args()
    if args.zip:
        n = build_corpus_from_zip(args.inputs[0], args.out, limit=args.limit,
                                  min_keys=args.min_keys)
    else:
        paths = [p for g in args.inputs for p in glob.glob(g)] or args.inputs
        n = build_corpus(paths, args.out, limit=args.limit, min_keys=args.min_keys)
    print(f"wrote {n} persona vectors → {args.out}")


if __name__ == "__main__":
    main()
