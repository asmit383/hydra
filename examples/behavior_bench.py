"""Behavioral benchmark — measure the warmup's human-likeness, Camoufox vs ours.

    python examples/behavior_bench.py

There's no public *behavioral* scorer (PerimeterX/DataDome don't expose one), so
this is our own: a page records mouse telemetry — movement count, path curvature,
and timing entropy, exactly what real behavioral engines watch — and scores
human-likeness /100. It runs Camoufox twice: **baseline** (a headless discovery
session, no mouse) vs **Hydra + warmup** (Camoufox humanize driving the warmup).

Typical result: baseline 0/100 (zero mouse telemetry — a dead bot giveaway) vs
~90/100 with the warmup (~490 curved, variably-timed mousemove events, because
humanize turns each gesture into a continuous human-like stream). The `/100` is
our formula; the raw deltas (0→hundreds of moves, straight→curved, fixed→jittered)
are the objective signal.
"""
import pathlib
import tempfile

from hydra.session import launch
from hydra.discover import _behavioral_warmup

_PAGE = """<!doctype html><html><body>bench
<script>
const mv = [];
addEventListener('mousemove', e => mv.push([e.clientX, e.clientY, performance.now()]));
window.__score = () => {
  if (mv.length < 3) return {moves: mv.length, curviness: 0, timingVar: 0, human: 0};
  let angleSum = 0; const iv = [];
  for (let i = 1; i < mv.length; i++) {
    const [x0,y0,t0] = mv[i-1], [x1,y1,t1] = mv[i]; iv.push(t1-t0);
    if (i > 1) { const [x2,y2] = mv[i-2];
      let d = Math.abs(Math.atan2(y1-y0,x1-x0) - Math.atan2(y0-y2,x0-x2));
      if (d > Math.PI) d = 2*Math.PI - d; angleSum += d; }
  }
  const mean = iv.reduce((a,b)=>a+b,0)/iv.length;
  const timingVar = iv.reduce((a,b)=>a+(b-mean)**2,0)/iv.length;
  const curviness = angleSum / mv.length;
  const s = Math.min(mv.length,40) + Math.min(curviness*60,30)
          + Math.min(timingVar>2?30:timingVar*15,30);
  return {moves: mv.length, curviness:+curviness.toFixed(3),
          timingVar:Math.round(timingVar), human:Math.round(s)};
};
</script></body></html>"""


def _run(url, warmup, humanize):
    with launch(proxy=None, humanize=humanize) as page:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        if warmup:
            _behavioral_warmup(page)
        page.wait_for_timeout(500)
        return page.evaluate("() => window.__score()")


def main():
    f = pathlib.Path(tempfile.gettempdir()) / "hydra_behavior_bench.html"
    f.write_text(_PAGE)
    url = f.as_uri()

    print("\n=== BEHAVIORAL BENCHMARK — human-likeness /100 ===\n")
    base = _run(url, warmup=False, humanize=True)
    print(f"  Camoufox baseline (no warmup): {base}")
    ours = _run(url, warmup=True, humanize=2.0)
    print(f"  Hydra + warmup (humanize 2.0): {ours}")
    print(f"\n  → human score:  baseline {base['human']}/100   vs   ours {ours['human']}/100")
    print(f"    raw: moves {base['moves']}→{ours['moves']}, "
          f"curviness {base['curviness']}→{ours['curviness']}, "
          f"timingVar {base['timingVar']}→{ours['timingVar']}\n")


if __name__ == "__main__":
    main()
