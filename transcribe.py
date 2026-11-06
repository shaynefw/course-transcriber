#!/usr/bin/env python3
"""
Drop-folder video transcriber (runs locally, nothing is uploaded anywhere).

Folder layout (created automatically next to this script):
    videos/        <- put your videos here: videos/<course>/<module>/<lesson>.mp4
    transcripts/   <- results mirror the same subfolders

For each video you get (in transcripts/<same path>/):
    name.txt              clean text in readable paragraphs
    name.timestamps.txt   [HH:MM:SS] per segment; lines where the speaker is probably
                          showing something on screen start with [VISUAL]
    name.visual-cues.txt  just the flagged lines (the "go screenshot this" list)

Per top-level course folder:
    transcripts/<course>/INDEX.md              every lesson: duration, words, visual cues
    transcripts/<course>/_bundles/<module>.md  all lessons of a module in one file

Usage:
    python3 transcribe.py                 # transcribe everything new, then exit
    python3 transcribe.py --watch         # keep running, pick up new files as you add them
    python3 transcribe.py --model medium  # more accurate, slower (default: small)
    python3 transcribe.py --lang auto     # auto-detect language (default: en)
    python3 transcribe.py --retag         # after editing VISUAL_PHRASES: re-tag existing
                                          # transcripts + rebuild indexes (no model needed)
    python3 transcribe.py --reindex       # only rebuild INDEX.md and bundles

A video is "done" when its name.txt exists, so re-running is always safe/resumable.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# EDIT ME: phrases (case-insensitive) that suggest something is on screen.
# A segment containing any of these is tagged [VISUAL] and listed in
# name.visual-cues.txt. After editing, run:  python3 transcribe.py --retag
# ---------------------------------------------------------------------------
VISUAL_PHRASES = [
    "as you can see", "you can see", "can you see", "as we can see", "we can see",
    "look at this", "look at that", "look over here", "take a look", "if you look",
    "right here", "over here", "up here", "down here", "over there", "right there",
    "this chart", "on the chart", "this level", "this line", "this candle",
    "this area", "this zone", "this box", "this one here", "this one right",
    "on the screen", "on your screen", "on my screen", "my screen",
    "let me show you", "let me show", "i'll show you", "i will show you",
    "let me pull up", "pull up", "let me draw", "if i draw", "i'm going to draw",
    "here we have", "here you have", "here you can", "you'll see here",
    "zoom in", "highlighted", "circled", "this arrow", "this number", "this table",
    "this dashboard", "this setting", "this button", "this tab",
    # drawing/marking talk and pointing at parts of a chart or diagram
    "mark out", "mark this", "mark that", "put this on", "put that on", "i'll just drag", "just drag", "drag",
    "rectangle", "zoom", "so here", "between here", "from here", "to here",
    "this wick", "these wicks", "this move", "this piece", "this body", "this one", "these candles",
]
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "small"
DEFAULT_LANG = "en"

VIDEO_EXTS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv",
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg",
    ".opus", ".oga", ".amr", ".3gp", ".wma", ".aiff", ".aif", ".caf", ".mpg", ".mpeg",   # voice notes, phone recordings
}

SELECT = None        # --select-file FILE: only handle exactly these videos (paths relative to ./videos); None = no limit
ONLY = None          # --only "Folder": only handle videos inside this top-level folder of ./videos
BASE = Path(__file__).resolve().parent
IN_DIR = BASE / "videos"
OUT_DIR = BASE / "transcripts"

TS_RE = re.compile(r"^(?:\[VISUAL\] )?\[(\d\d):(\d\d):(\d\d)\] (.*)$")
_CUE_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(p) for p in sorted(VISUAL_PHRASES, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)


# ------------------------------------------- progress reporting (for the control panel's time estimates)
# The panel sets TRANSCRIBER_PROGRESS=1; from a terminal these machine-readable lines stay off.
PROGRESS_ON = bool(os.environ.get("TRANSCRIBER_PROGRESS"))
_prog = {"done": 0.0, "total": 0.0, "units": {}}


def video_seconds(video: Path) -> float:
    try:
        import av
        with av.open(str(video)) as c:
            return (c.duration or 0) / 1_000_000
    except Exception:
        return 0.0


def progress_plan(units: dict):
    """units: {video: amount of work} for this batch (seconds of audio, or planned looks)."""
    _prog.update(done=0.0, total=float(sum(units.values())), units=dict(units))
    if PROGRESS_ON:
        print(f"PLAN {len(units)} {_prog['total']:.1f}", flush=True)


def progress_tick(video: Path, frac: float):
    if PROGRESS_ON and (abs(frac - _prog.get("last", -1)) >= 0.005 or frac >= 1):
        _prog["last"] = frac
        u = _prog["units"].get(video, 0.0)
        print(f"PROGRESS {_prog['done'] + frac * u:.1f} {_prog['total']:.1f} {min(max(frac, 0), 1):.3f}", flush=True)


def progress_finish(video: Path):
    _prog["done"] += _prog["units"].get(video, 0.0)
    if PROGRESS_ON:
        print(f"PROGRESS {_prog['done']:.1f} {_prog['total']:.1f} 0.000", flush=True)


# ---------------------------------------------------------------- helpers
def stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def hms(seconds: float) -> str:
    """Compact duration for tables: M:SS or H:MM:SS."""
    s = int(round(seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def lw(n: int) -> str:
    return f"{n} lesson" + ("" if n == 1 else "s")


def natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s.lower())]


def write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_if_changed(path: Path, text: str):
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except FileNotFoundError:
        pass
    write_atomic(path, text)


def walk_files(root: Path):
    """os.walk that follows symlinked folders (so you can symlink a course in)."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for f in sorted(filenames):
            yield Path(dirpath) / f


def out_paths(rel: Path):
    base = OUT_DIR / rel.with_suffix("")
    return {
        "txt": base.with_name(base.name + ".txt"),
        "ts": base.with_name(base.name + ".timestamps.txt"),
        "cues": base.with_name(base.name + ".visual-cues.txt"),
        "meta": base.with_name("." + base.name + ".meta.json"),
    }


def list_videos():
    vids = []
    for p in walk_files(IN_DIR):
        if p.suffix.lower() in VIDEO_EXTS and not p.name.startswith("."):
            if ONLY and p.relative_to(IN_DIR).parts[0] != ONLY:
                continue
            if SELECT is not None and p.relative_to(IN_DIR).as_posix() not in SELECT:
                continue
            vids.append(p)
    return sorted(vids, key=lambda p: natural_key(str(p.relative_to(IN_DIR))))


def load_selection(path):
    """Read a JSON list of video paths (relative to ./videos) written by the control panel."""
    global SELECT
    SELECT = set(json.loads(Path(path).read_text(encoding="utf-8")))


def find_pending():
    return [p for p in list_videos() if not out_paths(p.relative_to(IN_DIR))["txt"].exists()]


def file_ready(p: Path, settle: float) -> bool:
    """Non-empty, and (in watch mode) not modified in the last `settle` seconds."""
    try:
        st = p.stat()
    except FileNotFoundError:
        return False
    return st.st_size > 0 and (time.time() - st.st_mtime >= settle)


# ------------------------------------------------------------ visual cues
def find_cue(text: str):
    m = _CUE_RE.search(text)
    return m.group(1).lower() if m else None


def render_timestamps(segments):
    """segments: [(start_seconds_or_stamp, text)] -> (timestamps text, cue lines)."""
    ts_lines, cue_lines = [], []
    for st, text in segments:
        st = st if isinstance(st, str) else stamp(st)
        cue = find_cue(text)
        if cue:
            ts_lines.append(f"[VISUAL] [{st}] {text}")
            cue_lines.append(f"[{st}] {text}   <- \"{cue}\"")
        else:
            ts_lines.append(f"[{st}] {text}")
    return ts_lines, cue_lines


def cues_file_text(cue_lines):
    head = ["# Visual cues: lines where the speaker is probably showing something on screen.",
            "# Scrub to the timestamp and screenshot. (Phrases are in VISUAL_PHRASES in transcribe.py)",
            ""]
    if not cue_lines:
        head.append("(none found)")
    return "\n".join(head + cue_lines) + "\n"


def retag(ts_path: Path) -> bool:
    """Re-apply cue tagging to an existing .timestamps.txt. Returns True if parsed."""
    segs = []
    for line in ts_path.read_text(encoding="utf-8").splitlines():
        m = TS_RE.match(line)
        if m:
            segs.append((f"{m[1]}:{m[2]}:{m[3]}", m[4]))
    ts_lines, cue_lines = render_timestamps(segs)
    write_if_changed(ts_path, "\n".join(ts_lines) + ("\n" if ts_lines else ""))
    cues_path = ts_path.with_name(ts_path.name.replace(".timestamps.txt", ".visual-cues.txt"))
    write_if_changed(cues_path, cues_file_text(cue_lines))
    return True


# ---------------------------------------------------------- transcription
def transcribe_one(model, video: Path, lang, model_name):
    rel = video.relative_to(IN_DIR)
    paths = out_paths(rel)

    print(f"\n>> {rel}", flush=True)
    start = time.time()
    segments, info = model.transcribe(
        str(video),
        language=lang,
        vad_filter=True,                   # skips silence, speeds things up
        beam_size=5,
        condition_on_previous_text=False,  # stops long lectures from drifting into repeat loops
    )
    total = info.duration or 0
    print(f"   length {stamp(total)}, language: {info.language}", flush=True)

    segs, paragraphs, spans = [], [], []
    current, last_end, last_pct, last_fine = [], 0.0, -1, -1
    prev_norm, repeat = None, 0

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        norm = re.sub(r"\W+", " ", text.lower()).strip()
        repeat = repeat + 1 if norm == prev_norm else 0
        prev_norm = norm
        if repeat >= 2:            # same line 3+ times in a row = Whisper hallucination loop
            continue

        segs.append((seg.start, text))
        spans.append([round(seg.start, 1), round(seg.end, 1)])   # lets snapshots.py know when someone is talking

        # start a new paragraph on a pause of 2s+ or when it gets long
        if current and (seg.start - last_end > 2.0 or sum(len(t) for t in current) > 700):
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        last_end = seg.end

        if total:
            pct = int(seg.end / total * 100)
            if pct != last_fine:
                last_fine = pct
                progress_tick(video, seg.end / total)
            if pct // 10 != last_pct // 10:
                last_pct = pct
                print(f"   {pct}%  ({int(time.time() - start)}s elapsed)", flush=True)

    if current:
        paragraphs.append(" ".join(current))

    ts_lines, cue_lines = render_timestamps(segs)
    words = sum(len(p.split()) for p in paragraphs)
    meta = {"duration": total, "words": words, "language": info.language, "model": model_name,
            "spans": spans}

    # the .txt is written last: it is the "done" marker
    write_atomic(paths["ts"], "\n".join(ts_lines) + ("\n" if ts_lines else ""))
    write_atomic(paths["cues"], cues_file_text(cue_lines))
    write_atomic(paths["meta"], json.dumps(meta))
    write_atomic(paths["txt"], "\n\n".join(paragraphs) + ("\n" if paragraphs else ""))

    elapsed = max(time.time() - start, 0.001)
    speed = f", {total / elapsed:.1f}x realtime" if total else ""
    print(f"   done in {int(elapsed)}s{speed} | {words} words, {len(cue_lines)} visual cues", flush=True)


# ------------------------------------------------------- INDEX + bundles
def collect_lessons():
    """-> {course: {module: [lesson dicts]}} from finished transcripts."""
    courses = defaultdict(lambda: defaultdict(list))
    if not OUT_DIR.exists():
        return courses
    for p in walk_files(OUT_DIR):
        if not p.name.endswith(".timestamps.txt") or p.name.startswith("."):
            continue
        stem = p.name[: -len(".timestamps.txt")]
        txt = p.with_name(stem + ".txt")
        if not txt.exists():
            continue
        cues = p.with_name(stem + ".visual-cues.txt")
        if not cues.exists():
            retag(p)
        rel = p.relative_to(OUT_DIR)
        parts = rel.parts
        course = parts[0] if len(parts) > 1 else ""
        module = " - ".join(parts[1:-1]) if len(parts) > 2 else (course or "(root)")

        meta = {}
        try:
            meta = json.loads(p.with_name("." + stem + ".meta.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        ts_text = p.read_text(encoding="utf-8")
        lines = ts_text.splitlines()
        duration = meta.get("duration")
        if not duration:
            last = next((TS_RE.match(l) for l in reversed(lines) if TS_RE.match(l)), None)
            duration = int(last[1]) * 3600 + int(last[2]) * 60 + int(last[3]) if last else 0
        words = meta.get("words")
        if words is None:
            words = len(txt.read_text(encoding="utf-8").split())
        n_cues = sum(1 for l in lines if l.startswith("[VISUAL]"))
        courses[course][module].append({
            "title": stem, "rel": rel, "duration": duration, "words": words,
            "cues": n_cues, "ts_lines": lines,
        })
    return courses


def build_outputs():
    courses = collect_lessons()
    pending_by_course = defaultdict(int)
    total_by_course = defaultdict(int)
    for v in list_videos():
        parts = v.relative_to(IN_DIR).parts
        c = parts[0] if len(parts) > 1 else ""
        total_by_course[c] += 1
        if not out_paths(v.relative_to(IN_DIR))["txt"].exists():
            pending_by_course[c] += 1

    for course in sorted(set(courses) | set(total_by_course), key=natural_key):
        course_dir = OUT_DIR / course if course else OUT_DIR
        modules = courses.get(course, {})
        all_lessons = [l for m in modules.values() for l in m]
        out = [f"# {course or 'Transcripts'} - Index", ""]
        out.append(
            f"{len(modules)} modules · {len(all_lessons)} of {total_by_course[course]} lessons transcribed · "
            f"{hms(sum(l['duration'] for l in all_lessons))} total · "
            f"{sum(l['words'] for l in all_lessons):,} words · "
            f"{sum(l['cues'] for l in all_lessons)} visual cues"
        )
        if pending_by_course[course]:
            out.append(f"\n_{pending_by_course[course]} video(s) not transcribed yet._")
        out.append("\n`[VISUAL]` lines in a lesson's timestamps file = speaker is likely showing something on screen.")

        for module in sorted(modules, key=natural_key):
            lessons = sorted(modules[module], key=lambda l: natural_key(l["title"]))
            dur = sum(l["duration"] for l in lessons)
            words = sum(l["words"] for l in lessons)
            cues = sum(l["cues"] for l in lessons)

            safe = re.sub(r'[\\/:*?"<>|]', "-", module).strip() or "module"
            bundle_rel = Path("_bundles") / f"{safe}.md"
            b = [f"# {module}", "",
                 f"Course: {course or '-'} · {lw(len(lessons))} · {hms(dur)} · {words:,} words · {cues} visual cues",
                 "",
                 "Each lesson below is its timestamped transcript. A leading [VISUAL] tag marks a line where the "
                 "speaker is probably showing something on screen (good moments to screenshot).", ""]
            for l in lessons:
                b += ["", "---", "", f"## Lesson: {l['title']}", f"(duration {hms(l['duration'])}, {l['cues']} visual cues)", ""]
                b += l["ts_lines"]
            write_if_changed(course_dir / bundle_rel, "\n".join(b) + "\n")

            out += ["", f"## {module}", "",
                    f"Bundle: [{bundle_rel.as_posix()}]({quote(bundle_rel.as_posix())}) · "
                    f"{lw(len(lessons))} · {hms(dur)} · {words:,} words · {cues} cues", "",
                    "| # | Lesson | Duration | Words | Visual cues |", "|--:|---|--:|--:|--:|"]
            for i, l in enumerate(lessons, 1):
                link = quote((l["rel"].with_name(l["title"] + ".timestamps.txt").relative_to(course) if course else
                              l["rel"].with_name(l["title"] + ".timestamps.txt")).as_posix())
                title = l["title"].replace("|", "\\|")
                out.append(f"| {i} | [{title}]({link}) | {hms(l['duration'])} | {l['words']:,} | {l['cues']} |")
        write_if_changed(course_dir / "INDEX.md", "\n".join(out) + "\n")


def log_failure(video: Path, err: Exception):
    try:
        with open(OUT_DIR / "_failed.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {video.relative_to(IN_DIR)}  {type(err).__name__}: {err}\n")
    except OSError:
        pass


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Local video transcriber (Whisper)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="tiny, base, small, medium, large-v3, distil-large-v3, or a .en variant "
                         f"(default: {DEFAULT_MODEL})")
    ap.add_argument("--lang", default=DEFAULT_LANG,
                    help=f"language code, or 'auto' to detect (default: {DEFAULT_LANG})")
    ap.add_argument("--watch", action="store_true", help="keep running and pick up new files")
    ap.add_argument("--only", default=None, metavar="FOLDER",
                    help="only handle videos inside this folder of ./videos (e.g. --only \"Web videos\")")
    ap.add_argument("--select-file", default=None, metavar="JSON",
                    help="only handle the videos listed in this JSON file (paths relative to ./videos)")
    ap.add_argument("--retag", action="store_true",
                    help="re-apply VISUAL_PHRASES to existing transcripts and rebuild indexes, then exit")
    ap.add_argument("--reindex", action="store_true", help="only rebuild INDEX.md + bundles, then exit")
    args = ap.parse_args()
    lang = None if args.lang.lower() == "auto" else args.lang
    global ONLY
    ONLY = args.only
    if args.select_file:
        load_selection(args.select_file)

    IN_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)

    if args.retag:
        n = 0
        for p in walk_files(OUT_DIR):
            if p.name.endswith(".timestamps.txt") and not p.name.startswith("."):
                retag(p)
                n += 1
        build_outputs()
        print(f"Re-tagged {n} transcript(s) and rebuilt indexes/bundles.")
        return
    if args.reindex:
        build_outputs()
        print("Indexes and bundles rebuilt.")
        return

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed. Run transcribe.command (it sets everything up), "
                 "or:  python3 -m pip install faster-whisper")

    print(f"Loading model '{args.model}' (first use downloads it)...", flush=True)
    try:
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
    except Exception as e:
        sys.exit(f"Could not load model '{args.model}': {e}\n(First run needs internet to download the model.)")

    print(f"Drop videos into: {IN_DIR}")
    print(f"Transcripts go to: {OUT_DIR}")

    failed = set()   # don't retry a bad file over and over within one run
    build_outputs()
    while True:
        pending = [v for v in find_pending() if v not in failed]
        if pending:
            print(f"{len(pending)} video(s) to transcribe", flush=True)
            if PROGRESS_ON:
                progress_plan({v: video_seconds(v) for v in pending})
        did_any = False
        for v in pending:
            if not file_ready(v, settle=5.0 if args.watch else 0.0):
                print(f"   skipping {v.name} (empty or still being copied)", flush=True)
                progress_finish(v)
                continue
            try:
                transcribe_one(model, v, lang, args.model)
                did_any = True
            except KeyboardInterrupt:
                raise
            except Exception as e:  # keep going if one file is bad
                print(f"   FAILED: {type(e).__name__}: {e}", flush=True)
                log_failure(v, e)
                failed.add(v)
                progress_finish(v)
            else:
                progress_finish(v)
                try:
                    build_outputs()      # keep INDEX/bundles current after every lesson
                except Exception as e:
                    print(f"   (index update failed: {e})", flush=True)
        if not args.watch:
            break
        if did_any:
            print("\nWaiting for new files (Ctrl-C to stop)...", flush=True)
        time.sleep(10)

    if failed:
        print(f"\n{len(failed)} file(s) failed, see {OUT_DIR / '_failed.log'}")
    print("\nAll done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. (Finished lessons are kept; unfinished ones restart next run.)")
