"""
Builds a small demo library with ORIGINAL content (so the README screenshots show nothing private or copyrighted):
narrated lessons made from slides drawn with Pillow and speech from the macOS `say` command, muxed with ffmpeg.

Used by make_screenshots.py. macOS only (needs `say`). Needs Pillow, numpy and imageio-ffmpeg (for ffmpeg).
"""
import random
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
INK, MUTED, ACCENT, ACCENT2, PAPER = (30, 41, 59), (100, 116, 139), (234, 88, 12), (13, 148, 136), (250, 248, 243)
FONT = "/System/Library/Fonts/Helvetica.ttc"
VOICE = "Samantha"


def font(size, bold=False):
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def base(title, sub=None):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 10], fill=ACCENT)
    d.text((70, 48), title, font=font(54, True), fill=INK)
    if sub:
        d.text((72, 118), sub, font=font(28), fill=MUTED)
    return im, d


def centered(d, text, y, size, fill=INK, bold=False, cx=W // 2):
    f = font(size, bold)
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)


# ------------------------------------------------------------------ slides
def s_title(title, sub=""):
    im, d = base("")
    for i, r in enumerate((300, 220, 140)):
        d.ellipse([W - 190 - r // 2, 250 - r // 2 + 60, W - 190 + r // 2, 250 + r // 2 + 60], outline=ACCENT if i == 2 else (226, 232, 240), width=6)
    d.text((90, 250), title, font=font(78, True), fill=INK)
    d.text((94, 360), sub, font=font(34), fill=MUTED)
    return im


def s_triangle():
    im, d = base("The exposure triangle", "three settings share one job: how bright is the photo?")
    top, bl, br = (W // 2 - 80, 260), (W // 2 - 340, 600), (W // 2 + 180, 600)
    d.polygon([top, bl, br], outline=INK, width=8)
    for (x, y), label, col in ((top, "APERTURE", ACCENT), (bl, "SHUTTER SPEED", ACCENT2), (br, "ISO", (79, 70, 229))):
        d.ellipse([x - 26, y - 26, x + 26, y + 26], fill=col)
    centered(d, "APERTURE", 200, 34, ACCENT, True, top[0])
    centered(d, "SHUTTER SPEED", 640, 34, ACCENT2, True, bl[0])
    centered(d, "ISO", 640, 34, (79, 70, 229), True, br[0])
    d.text((br[0] + 150, 330), "change one,\nbalance the\nothers", font=font(34), fill=MUTED, spacing=10)
    return im


def s_aperture():
    im, d = base("Aperture", "the size of the lens opening")
    for i, (f, r) in enumerate((("f/1.8", 78), ("f/4", 58), ("f/8", 38), ("f/16", 20))):
        cx = 200 + i * 230
        d.ellipse([cx - 90, 250 - 90, cx + 90, 250 + 90], fill=INK)
        d.ellipse([cx - r, 250 - r, cx + r, 250 + r], fill=(255, 250, 235))
        centered(d, f, 360, 34, INK, True, cx)
    bg = Image.new("RGB", (480, 150), (226, 232, 240))
    bd = ImageDraw.Draw(bg)
    for x in range(0, 480, 40):
        bd.rectangle([x, 0, x + 18, 150], fill=(148, 163, 184))
    blurred = bg.filter(ImageFilter.GaussianBlur(9))
    im.paste(blurred, (110, 470))
    im.paste(bg, (690, 470))
    d.ellipse([320, 520, 380, 580], fill=ACCENT)
    d.ellipse([900, 520, 960, 580], fill=ACCENT)
    centered(d, "wide opening: soft background", 640, 28, MUTED, cx=350)
    centered(d, "small opening: everything sharp", 640, 28, MUTED, cx=930)
    return im


def s_shutter():
    im, d = base("Shutter speed", "how long the sensor sees the scene")
    rows = (("1/1000 s", 1), ("1/60 s", 5), ("1/4 s", 14))
    for i, (label, trail) in enumerate(rows):
        y = 260 + i * 150
        d.text((80, y - 20), label, font=font(36, True), fill=INK)
        d.line([330, y, 1150, y], fill=(203, 213, 225), width=3)
        for t in range(trail):                      # a longer exposure leaves a fading smear behind the ball
            x = 700 + t * 18
            f = t / (trail + 1)
            d.ellipse([x - 30, y - 30, x + 30, y + 30], fill=tuple(int(ACCENT[k] + (PAPER[k] - ACCENT[k]) * f * 0.8) for k in range(3)))
        d.ellipse([700 - 30, y - 30, 700 + 30, y + 30], fill=ACCENT)
    centered(d, "fast = frozen    slow = motion blur", 665, 30, MUTED)
    return im


def s_iso():
    im, d = base("ISO", "brightness from the sensor, at the cost of noise")
    rng = np.random.default_rng(7)
    for i, (label, amp) in enumerate((("ISO 100", 4), ("ISO 800", 22), ("ISO 6400", 60))):
        grad = np.tile(np.linspace(70, 190, 330), (330, 1))
        arr = np.clip(grad[..., None] + rng.normal(0, amp, (330, 330, 1)), 0, 255).repeat(3, axis=2).astype("uint8")
        x = 110 + i * 380
        im.paste(Image.fromarray(arr), (x, 200))
        centered(d, label, 560, 36, INK, True, x + 165)
    centered(d, "keep it as low as the light allows", 650, 30, MUTED)
    return im


def hist(title, sub, pattern):
    im, d = base(title, sub)
    x0, y0, w, h = 160, 190, 960, 380
    d.rectangle([x0, y0, x0 + w, y0 + h], outline=(203, 213, 225), width=3)
    xs = np.linspace(0, 1, 64)
    if pattern == "dark":
        v = np.exp(-((xs - 0.14) ** 2) / 0.012) + 0.08
    elif pattern == "bright":
        v = np.exp(-((xs - 0.86) ** 2) / 0.012) + 0.08
    else:
        v = np.exp(-((xs - 0.5) ** 2) / 0.07) + 0.15 * np.exp(-((xs - 0.2) ** 2) / 0.02)
    v = v / v.max()
    for i, val in enumerate(v):
        bx = x0 + 8 + i * (w - 16) / 64
        d.rectangle([bx, y0 + h - val * (h - 20), bx + (w - 16) / 64 - 3, y0 + h - 4], fill=ACCENT2 if pattern == "balanced" else ACCENT)
    for i in range(64):
        g = int(255 * i / 63)
        d.rectangle([x0 + 8 + i * (w - 16) / 64, y0 + h + 24, x0 + 8 + (i + 1) * (w - 16) / 64, y0 + h + 60], fill=(g, g, g))
    d.text((x0, y0 + h + 70), "shadows", font=font(26), fill=MUTED)
    centered(d, "midtones", y0 + h + 70, 26, MUTED, cx=x0 + w // 2)
    d.text((x0 + w - 120, y0 + h + 70), "highlights", font=font(26), fill=MUTED)
    return im


def landscape(d_im, box, tree_x):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    sky = Image.new("RGB", (w, h))
    sd = ImageDraw.Draw(sky)
    for y in range(h):
        t = y / h
        sd.line([0, y, w, y], fill=(int(120 + 110 * t), int(170 + 70 * t), int(230 - 20 * t)))
    sd.ellipse([w * 0.72 - 45, h * 0.18 - 45, w * 0.72 + 45, h * 0.18 + 45], fill=(255, 226, 140))
    sd.polygon([(0, h * 0.66), (w * 0.3, h * 0.5), (w * 0.6, h * 0.68), (w, h * 0.55), (w, h), (0, h)], fill=(34, 110, 80))
    tx = int(w * tree_x)
    sd.rectangle([tx - 7, h * 0.46, tx + 7, h * 0.74], fill=(90, 60, 40))
    sd.ellipse([tx - 50, h * 0.26, tx + 50, h * 0.55], fill=(20, 84, 60))
    d_im.paste(sky, (x0, y0))


def s_thirds(tree_x, grid=True, caption=""):
    im, d = base("Rule of thirds", "place the subject on a line, not in the middle")
    box = (140, 190, 1140, 640)
    landscape(im, box, tree_x)
    if grid:
        x0, y0, x1, y1 = box
        for k in (1, 2):
            d.line([x0 + (x1 - x0) * k / 3, y0, x0 + (x1 - x0) * k / 3, y1], fill=(255, 255, 255), width=4)
            d.line([x0, y0 + (y1 - y0) * k / 3, x1, y0 + (y1 - y0) * k / 3], fill=(255, 255, 255), width=4)
        for kx in (1, 2):
            for ky in (1, 2):
                cx, cy = x0 + (x1 - x0) * kx / 3, y0 + (y1 - y0) * ky / 3
                d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=ACCENT, width=6)
    if caption:
        centered(d, caption, 660, 30, MUTED)
    return im


def s_leading():
    im, d = base("Leading lines", "let the scene point at your subject")
    box = (140, 190, 1140, 640)
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=(203, 213, 225))
    vp = (x0 + 640, y0 + 170)
    d.ellipse([vp[0] - 48, vp[1] - 48, vp[0] + 48, vp[1] + 48], fill=(255, 226, 140))
    d.polygon([vp, (x0 + 120, y1), (x1 - 80, y1)], fill=(71, 85, 105))
    for t in range(1, 7):
        f = t / 7
        yy = vp[1] + (y1 - vp[1]) * f * f
        w = 5 + 26 * f * f
        d.rectangle([vp[0] - w / 2, yy, vp[0] + w / 2, yy + 22 * f + 6], fill=(250, 204, 21))
    d.line([(x0 + 120, y1), vp], fill=ACCENT, width=6)
    d.line([(x1 - 80, y1), vp], fill=ACCENT, width=6)
    return im


def s_grind():
    im, d = base("Grind size", "finer grounds slow the water down")
    rng = random.Random(3)
    for i, (label, r, n) in enumerate((("COARSE", 15, 70), ("MEDIUM", 8, 220), ("FINE", 4, 700))):
        cx = 230 + i * 410
        d.ellipse([cx - 150, 260, cx + 150, 560], fill=(241, 235, 224), outline=INK, width=5)
        for _ in range(n):
            a, rad = rng.random() * 6.283, 130 * rng.random() ** 0.5
            x, y = cx + rad * np.cos(a), 410 + rad * np.sin(a)
            d.ellipse([x - r / 2, y - r / 2, x + r / 2, y + r / 2], fill=(92 - rng.randint(0, 25), 60, 40))
        centered(d, label, 590, 36, INK, True, cx)
    return im


def s_shots():
    im, d = base("Dialing in shots", "time the pour, then taste")
    x0, y0, base_y = 150, 200, 580
    d.line([x0, base_y, 1130, base_y], fill=INK, width=4)
    d.rectangle([x0, base_y - 190, 1130, base_y - 105], fill=(209, 250, 229))
    d.text((x0 + 800, base_y - 188), "target 25-30 s", font=font(26, True), fill=ACCENT2)
    for i, (label, secs, col) in enumerate((("sour", 14, (250, 204, 21)), ("balanced", 28, ACCENT2), ("bitter", 44, ACCENT))):
        bx = 260 + i * 290
        d.rectangle([bx, base_y - secs * 8, bx + 190, base_y], fill=col)
        centered(d, f"{secs} s", base_y - secs * 8 - 44, 34, INK, True, bx + 95)
        centered(d, label, base_y + 14, 32, INK, False, bx + 95)
    return im


def s_tips():
    im, d = base("5 tips for sharper photos")
    for i, t in enumerate(("Hold still: elbows tucked in", "Use a faster shutter than you think", "Focus on the eye, then recompose",
                           "Clean the lens first", "Shoot a burst, keep the best frame")):
        y = 190 + i * 100
        d.ellipse([90, y, 150, y + 60], fill=ACCENT)
        centered(d, str(i + 1), y + 8, 36, (255, 255, 255), True, 120)
        d.text((190, y + 6), t, font=font(42), fill=INK)
    return im


def s_end(next_up):
    im, d = base("")
    centered(d, "That's the lesson", 270, 70, INK, True)
    centered(d, next_up, 380, 36, MUTED)
    return im


SLIDES = {
    "triangle": s_triangle, "aperture": s_aperture, "shutter": s_shutter, "iso": s_iso,
    "hist_balanced": lambda: hist("Reading a histogram", "how many pixels are dark, medium or bright", "balanced"),
    "hist_dark": lambda: hist("Underexposed", "the graph piles up on the left", "dark"),
    "hist_bright": lambda: hist("Overexposed", "the graph piles up on the right", "bright"),
    "thirds_grid": lambda: s_thirds(0.5, True, "centered subject: calm, but static"),
    "thirds_on": lambda: s_thirds(1 / 3, True, "on a third: balanced and alive"),
    "leading": s_leading, "grind": s_grind, "shots": s_shots, "tips": s_tips,
}

# ----------------------------------------------------------------- lessons
# (course, module, lesson file name, [(slide key or ("title", t, sub) or ("end", text), narration)])
LESSONS = [
    ("Photography Basics", "01 - Light and Exposure", "P01 - 01 - The Exposure Triangle", [
        (("title", "The exposure triangle", "Photography Basics, lesson 1"), "Welcome. In this lesson we look at the exposure triangle, the three settings that decide how bright your photo turns out."),
        ("triangle", "Here we have the triangle on the screen. Aperture, shutter speed and ISO sit at the three corners. Change one of them and you have to balance it with the others."),
        ("aperture", "Let me show you aperture first. As you can see, a wide opening lets in more light but gives a shallow depth of field. This area right here is the soft blurred background."),
        ("shutter", "Now look at this line of motion. Shutter speed is how long the sensor sees the scene. A fast speed freezes the movement, a slow speed blurs it."),
        ("iso", "Finally ISO. Raising it brightens the picture but adds noise, as you can see in this one over here. Keep it as low as the light allows."),
        (("end", "Next: reading a histogram"), "That is the exposure triangle. In the next lesson we will learn to read the histogram."),
    ]),
    ("Photography Basics", "01 - Light and Exposure", "P01 - 02 - Reading a Histogram", [
        (("title", "Reading a histogram", "Photography Basics, lesson 2"), "A histogram is a quick check on your exposure. Let's see how to read one."),
        ("hist_balanced", "Here we have a balanced histogram. This line of bars shows how many pixels are dark, medium or bright, from the shadows on the left to the highlights on the right."),
        ("hist_dark", "If the graph is piled up on the left, as you can see right here, the photo is underexposed and the shadows are crushed."),
        ("hist_bright", "Look at this one. When the bars pile up on the right the photo is overexposed. This area at the edge means clipped highlights that you cannot recover."),
        (("end", "Next: the rule of thirds"), "Check the histogram after every few shots and you will catch exposure problems early."),
    ]),
    ("Photography Basics", "02 - Composition", "P02 - 01 - Rule of Thirds", [
        (("title", "The rule of thirds", "Photography Basics, lesson 3"), "Composition is how you arrange things inside the frame. The simplest tool is the rule of thirds."),
        ("thirds_grid", "On the screen you can see the frame split into nine parts by two vertical and two horizontal lines. Here the tree sits in the middle, which feels calm but a little static."),
        ("thirds_on", "Now look at this version. The tree has moved to this line on the left, right at an intersection. The picture feels more balanced and there is room for the eye to travel."),
        (("end", "Next: leading lines"), "Most cameras can show this grid on the screen. Turn it on and practise."),
    ]),
    ("Photography Basics", "02 - Composition", "P02 - 02 - Leading Lines", [
        (("title", "Leading lines", "Photography Basics, lesson 4"), "Lines in a scene can guide the viewer straight to your subject."),
        ("leading", "Here we have a road. Follow this line from the bottom of the frame, and this one on the other side. Both lines meet at the sun, right here, so your eye lands exactly where you want it."),
        (("end", "Photography Basics complete"), "Look for roads, fences, rivers and shadows. They all work the same way."),
    ]),
    ("Home Espresso", "01 - Dialing In", "E01 - 01 - Grind Size", [
        (("title", "Grind size", "Home Espresso, lesson 1"), "Grind size is the biggest lever you have for the taste of an espresso."),
        ("grind", "Let me show you three bowls on the screen. This one is coarse, this one is medium and this one over here is fine. Finer grounds slow the water down and extract more."),
        (("end", "Next: dialing in shots"), "Change the grind one small step at a time, and only change one thing per shot."),
    ]),
    ("Home Espresso", "01 - Dialing In", "E01 - 02 - Dialing In Shots", [
        (("title", "Dialing in shots", "Home Espresso, lesson 2"), "Now that you know the grind, let's dial in a shot by time and by taste."),
        ("shots", "Here we have a chart of three shots. As you can see, the fourteen second shot is sour, this one at twenty eight seconds is balanced, and this level at forty four seconds tastes bitter. Aim for the green band."),
        (("end", "Home Espresso complete"), "If the shot runs fast, grind finer. If it crawls, grind coarser."),
    ]),
]
WEB_LESSON = ("Demo Channel", None, "5 Tips for Sharper Photos", [
    (("title", "5 tips for sharper photos", "Demo Channel"), "Blurry photos are usually fixable. Here are five quick tips."),
    ("tips", "Look at this list on the screen. Tip one, hold still with your elbows tucked in. Tip two, use a faster shutter speed than you think you need. Tip three, focus on the eye and then recompose."),
    (("end", "Thanks for watching"), "Tip four, clean the lens. Tip five, shoot a burst and keep the best frame."),
])
VOICE_NOTE = "Quick note to myself. Re-watch the lesson on leading lines, and try the rule of thirds on tomorrow's walk."


# ---------------------------------------------------------------- building
def run(cmd, **kw):
    subprocess.run(cmd, check=True, capture_output=True, **kw)


def wav_len(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def speak(text, out_wav):
    aiff = out_wav.with_suffix(".aiff")
    run(["say", "-v", VOICE, "-r", "165", "-o", str(aiff), text])
    return aiff


def build_video(ffmpeg, parts, out_mp4, work):
    work.mkdir(parents=True, exist_ok=True)
    wavs, pngs, durs = [], [], []
    for i, (slide, text) in enumerate(parts):
        if isinstance(slide, tuple):
            img = s_title(slide[1], slide[2]) if slide[0] == "title" else s_end(slide[1])
        else:
            img = SLIDES[slide]()
        png = work / f"s{i}.png"
        img.save(png)
        wav = work / f"n{i}.wav"
        aiff = speak(text, wav)
        run([ffmpeg, "-y", "-i", str(aiff), "-ar", "44100", "-ac", "1", str(wav)])
        pngs.append(png)
        wavs.append(wav)
        durs.append(wav_len(wav) + (1.0 if i == len(parts) - 1 else 0.5))
    # narration track: each paragraph followed by a short pause
    with wave.open(str(work / "narration.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(44100)
        for wv, d in zip(wavs, durs):
            with wave.open(str(wv)) as r:
                out.writeframes(r.readframes(r.getnframes()))
            pause = d - wav_len(wv)
            out.writeframes(b"\x00\x00" * int(44100 * pause))
    lines = []
    for png, d in zip(pngs, durs):
        lines += [f"file '{png}'", f"duration {d:.3f}"]
    lines.append(f"file '{pngs[-1]}'")
    (work / "list.txt").write_text("\n".join(lines) + "\n")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-i", str(work / "narration.wav"),
         "-vf", "fps=10,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "80k",
         "-shortest", str(out_mp4)])


def build_all(videos_dir: Path, originals_dir: Path, work: Path, ffmpeg: str):
    """Creates videos/<course>/<module>/<lesson>.mp4, videos/Web videos/<channel>/<title>.mp4 and a voice note under originals/."""
    for course, module, name, parts in LESSONS:
        out = videos_dir / course / module / f"{name}.mp4"
        if not out.exists():
            print("  building", name, flush=True)
            build_video(ffmpeg, parts, out, work / name)
    channel, _, title, parts = WEB_LESSON
    out = videos_dir / "Web videos" / channel / f"{title}.mp4"
    if not out.exists():
        print("  building", title, flush=True)
        build_video(ffmpeg, parts, out, work / title)
    originals_dir.mkdir(parents=True, exist_ok=True)
    note = originals_dir / "Voice note.ogg"
    if not note.exists():
        aiff = speak(VOICE_NOTE, work / "voice.wav")
        run([ffmpeg, "-y", "-i", str(aiff), "-ar", "48000", "-ac", "1", "-c:a", "libopus", "-b:a", "24k", str(note)])
    link_dir = videos_dir / "Single files"
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "Voice note.ogg"
    if not link.exists():
        link.symlink_to(note)
