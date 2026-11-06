#!/usr/bin/env python3
"""Draws the Transcriber icon (waveform + caption lines) -> icon-1024.png, icon-256.png, icon.svg, Transcriber.icns.
Run:  ~/.transcriber/venv/bin/python assets/make_icon.py   (needs numpy, which faster-whisper installs)"""
import struct, subprocess, zlib, shutil
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
N = 1024
BARS = [110, 210, 330, 250, 410, 290, 340, 200, 110]          # waveform bar heights
BAR_W, GAP, WAVE_CY = 40, 30, 410
LINES = [(380, 665), (250, 755)]                              # (width, y) caption lines
TOP, BOT = (0x3f, 0x8c, 0x66), (0x1c, 0x45, 0x31)             # gradient green


def rrect(x, y, cx, cy, w, h, r):
    """signed distance to a rounded rect centred (cx, cy), size w x h, corner radius r"""
    qx, qy = np.abs(x - cx) - (w / 2 - r), np.abs(y - cy) - (h / 2 - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def cover(sd):                                                # anti-aliased coverage from distance
    return np.clip(0.5 - sd, 0, 1)


def render():
    y, x = np.mgrid[0:N, 0:N].astype(np.float64) + 0.5
    rgba = np.zeros((N, N, 4))
    body = rrect(x, y, N / 2, N / 2, 824, 824, 186)
    # soft shadow
    sh = rrect(x, y, N / 2, N / 2 + 14, 824, 824, 186)
    shadow = np.exp(-np.maximum(sh, 0) / 22) * 0.25 * (1 - cover(body))
    rgba[..., 3] = shadow
    # gradient body
    t = np.clip((y - 100) / 824, 0, 1)[..., None]
    col = np.array(TOP) * (1 - t) + np.array(BOT) * t
    a = cover(body)[..., None]
    rgba[..., :3] = col * a / 255
    rgba[..., 3] = np.maximum(rgba[..., 3], a[..., 0])
    rgba[..., :3] = np.where(a > 0, rgba[..., :3], 0)
    # top sheen
    sheen = np.clip(1 - (y - 100) / 300, 0, 1) * 0.10 * cover(body)
    rgba[..., :3] += sheen[..., None]

    def paint(sd, alpha=1.0):
        c = (cover(sd) * alpha)[..., None]
        rgba[..., :3] = rgba[..., :3] * (1 - c) + c
        rgba[..., 3] = np.maximum(rgba[..., 3], c[..., 0])

    total = len(BARS) * BAR_W + (len(BARS) - 1) * GAP
    x0 = N / 2 - total / 2 + BAR_W / 2
    for i, h in enumerate(BARS):
        paint(rrect(x, y, x0 + i * (BAR_W + GAP), WAVE_CY, BAR_W, h, BAR_W / 2))
    for w, yy in LINES:
        paint(rrect(x, y, N / 2, yy, w, 40, 20), 0.88)
    return (np.clip(rgba, 0, 1) * 255).astype(np.uint8)


def write_png(path, arr):
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[i].tobytes() for i in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def svg():
    total = len(BARS) * BAR_W + (len(BARS) - 1) * GAP
    x0 = N / 2 - total / 2
    bars = "".join(f'<rect x="{x0 + i * (BAR_W + GAP)}" y="{WAVE_CY - h / 2}" width="{BAR_W}" height="{h}" rx="{BAR_W / 2}"/>'
                   for i, h in enumerate(BARS))
    lines = "".join(f'<rect x="{N / 2 - w / 2}" y="{yy - 20}" width="{w}" height="40" rx="20" opacity=".88"/>' for w, yy in LINES)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="100 100 824 824"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="#3f8c66"/><stop offset="1" stop-color="#1c4531"/></linearGradient></defs>'
            f'<rect x="100" y="100" width="824" height="824" rx="186" fill="url(#g)"/><g fill="#fff">{bars}{lines}</g></svg>')


if __name__ == "__main__":
    big = render()
    write_png(HERE / "icon-1024.png", big)
    (HERE / "icon.svg").write_text(svg())
    # favicon / small sizes via macOS sips
    iconset = HERE / "Transcriber.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()
    for s in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = s * scale
            out = iconset / (f"icon_{s}x{s}.png" if scale == 1 else f"icon_{s}x{s}@2x.png")
            subprocess.run(["sips", "-z", str(px), str(px), str(HERE / "icon-1024.png"), "--out", str(out)],
                           check=True, capture_output=True)
    subprocess.run(["sips", "-z", "128", "128", str(HERE / "icon-1024.png"), "--out", str(HERE / "favicon.png")],
                   check=True, capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "Transcriber.icns")], check=True)
    shutil.rmtree(iconset)
    print("icons written to", HERE)
