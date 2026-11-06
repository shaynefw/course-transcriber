#!/usr/bin/env python3
"""
Video snapshotter: saves compressed screenshots of each lesson while someone is talking,
skipping frames that look the same as the last saved one, and always grabbing a frame at
every [VISUAL] cue found by the transcriber.

Reads ./videos (same layout as the transcriber), writes ./snapshots/<same path>/<lesson>/:
    00-12-05.jpg            a snapshot at 00:12:05
    00-12-40_VISUAL.jpg     a snapshot at a spot the speaker was pointing at something
    _snapshots.txt          each file with the transcript line being spoken at that moment

Usage:
    python3 snapshots.py                  # all videos without snapshots yet
    python3 snapshots.py --interval 10    # look every 10 s instead of 5
    python3 snapshots.py --change 0.2     # more sensitive (keeps smaller on-screen changes)
    python3 snapshots.py --visual-only    # 1-second bursts only around [VISUAL] lines -> snapshots-visual/
    python3 snapshots.py --visual-only --burst 10 --change 0   # 10 s bursts, save every look (no skipping)
    python3 snapshots.py --combined --burst 10   # background frames + 1 s bursts around cues -> snapshots-combined/
    python3 snapshots.py --redo           # redo lessons that already have snapshots

A lesson is "done" once its folder has .done.json, so re-running is safe/resumable.
"""
import argparse
import bisect
import json
import re
import shutil
import sys
import time
from pathlib import Path

import transcribe as T

# ---------------------------------------------------------------------------
# EDIT ME: defaults
# ---------------------------------------------------------------------------
INTERVAL = 5.0        # seconds between looks
CHANGE_PCT = 1.0      # save only if at least this % of the picture changed since the last saved shot
PIXEL_DELTA = 24      # (0-255) how different a pixel must be to count as "changed"
JPEG_QUALITY = 78     # 1-95; ~75-80 is small and still sharp enough to read chart labels
MAX_WIDTH = 1280      # downscale wider frames to this (keeps text readable, files small)
SPEECH_PAD = 1.0      # seconds of padding around each spoken stretch
SPAN_CAP = 10.0       # when an old transcript has no end times, assume a line lasts at most this long
CUE_DELAY = 1.0       # grab the cue frame this long after the speaker starts the sentence
# "visuals only" mode: a 1-second burst around every [VISUAL] line (windows that overlap are merged)
VISUAL_BEFORE = 1.0   # start this many seconds before the cue line
VISUAL_AFTER = 6.0    # ...and keep going this many seconds after it starts (--burst overrides)
VISUAL_STEP = 1.0     # seconds between frames inside a window
VISUAL_CHANGE_PCT = 1.0   # same as normal; lower it (e.g. 0.3) to keep small drawings but expect ~2x the images
# ---------------------------------------------------------------------------

SNAP_DIR = T.BASE / "snapshots"                  # everything-while-talking mode
VIS_DIR = T.BASE / "snapshots-visual"            # visuals-only mode (kept separate so the two never overwrite each other)


COMBO_DIR = T.BASE / "snapshots-combined"        # visual bursts + background frames (safety net)
ROOTS = {"all": SNAP_DIR, "visual": VIS_DIR, "combined": COMBO_DIR}


def snap_folder(rel: Path, mode: str = "all") -> Path:
    return ROOTS[mode] / rel.with_suffix("")


def is_done(rel: Path, mode: str = "all") -> bool:
    return (snap_folder(rel, mode) / ".done.json").exists()


def hhmmss_to_s(h, m, s) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def load_transcript(rel: Path):
    """-> (lines [(start_s, text, is_visual)], meta dict). Missing files give ([], {})."""
    paths = T.out_paths(rel)
    lines = []
    if paths["ts"].exists():
        for raw in paths["ts"].read_text(encoding="utf-8").splitlines():
            m = T.TS_RE.match(raw)
            if m:
                lines.append((hhmmss_to_s(m[1], m[2], m[3]), m[4], raw.startswith("[VISUAL]")))
    meta = {}
    try:
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    except Exception:
        pass
    return lines, meta


def merge(spans, gap=0.0):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def speech_spans(video: Path, lines, meta, duration):
    """Where someone is talking: exact spans if the transcriber saved them, else estimate from the
    transcript, else run voice detection on the audio."""
    if meta.get("spans"):
        raw, how = [(a, b) for a, b in meta["spans"]], "transcript"
    elif lines:
        starts = [l[0] for l in lines]
        raw = [(s, min(starts[i + 1] if i + 1 < len(starts) else s + SPAN_CAP, s + SPAN_CAP))
               for i, s in enumerate(starts)]
        how = "transcript (estimated)"
    else:
        from faster_whisper import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        audio = decode_audio(str(video), sampling_rate=16000)
        raw = [(c["start"] / 16000, c["end"] / 16000) for c in get_speech_timestamps(audio, VadOptions())]
        how = "voice detection (no transcript yet)"
    return merge([(max(0, a - SPEECH_PAD), min(duration, b + SPEECH_PAD)) for a, b in raw]), how


def plan_times(duration, spans, cues, interval, speech_only):
    """-> sorted [(time_s, is_cue)]"""
    times = {}
    t = 0.0
    starts = [a for a, _ in spans]
    while t < duration:
        if not speech_only:
            inside = True
        else:
            i = bisect.bisect_right(starts, t) - 1
            inside = i >= 0 and t <= spans[i][1]
        if inside:
            times[round(t, 1)] = False
        t += interval
    for c in cues:
        c = min(c + CUE_DELAY, max(duration - 0.5, 0))
        near = [k for k in times if abs(k - c) < interval / 2]
        if near:
            times[min(near, key=lambda k: abs(k - c))] = True      # a regular look is close enough
        else:
            times[round(c, 1)] = True
    return sorted(times.items())


def plan_visual(duration, cues, step, after):
    """Windows around each [VISUAL] line (cue start - VISUAL_BEFORE .. cue start + after), merged,
    sampled every `step` seconds."""
    wins = merge([(max(0.0, c - VISUAL_BEFORE), min(duration, c + after)) for c in cues])
    times = []
    for a, b in wins:
        t = a
        while t <= b and t < duration:
            times.append((round(t, 1), False))
            t += step
    return times, len(wins)


def plan_combined(duration, spans, cues, interval, after):
    """Background looks every `interval` s while talking + a full 1-second burst after each cue.
    Burst looks are flagged True (always saved, named _VISUAL); background looks are False (change-filtered)."""
    times = {t: False for t, _ in plan_times(duration, spans, [], interval, True)}
    burst, n_win = plan_visual(duration, cues, VISUAL_STEP, after)
    for t, _ in burst:
        times[t] = True
    return sorted(times.items()), n_win


def estimate_looks(video: Path, mode, interval, burst, speech_only) -> float:
    """How many looks this lesson will take (the unit of work for the time estimates)."""
    rel = video.relative_to(T.IN_DIR)
    lines, meta = load_transcript(rel)
    duration = T.video_seconds(video) or float(meta.get("duration") or 0)
    cues = [l[0] for l in lines if l[2]]
    if mode == "visual":
        return float(len(plan_visual(duration, cues, interval, burst if burst else VISUAL_AFTER)[0])) if lines else 0.0
    if not lines and not meta.get("spans"):
        return duration / interval            # would need voice detection; just estimate
    spans = speech_spans(video, lines, meta, duration)[0] if speech_only else [[0, duration]]
    if mode == "combined":
        return float(len(plan_combined(duration, spans, cues, interval, burst if burst else VISUAL_AFTER)[0]))
    return float(len(plan_times(duration, spans, cues, interval, speech_only)))


def grab_frame(container, stream, t):
    """Decode the first frame at or after time t (seconds); None if past the end."""
    container.seek(int(t / stream.time_base), stream=stream, backward=True, any_frame=False)
    for frame in container.decode(stream):
        if frame.time is not None and frame.time >= t - 0.02:
            return frame
    return None


def snapshot_one(video: Path, interval, change_pct, quality, speech_only, mode="all", burst=None):
    import av
    import numpy as np

    rel = video.relative_to(T.IN_DIR)
    print(f"\n>> {rel}", flush=True)
    start = time.time()
    lines, meta = load_transcript(rel)
    visual_only = mode == "visual"
    if visual_only and not lines:
        print("   needs a transcript first (visuals-only mode uses the [VISUAL] lines); skipping", flush=True)
        return
    folder = snap_folder(rel, mode)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    with av.open(str(video)) as container:
        if not container.streams.video:
            print("   no video track, skipping", flush=True)
            (folder / ".done.json").write_text(json.dumps({"count": 0, "note": "no video"}))
            return
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        duration = float(container.duration / 1_000_000) if container.duration else float(meta.get("duration") or 0)
        print(f"   length {T.stamp(duration)}", flush=True)

        cues = [l[0] for l in lines if l[2]]
        if visual_only:
            targets, n_win = plan_visual(duration, cues, interval, burst if burst else VISUAL_AFTER)
            print(f"   {len(targets)} looks (every {interval:g}s) in {n_win} visual moment(s) from {len(cues)} cue lines", flush=True)
        else:
            if speech_only:
                spans, how = speech_spans(video, lines, meta, duration)
            else:
                spans, how = [[0, duration]], "whole video"
            if mode == "combined":
                targets, n_win = plan_combined(duration, spans, cues, interval, burst if burst else VISUAL_AFTER)
                print(f"   {len(targets)} looks: every {interval:g}s while talking (speech from: {how}) + "
                      f"1s bursts in {n_win} visual moment(s) from {len(cues)} cue lines", flush=True)
            else:
                targets = plan_times(duration, spans, cues, interval, speech_only)
                print(f"   {len(targets)} looks (speech from: {how}), {len(cues)} visual cues", flush=True)
        if not lines:
            print("   tip: transcribe this lesson first to also catch the [VISUAL] moments", flush=True)

        starts = [l[0] for l in lines]
        saved, skipped = [], 0            # saved: [name, t, is_cue]
        last_thumb, last_pct = None, -1
        for n, (t, is_cue) in enumerate(targets):
            frame = grab_frame(container, stream, t)
            if frame is not None:
                thumb = frame.reformat(width=160, height=90, format="gray").to_ndarray().astype(np.int16)
                changed = 100.0 if last_thumb is None else float((np.abs(thumb - last_thumb) > PIXEL_DELTA).mean() * 100)
                if changed >= change_pct or (mode == "combined" and is_cue):
                    name = f"{T.stamp(t).replace(':', '-')}{'_VISUAL' if is_cue else ''}.jpg"
                    img = frame.to_image()
                    if img.width > MAX_WIDTH:
                        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)))
                    img.save(folder / name, "JPEG", quality=quality, optimize=True)
                    saved.append([name, t, is_cue])
                    last_thumb = thumb
                elif is_cue and saved and not saved[-1][2]:
                    # same picture as the last saved shot: mark that shot as the cue one instead of duplicating
                    old = saved[-1]
                    new = old[0].replace(".jpg", "_VISUAL.jpg")
                    (folder / old[0]).rename(folder / new)
                    saved[-1] = [new, old[1], True]
                    skipped += 1
                else:
                    skipped += 1
            T.progress_tick(video, (n + 1) / max(len(targets), 1))
            pct = int((n + 1) / max(len(targets), 1) * 100)
            if pct // 10 != last_pct // 10:
                last_pct = pct
                print(f"   {pct}%  ({int(time.time() - start)}s elapsed, {len(saved)} saved)", flush=True)

    # contents file: each picture next to what was being said
    out = ["# Snapshot -> what was being said (names are HH-MM-SS; _VISUAL = speaker was pointing at something)", ""]
    for name, t, is_cue in saved:
        i = bisect.bisect_right(starts, t) - 1
        said = f"[{T.stamp(lines[i][0])}] {lines[i][1]}" if i >= 0 else ""
        out.append(f"{name}   {said}")
    (folder / "_snapshots.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    size_mb = sum(p.stat().st_size for p in folder.glob("*.jpg")) / 1e6
    (folder / ".done.json").write_text(json.dumps(
        {"count": len(saved), "visual": sum(1 for s in saved if s[2]), "skipped_similar": skipped,
         "interval": interval, "change_pct": change_pct, "burst": burst,
         "mode": mode}))
    elapsed = max(time.time() - start, 0.001)
    tag = "" if visual_only else f" ({sum(1 for s in saved if s[2])} from visual bursts)" if mode == "combined" else f" ({sum(1 for s in saved if s[2])} visual)"
    print(f"   done in {int(elapsed)}s, {duration / elapsed:.0f}x realtime | {len(saved)} snapshots{tag}, "
          f"{skipped} skipped as unchanged, {size_mb:.1f} MB", flush=True)


def log_failure(video: Path, err: Exception, mode: str = "all"):
    try:
        root = ROOTS[mode]
        root.mkdir(exist_ok=True)
        with open(root / "_failed.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {video.relative_to(T.IN_DIR)}  {type(err).__name__}: {err}\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description="Snapshot videos while someone is talking")
    ap.add_argument("--interval", type=float, default=None,
                    help=f"seconds between looks (default {INTERVAL:g}; {VISUAL_STEP:g} with --visual-only)")
    ap.add_argument("--burst", type=float, default=None,
                    help=f"--visual-only: seconds of frames after each [VISUAL] line starts (default {VISUAL_AFTER:g})")
    ap.add_argument("--change", type=float, default=None,
                    help=f"min %% of picture changed to save a new shot (default {CHANGE_PCT:g}, or {VISUAL_CHANGE_PCT:g} "
                         "with --visual-only; 0 = save every look)")
    ap.add_argument("--combined", action="store_true",
                    help=f"background looks every --interval s (default {INTERVAL:g}) PLUS full {VISUAL_STEP:g}-second bursts "
                         "around [VISUAL] lines -> snapshots-combined/ (safety net for moments the transcript didn't flag)")
    ap.add_argument("--visual-only", action="store_true",
                    help=f"only {VISUAL_STEP:g}-second bursts around [VISUAL] lines -> snapshots-visual/ (needs transcripts)")
    ap.add_argument("--quality", type=int, default=JPEG_QUALITY, help=f"JPEG quality (default {JPEG_QUALITY})")
    ap.add_argument("--all-video", action="store_true", help="ignore speech, look through the whole video")
    ap.add_argument("--redo", action="store_true", help="redo lessons that already have snapshots")
    ap.add_argument("--only", default=None, metavar="FOLDER",
                    help="only handle videos inside this folder of ./videos (e.g. --only \"Web videos\")")
    ap.add_argument("--select-file", default=None, metavar="JSON",
                    help="only handle the videos listed in this JSON file (paths relative to ./videos)")
    args = ap.parse_args()

    try:
        import av, numpy, PIL  # noqa: F401
    except ImportError as e:
        sys.exit(f"Missing {e.name}. Run:  ~/.transcriber/venv/bin/pip install Pillow")

    T.ONLY = args.only
    if args.select_file:
        T.load_selection(args.select_file)
    T.IN_DIR.mkdir(exist_ok=True)
    SNAP_DIR.mkdir(exist_ok=True)
    vis = args.visual_only
    mode = "visual" if vis else "combined" if args.combined else "all"
    change = args.change if args.change is not None else (VISUAL_CHANGE_PCT if vis else CHANGE_PCT)
    interval = max(args.interval if args.interval is not None else (VISUAL_STEP if vis else INTERVAL), 0.5)
    videos = [v for v in T.list_videos() if args.redo or not is_done(v.relative_to(T.IN_DIR), mode)]
    print(f"Snapshots go to: {ROOTS[mode]}")
    if videos:
        print(f"{len(videos)} video(s) to snapshot", flush=True)
    failed = 0
    if T.PROGRESS_ON:
        units = {}
        for v in videos:
            try:
                units[v] = estimate_looks(v, mode, interval, args.burst, not args.all_video)
            except Exception:
                units[v] = 0.0
        T.progress_plan(units)
    for v in videos:
        if v.stat().st_size == 0:
            continue
        try:
            snapshot_one(v, interval, change, args.quality, not args.all_video, mode, args.burst)
            T.progress_finish(v)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"   FAILED: {type(e).__name__}: {e}", flush=True)
            log_failure(v, e, mode)
            T.progress_finish(v)
            failed += 1
            shutil.rmtree(snap_folder(v.relative_to(T.IN_DIR), mode), ignore_errors=True)
    if failed:
        print(f"\n{failed} file(s) failed, see {ROOTS[mode] / '_failed.log'}")
    print("\nAll done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. (Finished lessons are kept; the unfinished one restarts next run.)")
