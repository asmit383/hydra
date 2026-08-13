"""Movement demo — Camoufox vs Hydra, side by side in one page.

    python examples/warmup_sim.py

A headful window split into two live panels, each with a button that jumps on
click and a cursor that chases it:

  • LEFT  — CAMOUFOX: one direct humanized move onto the target.
  • RIGHT — HYDRA (on top of Camoufox): a human approach — wander → overshoot →
            micro-correction → click. Both are curved by Camoufox humanize; Hydra
            adds the multi-phase "submovement" pattern a real hand makes.

Each panel shows live stats — mousemove events, path curviness, timing variance,
and a human-likeness score — so you can compare what Camoufox does vs what our
layer adds on top of it. The rounds alternate so both fill together. Enter to close.
"""
import pathlib
import random
import tempfile

from hydra.session import launch

_PAGE = r"""<!doctype html><html><head><meta charset=utf-8><style>
  *{box-sizing:border-box} body{margin:0;background:#080810;color:#cdd;font-family:ui-monospace,monospace;overflow:hidden}
  header{padding:12px 20px;border-bottom:1px solid #1c1c2a}
  header h1{margin:0;font-size:17px;color:#fff} header p{margin:3px 0 0;font-size:12px;color:#68708a}
  .panels{display:flex;height:calc(100vh - 56px)}
  .panel{flex:1;position:relative;border-right:1px solid #1c1c2a;overflow:hidden}
  .panel:last-child{border-right:0}
  canvas{position:absolute;inset:0}
  .tag{position:absolute;top:12px;left:14px;font-size:14px;font-weight:700;z-index:3}
  .stat{position:absolute;bottom:12px;left:14px;font-size:12px;line-height:1.7;z-index:3;color:#8a92ab}
  .stat b{color:#e6e9f2;font-weight:700}
  button.t{position:absolute;padding:12px 18px;font:700 14px ui-monospace,monospace;color:#080810;
    border:0;border-radius:9px;cursor:pointer;z-index:2}
</style></head><body>
<header><h1>🐍 Hydra — behavioral movement: Camoufox vs Hydra</h1>
<p>same engine (Camoufox humanize); the right panel adds the human approach pattern on top</p></header>
<div class="panels">
  <div class="panel" id="L"><canvas></canvas><div class="tag" style="color:#3ee6ff">CAMOUFOX · humanize</div>
    <button class="t" style="background:#3ee6ff">CLICK</button><div class="stat"></div></div>
  <div class="panel" id="R"><canvas></canvas><div class="tag" style="color:#ffb020">HYDRA · humanize + approach</div>
    <button class="t" style="background:#ffb020">CLICK</button><div class="stat"></div></div>
</div>
<script>
function mk(id,color){
  const p=document.getElementById(id), cv=p.querySelector('canvas'), btn=p.querySelector('button'),
        st=p.querySelector('.stat');
  const size=()=>{cv.width=p.clientWidth; cv.height=p.clientHeight;}; size(); addEventListener('resize',size);
  const S={p,cv,ctx:cv.getContext('2d'),btn,st,color,mv:[],last:null,clicks:0};
  const place=()=>{const w=p.clientWidth,h=p.clientHeight;
    btn.style.left=(30+Math.random()*(w-140))+'px'; btn.style.top=(50+Math.random()*(h-120))+'px';};
  place(); btn.addEventListener('click',()=>{S.clicks++; place();});
  return S;
}
const L=mk('L','#3ee6ff'), R=mk('R','#ffb020');
function stats(S){
  const mv=S.mv; if(mv.length<3) return {moves:mv.length,curviness:0,timingVar:0,human:0};
  let ang=0; const iv=[];
  for(let i=1;i<mv.length;i++){const [x0,y0,t0]=mv[i-1],[x1,y1,t1]=mv[i]; iv.push(t1-t0);
    if(i>1){const [x2,y2]=mv[i-2]; let d=Math.abs(Math.atan2(y1-y0,x1-x0)-Math.atan2(y0-y2,x0-x2));
      if(d>Math.PI)d=2*Math.PI-d; ang+=d;}}
  const m=iv.reduce((a,b)=>a+b,0)/iv.length, tv=iv.reduce((a,b)=>a+(b-m)**2,0)/iv.length, cv=ang/mv.length;
  const s=Math.min(mv.length,40)+Math.min(cv*60,30)+Math.min(tv>2?30:tv*15,30);
  return {moves:mv.length,curviness:+cv.toFixed(3),timingVar:Math.round(tv),human:Math.round(s)};
}
function render(S){const q=stats(S);
  S.st.innerHTML='mousemove events <b>'+q.moves+'</b><br>path curviness <b>'+q.curviness
    +'</b><br>timing variance <b>'+q.timingVar+'</b><br>clicks <b>'+S.clicks
    +'</b><br>human score <b>'+q.human+'/100</b>';}
addEventListener('mousemove',e=>{
  const S = e.clientX < innerWidth/2 ? L : R;
  const r = S.cv.getBoundingClientRect(); const x=e.clientX-r.left, y=e.clientY-r.top;
  S.mv.push([x,y,performance.now()]);
  if(S.last){S.ctx.strokeStyle=S.color;S.ctx.lineWidth=2.2;S.ctx.lineCap='round';
    S.ctx.beginPath();S.ctx.moveTo(S.last[0],S.last[1]);S.ctx.lineTo(x,y);S.ctx.stroke();}
  S.ctx.fillStyle='#fff';S.ctx.beginPath();S.ctx.arc(x,y,1.4,0,7);S.ctx.fill();
  S.last=[x,y]; render(S);
});
render(L); render(R);
</script></body></html>"""


def _center(page, side):
    b = page.locator(f"#{side} button").bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _native(page, cx, cy):
    page.mouse.move(cx, cy)                      # one direct humanized arc
    page.mouse.click(cx, cy)


def _ours(page, cx, cy):
    page.mouse.move(cx + random.randint(-120, 120), cy + random.randint(-90, 90))   # wander in
    page.wait_for_timeout(random.randint(100, 240))
    page.mouse.move(cx + random.randint(-55, 55), cy + random.randint(-40, 40))     # overshoot
    page.wait_for_timeout(random.randint(90, 200))
    page.mouse.move(cx, cy)                                                          # settle
    page.wait_for_timeout(random.randint(70, 150))
    page.mouse.click(cx, cy)


def main():
    f = pathlib.Path(tempfile.gettempdir()) / "hydra_movement_demo.html"
    f.write_text(_PAGE)
    print("opening headful Camoufox — LEFT = Camoufox, RIGHT = Hydra (on top of it)…")
    with launch(proxy=None, headless=False, humanize=2.5) as page:
        page.goto(f.as_uri(), wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)
        for r in range(1, 17):
            side = "L" if r % 2 else "R"
            cx, cy = _center(page, side)
            (_native if side == "L" else _ours)(page, cx, cy)
            page.wait_for_timeout(random.randint(400, 800))
        input("\n(compare the two panels + their stats) — press Enter to close… ")


if __name__ == "__main__":
    main()
