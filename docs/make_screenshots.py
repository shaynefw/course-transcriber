#!/usr/bin/env python3
"""
Rebuilds the README screenshots and the animated tour.

It does NOT use your own files. It builds a demo library from original content (narrated lessons with drawn slides),
runs the real tool on it (real transcription, real snapshots), and photographs the real panel with headless Chrome. So the
pictures are honest, reproducible, and show nothing private or copyrighted. Paths shown in the panel are masked.

    python3 docs/make_screenshots.py --work /some/scratch/folder

Needs: macOS, Google Chrome, the tool's Python environment (faster-whisper, Pillow, numpy, imageio-ffmpeg) and
`pip install websocket-client`. Takes a few minutes. Output: docs/screenshots/*.png and docs/screenshots/tour.gif
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import cdp  # noqa: E402
import demo_media  # noqa: E402

PORT = 8790
BASE = f"http://127.0.0.1:{PORT}/"
FAKE_ROOT = "/Users/you/Transcriber"
FAKE_ORIG = "/Users/you/Voice Memos"

LAUNCH = '''import sys
from pathlib import Path
sys.path.insert(0, ".")
import gui
REAL, ORIG = str(Path(".").resolve()), "%(orig)s"
old = gui.Handler._send
def _send(self, code, body, ctype="application/json", cache="no-store"):
    if isinstance(body, str):
        body = body.replace(REAL, "%(root)s").replace(ORIG, "%(forig)s")
    elif ctype.startswith(("text/", "application/json", "application/javascript")):
        body = body.decode("utf-8").replace(REAL, "%(root)s").replace(ORIG, "%(forig)s").encode("utf-8")
    return old(self, code, body, ctype, cache)
gui.Handler._send = _send
gui.main()
'''


TOUR = [        # (screenshot, caption) in the order they appear in the animated tour
    ("transcribe-select", "TRANSCRIBE: pick exactly which videos"),
    ("transcribe-running", "Live progress and time estimates, always on screen"),
    ("snapshots-select", "SNAPSHOTS: frames where something is on screen"),
    ("files-transcript", "FILES: read every transcript, with search"),
    ("files-timestamps", "[VISUAL] lines mark what's on screen"),
    ("files-gallery", "Browse the snapshots as a gallery"),
    ("files-lightbox", "Zoom in, with the words spoken at that moment"),
    ("files-ai-notes", "The AI keeps its notes per lesson, readable here"),
    ("ai-prompt", "AI: one prompt points your AI at it all"),
]


def say(msg):
    print(msg, flush=True)


def copy_app(app):
    if app.exists():
        shutil.rmtree(app, ignore_errors=True)
    # copy exactly what git would publish (tracked files plus new files that aren't ignored), so private folders never come along
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    for rel in files:
        if rel.startswith("docs/") or rel.endswith(".command") or not (REPO / rel).is_file():
            continue
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, app / rel)


class Panel:
    def __init__(self):
        self.token = ""

    def get(self, path):
        return json.load(urllib.request.urlopen(BASE + path.lstrip("/"), timeout=30))

    def post(self, path, body=None):
        req = urllib.request.Request(BASE + path.lstrip("/"), data=json.dumps(body or {}).encode(),
                                     headers={"X-Token": self.get("api/status")["token"], "Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=60))


def wait_idle(panel, timeout=900):
    t0 = time.time()
    time.sleep(2)
    while time.time() - t0 < timeout:
        s = panel.get("api/status")
        if not s["running"]:
            return s
        time.sleep(1.5)
    raise TimeoutError("job didn't finish")


def jq(ch, code, wait=0):
    """Run async JS in the page."""
    return ch.js("(async()=>{ const sleep=ms=>new Promise(r=>setTimeout(r,ms));"
                 "const click=(sel,txt)=>{const el=[...document.querySelectorAll(sel)].find(e=>!txt||e.textContent.includes(txt)); if(!el) throw new Error('missing '+sel+' '+txt); el.click(); return el;};"
                 + code + (f"; await sleep({wait});" if wait else "") + " })()")


def open_tab(ch, tab, wait=1600):
    jq(ch, f"setTab('{tab}'); await sleep({wait}); window.scrollTo(0,0);")


def shot(ch, out, name):
    time.sleep(0.4)
    ch.shot(out / f"{name}.png")
    say(f"  captured {name}.png")


def tidy(out):
    """Smaller PNGs: README images don't need 24-bit color."""
    for p in out.glob("*.png"):
        im = Image.open(p).convert("RGB")
        q = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        q.save(p, optimize=True)


def build_gif(out, frames):
    font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 23)
    imgs = []
    frames = [f for f in frames if (out / f"{f[0]}.png").exists()]
    for i, (name, caption) in enumerate(frames):
        im = Image.open(out / f"{name}.png").convert("RGB")
        w = 1000
        im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
        d = ImageDraw.Draw(im, "RGBA")
        bar = 56
        d.rectangle([0, im.height - bar, w, im.height], fill=(2, 11, 5, 235))
        d.line([0, im.height - bar, w, im.height - bar], fill=(66, 255, 148, 255), width=2)
        d.text((22, im.height - bar + 15), caption, font=font, fill=(66, 255, 148, 255))
        for k in range(len(frames)):                       # slider dots
            x = w - 24 - (len(frames) - 1 - k) * 22
            d.ellipse([x - 6, im.height - 31, x + 6, im.height - 19], fill=(66, 255, 148, 255) if k == i else (19, 128, 63, 255))
        imgs.append(im.convert("P", palette=Image.Palette.ADAPTIVE, colors=160, dither=Image.Dither.NONE))
    imgs[0].save(out / "tour.gif", save_all=True, append_images=imgs[1:], duration=3200, loop=0, optimize=True, disposal=2)
    say(f"  tour.gif: {(out / 'tour.gif').stat().st_size / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="scratch folder for the demo copy (will be created)")
    ap.add_argument("--out", default=str(HERE / "screenshots"))
    a = ap.parse_args()
    work, out = Path(a.work).resolve(), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    app = work / "Transcriber"

    say("1/6 copying the app and building the demo library (narrated lessons)…")
    import imageio_ffmpeg
    cache = work / "videos_cache"                      # narrated videos are slow to make, so they are kept between runs
    demo_media.build_all(cache, work / "Voice Memos", work / "media_work", imageio_ffmpeg.get_ffmpeg_exe())
    copy_app(app)
    shutil.copytree(cache, app / "videos", symlinks=True)
    (app / "_demo_launch.py").write_text(LAUNCH % {"root": FAKE_ROOT, "orig": str(work / "Voice Memos"), "forig": FAKE_ORIG})

    say("2/6 starting the demo panel and Chrome…")
    env = {**os.environ, "TRANSCRIBER_PORT": str(PORT), "TRANSCRIBER_NO_BROWSER": "1"}
    srv = subprocess.Popen([sys.executable, "-u", "_demo_launch.py"], cwd=app, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    panel = Panel()
    for _ in range(40):
        try:
            panel.get("api/ping")
            break
        except OSError:
            time.sleep(0.5)
    else:
        srv.terminate()
        raise RuntimeError("the demo panel did not start (run _demo_launch.py in the demo folder to see why)")
    ch = cdp.Chrome(work / "chrome-profile")
    try:
        ch.viewport(1280, 900, 1)
        ch.goto(BASE)
        ch.js("sessionStorage.setItem('booted','1')")
        ch.goto(BASE + "#transcribe")
        time.sleep(2.5)

        say("3/6 before any work: the Transcribe selection list (desktop + phone)…")
        open_tab(ch, "transcribe", 2500)
        shot(ch, out, "transcribe-select")
        ch.viewport(375, 812, 2, True)
        time.sleep(1.2)
        open_tab(ch, "transcribe", 1500)
        shot(ch, out, "m-transcribe")
        ch.viewport(1280, 900, 1)
        time.sleep(1)

        say("4/6 transcribing for real, capturing the live progress…")
        open_tab(ch, "transcribe", 1000)
        jq(ch, "document.getElementById('go').click()")
        got = False
        for _ in range(120):
            st = ch.js("(typeof ST!=='undefined'&&ST&&ST.running&&ST.eta_batch!=null&&ST.current)?[ST.percent,ST.eta_batch]:null")
            if st and 20 <= st[0] <= 85:
                got = True
                break
            time.sleep(0.6)
        if got:
            shot(ch, out, "transcribe-running")
        wait_idle(panel)
        jq(ch, "treeDirty=true; await loadTree(true); await loadSources(); await sleep(800)")

        say("5/6 taking snapshots for real…")
        open_tab(ch, "snapshots", 2500)
        shot(ch, out, "snapshots-select")
        jq(ch, "document.getElementById('snap').click()")
        for _ in range(60):
            st = ch.js("(typeof ST!=='undefined'&&ST&&ST.running&&ST.current)?[ST.percent]:null")
            if st and st[0] >= 10:
                shot(ch, out, "snapshots-running")
                break
            time.sleep(0.4)
        wait_idle(panel)
        jq(ch, "treeDirty=true; await loadTree(true); await loadSources(); await sleep(1200)")

        say("6/6 browsing the results…")
        open_tab(ch, "sources", 2000)
        shot(ch, out, "sources")
        jq(ch, "setTab('files'); await sleep(2000); click('.tnode','Photography Basics'); await sleep(300); click('.tnode','01 - Light and Exposure'); await sleep(300); click('.tnode','The Exposure Triangle'); await sleep(1500);")
        jq(ch, "const q=document.getElementById('vq'); q.value='as you can see'; q.dispatchEvent(new Event('input')); await sleep(600); window.scrollTo(0,0);")
        shot(ch, out, "files-transcript")
        jq(ch, "click('[data-vt=\"ts\"]'); await sleep(1200); const v=document.querySelector('#vbody .ln.vis'); if(v) v.scrollIntoView({block:'center'}); window.scrollTo(0,0);")
        shot(ch, out, "files-timestamps")
        jq(ch, "click('[data-vt=\"snaps\"]'); await sleep(3000); window.scrollTo(0,0);")
        shot(ch, out, "files-gallery")
        jq(ch, "document.querySelectorAll('#grid figure')[7].click(); await sleep(1500);")
        shot(ch, out, "files-lightbox")
        jq(ch, "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})); await sleep(300);")

        # a sample set of AI notes, so the AI NOTES tab has something to show
        res = panel.post("api/findings/new", {"rel": "Photography Basics/01 - Light and Exposure/P01 - 01 - The Exposure Triangle"})
        notes = app / res["path"]
        snap_dir = app / "snapshots-combined/Photography Basics/01 - Light and Exposure/P01 - 01 - The Exposure Triangle"
        vis = sorted(p.name for p in snap_dir.glob("*_VISUAL.jpg"))
        img_a, img_b = (vis[0], vis[min(5, len(vis) - 1)]) if vis else ("00-00-20_VISUAL.jpg", "00-00-30_VISUAL.jpg")
        txt = notes.read_text(encoding="utf-8")
        txt = txt.replace("status: not-started", "status: done").replace("<!-- 3-5 lines: what this lesson teaches -->",
            "The exposure triangle is aperture, shutter speed and ISO. Together they decide how bright a photo is; changing one means rebalancing the others.")
        txt = txt.replace("<!-- one bullet each; end with the source, e.g. [00:04:37] or image 00-04-37.jpg -->",
            f"- Wide aperture = more light but shallower depth of field (blurred background). [00:00:21] image {img_a}\n"
            "- Fast shutter freezes motion, slow shutter blurs it. [00:00:38]\n"
            "- Higher ISO brightens the picture but adds noise; keep it as low as the light allows. [00:00:48]")
        txt = txt.replace("<!-- images you actually looked at: file name and what it shows -->",
            f"- {img_a}: four aperture openings (f/1.8 to f/16) and the soft vs sharp background.\n- {img_b}: shutter speed examples with the ball's motion trail.")
        txt = txt.replace("## Still to check / open questions", "## Still to check / open questions\n- Does the lesson say how ISO interacts with exposure compensation? Not covered here.")
        notes.write_text(txt, encoding="utf-8")
        jq(ch, "TREEVER++; await loadTree(true); await sleep(800); click('.tnode','The Exposure Triangle'); await sleep(800); click('[data-vt=\"findings\"]'); await sleep(1200); window.scrollTo(0,0);")
        shot(ch, out, "files-ai-notes")

        open_tab(ch, "ai", 2200)
        jq(ch, "const set=(id,v)=>{const s=document.getElementById(id); s.value=v; s.dispatchEvent(new Event('change',{bubbles:true}));};"
               "set('aiCourse','Photography Basics'); await sleep(700); set('aiModule','01 - Light and Exposure'); await sleep(700);"
               "const g=document.getElementById('aiGoal'); g.value='Learn the exposure triangle and check my understanding against the slides'; g.dispatchEvent(new Event('input')); await sleep(1500); window.scrollTo(0,0);")
        shot(ch, out, "ai-prompt")

        jq(ch, "setTab('files'); await sleep(1200); click('.tnode','The Exposure Triangle'); await sleep(900); click('[data-vt=\"txt\"]'); await sleep(500); document.getElementById('vDelete').click(); await sleep(1500);")
        shot(ch, out, "files-delete")
        jq(ch, "document.getElementById('dCancel').click(); await sleep(300);")

        say("phone screenshots…")
        ch.viewport(375, 812, 2, True)
        time.sleep(1.2)
        jq(ch, "setTab('files'); await sleep(1200); click('.tnode','The Exposure Triangle'); await sleep(1200);"
               "const q=document.getElementById('vq'); if(q){q.value='as you can see'; q.dispatchEvent(new Event('input'));} await sleep(600); window.scrollTo(0,0);")
        shot(ch, out, "m-files")
        jq(ch, "click('[data-vt=\"snaps\"]'); await sleep(2800); window.scrollTo(0, document.querySelector('.sets').getBoundingClientRect().top+scrollY-110);")
        shot(ch, out, "m-gallery")
        open_tab(ch, "ai", 2200)
        jq(ch, "window.scrollTo(0, document.getElementById('aiPrompt').getBoundingClientRect().top+scrollY-120);")
        shot(ch, out, "m-ai")
    finally:
        try:
            ch.close()
        finally:
            try:
                panel.post("api/quit")
            except Exception:
                pass
            srv.terminate()

    say("building the animated tour…")
    build_gif(out, TOUR)
    tidy(out)
    say("done: " + str(out))


if __name__ == "__main__":
    main()
