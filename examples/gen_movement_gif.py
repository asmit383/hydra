"""Regenerate assets/movement.gif — Hydra's humanized cursor as a red dot, no trail.

    python examples/gen_movement_gif.py

Drives the REAL Camoufox mouse (humanize on) through Hydra's approach pattern —
mostly direct, occasional overshoot/hesitate — records the humanized path, and
renders it to a small looping GIF (just the red cursor dot on dark, no trail).
Used in the README. Needs pillow (`pip install pillow`).
"""
import pathlib
import random
import tempfile

from PIL import Image, ImageDraw

from hydra.session import launch

F = 460
_REC = ('<!doctype html><body style="margin:0;background:#080810"><script>'
        'window.__r=[];addEventListener("mousemove",e=>window.__r.push('
        '[e.clientX,e.clientY,Math.round(performance.now())]));</script></body>')


def _cl(v):
    return max(10, min(F - 10, v))


def _ours(page, tx, ty):                          # mostly direct, imperfect occasionally
    r = random.random()
    if r < 0.70:
        page.mouse.move(tx, ty)
    elif r < 0.90:
        page.mouse.move(_cl(tx + random.randint(-45, 45)), _cl(ty + random.randint(-40, 40)))
        page.wait_for_timeout(random.randint(70, 160)); page.mouse.move(tx, ty)
    else:
        page.mouse.move(_cl(tx + random.randint(-24, 24)), _cl(ty + random.randint(-20, 20)))
        page.wait_for_timeout(random.randint(220, 460)); page.mouse.move(tx, ty)
    page.wait_for_timeout(random.randint(150, 330))


def _record():
    rec = pathlib.Path(tempfile.gettempdir()) / "hydra_rec.html"
    rec.write_text(_REC)
    with launch(proxy=None, headless=True, humanize=1.2) as page:
        page.set_viewport_size({"width": F, "height": F})
        page.goto(rec.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(300)
        page.mouse.move(F // 2, F // 2)
        for _ in range(9):
            _ours(page, random.randint(30, F - 30), random.randint(30, F - 30))
        return page.evaluate("() => window.__r")


def _at(pts, tt):
    for i in range(1, len(pts)):
        if pts[i][2] >= tt:
            a, b = pts[i - 1], pts[i]; s = (b[2] - a[2]) or 1; f = (tt - a[2]) / s
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
    return pts[-1][0], pts[-1][1]


def main():
    pts = _record()
    print(f"recorded {len(pts)} humanized points")
    N, (t0, t1) = 140, (pts[0][2], pts[-1][2])
    frames = []
    for k in range(N):
        x, y = _at(pts, t0 + (t1 - t0) * k / N)
        img = Image.new("RGB", (F, F), (8, 8, 16)); d = ImageDraw.Draw(img)
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(90, 16, 12))    # glow
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(240, 55, 40))       # core
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 190, 170))     # highlight
        frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=24))
    out = pathlib.Path(__file__).resolve().parent.parent / "assets" / "movement.gif"
    out.parent.mkdir(exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=45, loop=0, optimize=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
