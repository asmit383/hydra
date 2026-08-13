"""Watch the behavioral warmup — a headful window that paints the mouse trail.

    python examples/warmup_sim.py

Opens a real Camoufox window on a page that draws every mousemove, then runs an
(extended) warmup so you can SEE Camoufox's humanize: each gesture becomes a
curved, variable-speed stream of points — a real hand, not a teleport. The event
counter climbs into the hundreds from only a handful of move() calls, which is the
whole trick. Press Enter in the terminal to close.
"""
import pathlib
import random
import tempfile

from hydra.session import launch

_PAGE = """<!doctype html><html><body style="margin:0;overflow:hidden;background:#0b0b12">
<canvas id="c" style="display:block"></canvas>
<div id="n" style="position:fixed;top:12px;left:14px;font:18px monospace;color:#3ef">🐍 hydra warmup — mousemove events: 0</div>
<script>
const c=document.getElementById('c'), ctx=c.getContext('2d');
c.width=innerWidth; c.height=innerHeight; let last=null, n=0;
addEventListener('mousemove', e=>{
  n++; document.getElementById('n').innerText='🐍 hydra warmup — mousemove events: '+n;
  const x=e.clientX, y=e.clientY;
  if(last){ ctx.strokeStyle='hsl('+(n%360)+',90%,62%)'; ctx.lineWidth=2.2; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(last[0],last[1]); ctx.lineTo(x,y); ctx.stroke(); }
  ctx.fillStyle='#8ff'; ctx.beginPath(); ctx.arc(x,y,2.5,0,7); ctx.fill(); last=[x,y];
});
</script></body></html>"""


def _demo_warmup(page):
    """Richer than the real _behavioral_warmup — more moves, so the trail is vivid."""
    try:
        for _ in range(random.randint(14, 20)):
            page.mouse.move(random.randint(80, 1160), random.randint(80, 720))
            page.wait_for_timeout(random.randint(150, 550))
        page.mouse.wheel(0, random.randint(300, 900))
        page.wait_for_timeout(random.randint(500, 1200))
        page.mouse.wheel(0, -random.randint(100, 400))
    except Exception:
        pass


def main():
    f = pathlib.Path(tempfile.gettempdir()) / "hydra_trail.html"
    f.write_text(_PAGE)
    print("opening a headful Camoufox window — watch the humanized mouse trail…")
    with launch(proxy=None, headless=False, humanize=2.5) as page:
        page.goto(f.as_uri(), wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1000)
        _demo_warmup(page)
        input("\n(watch the window) — press Enter to close… ")


if __name__ == "__main__":
    main()
