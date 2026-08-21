"""Extraction-pipeline tests — synthetic Aalto-format participants through the real
`vector_from_sections` + `build_corpus` + `load_corpus`, so the pipeline is verified
end-to-end without the multi-GB download."""
import json

from hydra.behaviorforge import PersonaGenerator
from hydra.corpus import build_corpus, load_corpus, vector_from_sections
from hydra.human import KeystrokeModel


def _typist(gap_ms, dwell=80, n=240, back_every=0):
    """One section of n keystrokes spaced `gap_ms` apart. `back_every`>0 injects a
    backspace (keycode 8) periodically to simulate errors."""
    letters = "the quick brown fox jumps "
    sec, t = [], 1000.0
    for i in range(n):
        if back_every and i and i % back_every == 0:
            sec.append((t, t + 20, "BKSP", "8"))
        else:
            sec.append((t, t + dwell, letters[i % len(letters)], "65"))
        t += gap_ms
    return [sec]


# ── the core extractor: fast vs slow typists yield distinguishing vectors ──────────────
def test_vector_extraction_distinguishes_speed():
    fast = vector_from_sections(_typist(90), min_keys=20)
    slow = vector_from_sections(_typist(210), min_keys=20)
    assert fast and slow
    assert fast["base_ms"] < slow["base_ms"]            # speed captured
    assert 40 <= fast["dwell_ms"] <= 140                # dwell in range
    for v in (fast, slow):                              # every Persona field present
        for k in ("base_ms", "flight_sigma", "dwell_ms", "error_rate", "tempo_theta"):
            assert k in v


def test_error_rate_reflects_backspaces():
    clean = vector_from_sections(_typist(120, back_every=0), min_keys=20)
    noisy = vector_from_sections(_typist(120, back_every=8), min_keys=20)
    assert noisy["error_rate"] > clean["error_rate"]


def test_too_little_data_returns_none():
    assert vector_from_sections(_typist(120, n=10), min_keys=150) is None


def test_bigram_table_is_extracted():
    v = vector_from_sections(_typist(100), min_keys=20)
    assert v["bigram_ms"] and all(len(k) == 2 for k in v["bigram_ms"])   # measured per-bigram


# ── end to end: build a corpus file, load it, feed the generator + engine ──────────────
def test_build_load_and_generate(tmp_path):
    # write a couple of Aalto-style TSV files (fast + slow participant)
    import csv
    from hydra.corpus import COLUMNS
    tsv = tmp_path / "ks.tsv"
    with open(tsv, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow([COLUMNS[k] for k in ("participant", "section", "press", "release", "letter", "keycode")])
        for pid, gap in (("p1", 95), ("p2", 200)):
            t = 1000.0
            for i in range(240):
                w.writerow([pid, "s1", t, t + 80, "abcde"[i % 5], "65"])
                t += gap
    out = tmp_path / "corpus.json"
    n = build_corpus([str(tsv)], str(out), min_keys=20)
    assert n == 2                                       # two participants extracted

    personas = load_corpus(str(out))
    assert len(personas) == 2 and all(60 <= p.base_ms <= 300 for p in personas)

    gen = PersonaGenerator.from_file(str(out))          # real corpus drops into the generator
    p = gen.generate(seed=1)
    plans = KeystrokeModel(p).plan("hello", allow_errors=False)
    assert plans and all(pl.flight_ms > 0 for pl in plans)
