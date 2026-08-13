"""Movement demo — Camoufox vs Hydra, two independent windows, live & simultaneous.

    python examples/warmup_sim.py

Browser rule: one page = one mouse. So to show two *independent* cursors moving at
the same time, this opens **two Camoufox windows**, one per approach, driven by a
thread each — they chase their jumping buttons simultaneously:

  • CAMOUFOX (cyan)  — one direct humanized move onto the target.
  • HYDRA    (gold)  — on top of Camoufox: wander → overshoot → micro-correction,
                       the multi-phase approach a real hand makes.

Each window shows its own live stats (mousemove events, curviness, timing variance,
human score). Drag the two windows side by side to compare. Enter to close both.
"""
import pathlib
import random
import tempfile
import threading

from hydra.session import launch

_PAGE = r"""<!doctype html><html><head><meta charset=utf-8><style>
  *{box-sizing:border-box} body{margin:0;background:#080810;color:#cdd;font-family:ui-monospace,monospace;overflow:hidden}
  canvas{position:absolute;inset:0}
  .tag{position:absolute;top:14px;left:16px;font-size:16px;font-weight:700;z-index:3;color:__C__}
  .sub{position:absolute;top:38px;left:16px;font-size:12px;z-index:3;color:#68708a}
  .stat{position:absolute;bottom:14px;left:16px;font-size:13px;line-height:1.8;z-index:3;color:#8a92ab}
  .stat b{color:#e6e9f2} button.t{position:absolute;padding:12px 18px;font:700 14px ui-monospace,monospace;
    color:#080810;background:__C__;border:0;border-radius:9px;cursor:pointer;z-index:2}
</style></head><body>
<canvas></canvas><div class="tag">__TAG__</div><div class="sub">__SUB__</div>
<button class="t">CLICK</button><div class="stat"></div>
<script>
const cv=document.querySelector('canvas'),ctx=cv.getContext('2d'),btn=document.querySelector('button'),st=document.querySelector('.stat');
const size=()=>{cv.width=innerWidth;cv.height=innerHeight}; size(); addEventListener('resize',size);
const mv=[]; let last=null, clicks=0; const COL='__C__';
const place=()=>{btn.style.left=(30+Math.random()*(innerWidth-140))+'px'; btn.style.top=(70+Math.random()*(innerHeight-160))+'px';};
place(); btn.addEventListener('click',()=>{clicks++; place();});
function stats(){ if(mv.length<3) return {moves:mv.length,curviness:0,timingVar:0,human:0};
  let ang=0; const iv=[]; for(let i=1;i<mv.length;i++){const [x0,y0,t0]=mv[i-1],[x1,y1,t1]=mv[i]; iv.push(t1-t0);
    if(i>1){const [x2,y2]=mv[i-2]; let d=Math.abs(Math.atan2(y1-y0,x1-x0)-Math.atan2(y0-y2,x0-x2)); if(d>Math.PI)d=2*Math.PI-d; ang+=d;}}
  const m=iv.reduce((a,b)=>a+b,0)/iv.length, tv=iv.reduce((a,b)=>a+(b-m)**2,0)/iv.length, c=ang/mv.length;
  return {moves:mv.length,curviness:+c.toFixed(3),timingVar:Math.round(tv),human:Math.round(Math.min(mv.length,40)+Math.min(c*60,30)+Math.min(tv>2?30:tv*15,30))};}
function render(){const q=stats(); st.innerHTML='mousemove events <b>'+q.moves+'</b><br>path curviness <b>'+q.curviness
  +'</b><br>timing variance <b>'+q.timingVar+'</b><br>clicks <b>'+clicks+'</b><br>human score <b>'+q.human+'/100</b>';}
addEventListener('mousemove',e=>{const x=e.clientX,y=e.clientY; mv.push([x,y,performance.now()]);
  if(last){ctx.strokeStyle=COL;ctx.lineWidth=2.2;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(last[0],last[1]);ctx.lineTo(x,y);ctx.stroke();}
  ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(x,y,1.5,0,7);ctx.fill(); last=[x,y]; render();});
render();
</script></body></html>"""


def _page(tag, sub, color):
    html = _PAGE.replace("__TAG__", tag).replace("__SUB__", sub).replace("__C__", color)
    f = pathlib.Path(tempfile.gettempdir()) / f"hydra_demo_{color.strip('#')}.html"
    f.write_text(html)
    return f.as_uri()


def _center(page):
    b = page.locator("button").bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _native(page, cx, cy):
    page.mouse.move(cx, cy)
    page.mouse.click(cx, cy)


def _ours(page, cx, cy):
    page.mouse.move(cx + random.randint(-120, 120), cy + random.randint(-90, 90))
    page.wait_for_timeout(random.randint(100, 240))
    page.mouse.move(cx + random.randint(-55, 55), cy + random.randint(-40, 40))
    page.wait_for_timeout(random.randint(90, 200))
    page.mouse.move(cx, cy)
    page.wait_for_timeout(random.randint(70, 150))
    page.mouse.click(cx, cy)


_close = threading.Event()


def _run_window(url, approach, humanize):
    with launch(proxy=None, headless=False, humanize=humanize) as page:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)
        while not _close.is_set():
            cx, cy = _center(page)
            approach(page, cx, cy)
            page.wait_for_timeout(random.randint(450, 850))


def main():
    camo = _page("CAMOUFOX", "humanize — direct move", "#3ee6ff")
    hydra = _page("HYDRA", "on top of Camoufox — approach + micro-correction", "#ffb020")
    print("opening TWO Camoufox windows (drag them side by side)…")
    t1 = threading.Thread(target=_run_window, args=(camo, _native, True), daemon=True)
    t2 = threading.Thread(target=_run_window, args=(hydra, _ours, 2.5), daemon=True)
    t1.start(); t2.start()
    input("\n(two windows chasing simultaneously) — press Enter to close both… ")
    _close.set()
    t1.join(timeout=5); t2.join(timeout=5)


if __name__ == "__main__":
    main()
