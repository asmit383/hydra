"""Movement demo — Camoufox vs Hydra, one page, two panels, playing at once.

    python examples/warmup_sim.py

A page has exactly one mouse, so we can't drive two live cursors in it. Instead we
**record** both real Camoufox-humanized paths (headless), then **replay them
simultaneously** in a single window, two panels side by side:

  • LEFT  — CAMOUFOX: direct humanized moves to each target.
  • RIGHT — HYDRA (on top of Camoufox): wander → overshoot → micro-correction.

Both trails/cursors animate together at their real recorded speed, each with live
stats (mousemove events, curviness, timing variance, human score). Enter to close.
"""
import json
import pathlib
import random
import tempfile

from hydra.session import launch

FIELD_W, FIELD_H = 660, 560

_REC = """<!doctype html><body style="margin:0"><script>
window.__rec=[]; addEventListener('mousemove',e=>window.__rec.push([e.clientX,e.clientY,Math.round(performance.now())]));
</script></body>"""


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _native(page, tx, ty):
    page.mouse.move(tx, ty)


def _ours(page, tx, ty):
    page.mouse.move(_clamp(tx + random.randint(-130, 130), 10, FIELD_W - 10),
                    _clamp(ty + random.randint(-100, 100), 10, FIELD_H - 10))     # wander
    page.wait_for_timeout(random.randint(100, 240))
    page.mouse.move(_clamp(tx + random.randint(-55, 55), 10, FIELD_W - 10),
                    _clamp(ty + random.randint(-45, 45), 10, FIELD_H - 10))       # overshoot
    page.wait_for_timeout(random.randint(90, 200))
    page.mouse.move(tx, ty)                                                       # settle


def _record(approach, humanize):
    with launch(proxy=None, headless=True, humanize=humanize) as page:
        page.set_viewport_size({"width": FIELD_W, "height": FIELD_H})
        page.goto("data:text/html," + _REC, wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        page.mouse.move(FIELD_W // 2, FIELD_H // 2)
        for _ in range(9):
            approach(page, random.randint(40, FIELD_W - 40), random.randint(50, FIELD_H - 50))
            page.wait_for_timeout(random.randint(150, 320))
        return page.evaluate("() => window.__rec")


_REPLAY = r"""<!doctype html><html><head><meta charset=utf-8><style>
 *{box-sizing:border-box} body{margin:0;background:#080810;color:#cdd;font-family:ui-monospace,monospace;overflow:hidden}
 header{padding:12px 20px;border-bottom:1px solid #1c1c2a}
 header h1{margin:0;font-size:17px;color:#fff} header p{margin:3px 0 0;font-size:12px;color:#68708a}
 .panels{display:flex;height:calc(100vh - 56px)}
 .panel{flex:1;position:relative;border-right:1px solid #1c1c2a}.panel:last-child{border-right:0}
 canvas{position:absolute;inset:0}
 .tag{position:absolute;top:14px;left:16px;font-size:15px;font-weight:700;z-index:3}
 .stat{position:absolute;bottom:14px;left:16px;font-size:13px;line-height:1.8;z-index:3;color:#8a92ab}
 .stat b{color:#e6e9f2}
</style></head><body>
<header><h1>🐍 Hydra — behavioral movement: Camoufox vs Hydra</h1>
<p>same engine (Camoufox humanize); the right panel adds the human approach pattern on top · replaying real recorded paths</p></header>
<div class="panels">
 <div class="panel" id="L"><canvas></canvas><div class="tag" style="color:#3ee6ff">CAMOUFOX · direct move</div><div class="stat"></div></div>
 <div class="panel" id="R"><canvas></canvas><div class="tag" style="color:#ffb020">HYDRA · approach + correction</div><div class="stat"></div></div>
</div>
<script>
const DATA = __DATA__;
function stats(mv){ if(mv.length<3) return {moves:mv.length,curviness:0,timingVar:0,human:0};
 let ang=0; const iv=[]; for(let i=1;i<mv.length;i++){const [x0,y0,t0]=mv[i-1],[x1,y1,t1]=mv[i]; iv.push(t1-t0);
  if(i>1){const [x2,y2]=mv[i-2]; let d=Math.abs(Math.atan2(y1-y0,x1-x0)-Math.atan2(y0-y2,x0-x2)); if(d>Math.PI)d=2*Math.PI-d; ang+=d;}}
 const m=iv.reduce((a,b)=>a+b,0)/iv.length, tv=iv.reduce((a,b)=>a+(b-m)**2,0)/iv.length, c=ang/mv.length;
 return {moves:mv.length,curviness:+c.toFixed(3),timingVar:Math.round(tv),human:Math.round(Math.min(mv.length,40)+Math.min(c*60,30)+Math.min(tv>2?30:tv*15,30))};}
function panel(id,pts,color){
 const p=document.getElementById(id),cv=p.querySelector('canvas'),ctx=cv.getContext('2d'),st=p.querySelector('.stat');
 cv.width=p.clientWidth; cv.height=p.clientHeight;
 const q=stats(pts); st.innerHTML='mousemove events <b>'+q.moves+'</b><br>path curviness <b>'+q.curviness
   +'</b><br>timing variance <b>'+q.timingVar+'</b><br>human score <b>'+q.human+'/100</b>';
 const t0=pts[0][2]; const span=pts[pts.length-1][2]-t0;
 function run(){ ctx.clearRect(0,0,cv.width,cv.height); let i=0,last=null; const start=performance.now();
  (function frame(now){ const el=now-start;
    while(i<pts.length && (pts[i][2]-t0)<=el){ const [x,y]=pts[i];
      if(last){ctx.strokeStyle=color;ctx.lineWidth=2.3;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(last[0],last[1]);ctx.lineTo(x,y);ctx.stroke();}
      ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(x,y,2.4,0,7);ctx.fill(); last=[x,y]; i++; }
    if(i<pts.length) requestAnimationFrame(frame); else setTimeout(run, 1200);
  })(performance.now());
 } run();
}
panel('L',DATA.native,'#3ee6ff'); panel('R',DATA.ours,'#ffb020');
</script></body></html>"""


def main():
    print("recording both humanized paths (headless)…")
    native = _record(_native, True)
    ours = _record(_ours, 2.5)
    html = _REPLAY.replace("__DATA__", json.dumps({"native": native, "ours": ours}))
    f = pathlib.Path(tempfile.gettempdir()) / "hydra_movement_demo.html"
    f.write_text(html)
    print(f"native path: {len(native)} points · ours path: {len(ours)} points")
    print("opening the replay window — both panels play at once…")
    with launch(proxy=None, headless=False, humanize=True) as page:
        page.goto(f.as_uri(), wait_until="domcontentloaded", timeout=30000)
        input("\n(both panels animating side by side) — press Enter to close… ")


if __name__ == "__main__":
    main()
