"""Cat-and-mouse sim — watch NATIVE vs OURS chase a jumping button, in one tab.

    python examples/warmup_sim.py

A headful Camoufox window with a button that teleports to a random spot every time
it's clicked. The cursor chases it, and each round alternates the *approach*:

  • NATIVE (cyan trail)  — one direct humanized move straight onto the button.
  • OURS   (gold trail)  — a human approach: overshoot / near-miss, a beat, then a
                           micro-correction onto the target (the "submovement"
                           humans actually do) + slower humanize.

Both are curved by Camoufox humanize; OURS adds the approach-and-settle pattern a
real hand makes instead of landing dead-center on the first try. Watch the trail
shapes differ. Press Enter to close.
"""
import pathlib
import random
import tempfile

from hydra.session import launch

_PAGE = """<!doctype html><html><body style="margin:0;overflow:hidden;background:#0b0b12;font-family:monospace">
<canvas id="c" style="position:absolute;inset:0"></canvas>
<button id="target" style="position:absolute;left:600px;top:360px;padding:14px 22px;
  font:bold 16px monospace;color:#0b0b12;background:#3ef;border:0;border-radius:10px;
  cursor:pointer;z-index:2">CLICK ME</button>
<div id="hud" style="position:absolute;top:12px;left:14px;z-index:2;font:16px monospace;color:#8ff">
  round 0 · clicks 0</div>
<script>
const c=document.getElementById('c'), ctx=c.getContext('2d'), t=document.getElementById('target');
c.width=innerWidth; c.height=innerHeight; let last=null;
window.__mode='native'; window.__clicks=0; window.__round=0;
const COL={native:'#3ef', ours:'#fb0'};
addEventListener('mousemove', e=>{
  const x=e.clientX, y=e.clientY;
  if(last){ ctx.strokeStyle=COL[window.__mode]; ctx.lineWidth=2.2; ctx.lineCap='round';
    ctx.beginPath(); ctx.moveTo(last[0],last[1]); ctx.lineTo(x,y); ctx.stroke(); }
  ctx.fillStyle='#fff'; ctx.beginPath(); ctx.arc(x,y,1.6,0,7); ctx.fill(); last=[x,y];
});
t.addEventListener('click', ()=>{
  window.__clicks++;
  const nx=60+Math.random()*(innerWidth-220), ny=90+Math.random()*(innerHeight-180);
  t.style.left=nx+'px'; t.style.top=ny+'px';
  t.style.background=COL[window.__mode];
  document.getElementById('hud').innerText=
    'round '+window.__round+' · clicks '+window.__clicks+' · MODE: '+window.__mode.toUpperCase()
    +(window.__mode==='native'?' (direct move)':' (approach + micro-correction)');
});
window.__setmode=(m,r)=>{ window.__mode=m; window.__round=r;
  document.getElementById('hud').innerText='round '+r+' · clicks '+window.__clicks+' · MODE: '+m.toUpperCase(); };
</script></body></html>"""


def _center(page):
    b = page.locator("#target").bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _native(page, cx, cy):
    page.mouse.move(cx, cy)          # one direct humanized curve to the target
    page.mouse.click(cx, cy)


def _ours(page, cx, cy):
    ox, oy = cx + random.randint(-70, 70), cy + random.randint(-70, 70)
    page.mouse.move(ox, oy)          # approach / near-miss
    page.wait_for_timeout(random.randint(120, 320))
    page.mouse.move(cx, cy)          # micro-correction onto the button
    page.wait_for_timeout(random.randint(80, 200))
    page.mouse.click(cx, cy)


def main():
    f = pathlib.Path(tempfile.gettempdir()) / "hydra_chase.html"
    f.write_text(_PAGE)
    print("opening headful Camoufox — cyan = NATIVE (direct), gold = OURS (approach+correct)…")
    with launch(proxy=None, headless=False, humanize=2.5) as page:
        page.goto(f.as_uri(), wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1000)
        for r in range(1, 13):
            mode = "native" if r % 2 else "ours"
            page.evaluate(f"window.__setmode('{mode}', {r})")
            cx, cy = _center(page)
            (_native if mode == "native" else _ours)(page, cx, cy)
            page.wait_for_timeout(random.randint(500, 1000))
        input("\n(watch the two trail styles) — press Enter to close… ")


if __name__ == "__main__":
    main()
