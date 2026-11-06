#!/usr/bin/env python3
"""
Download web videos (YouTube links, playlists, and most other video pages) into
videos/Web videos/<playlist or channel>/<title>.mp4 so the normal transcribe + snapshot
steps treat them like any other course. Uses yt-dlp; nothing is uploaded anywhere.

Usage:
    python3 webdl.py URL [URL ...] [--quality 720|1080|best] [--playlist]

    --playlist   if a link is a video *inside* a playlist, download the whole playlist
                 (default: just that one video)

Only download videos you have the right to keep for personal study. Many sites' terms of
service restrict downloading; that is your call.
Already-downloaded videos are skipped (resumable), so re-running is safe.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import transcribe as T

COURSE = "Web videos"                       # the "course" folder these land in
DEST = T.IN_DIR / COURSE
ARCHIVE = DEST / ".downloaded.txt"          # yt-dlp's record of finished downloads
SOURCES = DEST / "_sources.txt"             # title <tab> url <tab> channel <tab> date, for citing later
# folder = playlist title, else channel name, else "Single videos"; files in a playlist keep their order
OUTTMPL = "%(playlist_title,uploader|Single videos)s/%(playlist_index&{} - |)s%(title)s.%(ext)s"


class Log:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        msg = str(msg).replace("ERROR: ", "")
        if "Deprecated Feature" in msg:        # e.g. "Python 3.9 is deprecated": a notice, not a failed video
            return
        hint = ""
        if "needs to be reloaded" in msg or "Sign in to confirm" in msg or "HTTP Error 403" in msg:
            hint = " (the downloader is probably out of date: click Update downloader)"
        print(f"   FAILED: {msg[:300]}{hint}", flush=True)


def height_format(q: str) -> str:
    if q == "best":
        return "bv*+ba/b"
    return f"bv*[height<={q}]+ba/b[height<={q}]/b"


def main():
    ap = argparse.ArgumentParser(description="Download web videos for transcribing")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--quality", default="1080", choices=["720", "1080", "best"])
    ap.add_argument("--playlist", action="store_true")
    args = ap.parse_args()

    try:
        import yt_dlp
    except ImportError:
        sys.exit("yt-dlp is not installed. Run:  ~/.transcriber/venv/bin/pip install yt-dlp imageio-ffmpeg")
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()      # a private ffmpeg, needed to join video + audio
    except Exception:
        ffmpeg = None

    DEST.mkdir(parents=True, exist_ok=True)
    urls = [u.strip() for u in args.urls if u.strip().lower().startswith(("http://", "https://"))]
    if not urls:
        sys.exit("No valid links (they must start with http:// or https://).")

    base = {
        "quiet": True, "no_warnings": True, "logger": Log(), "noprogress": True,
        "noplaylist": not args.playlist, "ignoreerrors": True,
        "paths": {"home": str(DEST)}, "outtmpl": OUTTMPL, "trim_file_name": 150,
        "format": height_format(args.quality), "merge_output_format": "mp4",
        "download_archive": str(ARCHIVE), "retries": 5, "fragment_retries": 5,
    }
    if ffmpeg:
        base["ffmpeg_location"] = ffmpeg

    # ---- pass 1: find out what the links contain (no downloading), so we can show "3 of 12"
    entries = []
    # (the check ignores the already-downloaded list, so repeat runs say "already had" instead of "nothing found")
    check = {k: v for k, v in base.items() if k != "download_archive"}
    with yt_dlp.YoutubeDL({**check, "extract_flat": "in_playlist", "skip_download": True}) as ydl:
        for u in urls:
            print(f"Checking {u}", flush=True)
            info = ydl.extract_info(u, download=False)
            if not info:
                continue
            if info.get("_type") == "playlist":
                entries += [e for e in (info.get("entries") or []) if e]
            else:
                entries.append(info)
    if not entries:
        print("   FAILED: nothing downloadable found at those links", flush=True)
        print("\nAll done.")
        return
    print(f"{len(entries)} video(s) to download", flush=True)
    labels = {Path(f"{i}"): 1.0 for i in range(len(entries))}
    T.progress_plan(labels)

    # ---- pass 2: download one at a time
    state = {"i": -1, "title": "", "last": -1, "got": False}

    def hook(d):
        info = d.get("info_dict") or {}
        title = info.get("title") or "video"
        if title != state["title"]:
            state["title"], state["last"] = title, -1
            print(f"\n>> {COURSE}/{title}", flush=True)
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        state["got"] = True                                   # something was actually fetched for this video
        if d["status"] == "downloading" and total:
            frac = d.get("downloaded_bytes", 0) / total
            pct = int(frac * 100)
            if pct != state["last"]:
                state["last"] = pct
                T.progress_tick(Path(f"{state['i']}"), frac * 0.95)    # leave 5% for joining audio + video
                if pct % 10 == 0:
                    print(f"   {pct}%", flush=True)
        elif d["status"] == "finished":
            T.progress_tick(Path(f"{state['i']}"), 0.97)

    try:
        have = {ln.split()[-1] for ln in ARCHIVE.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except OSError:
        have = set()
    t0 = time.time()
    ok = failed = skipped = 0
    with yt_dlp.YoutubeDL({**base, "progress_hooks": [hook]}) as ydl:
        for i, e in enumerate(entries):
            state["i"] = i
            state["got"] = False
            url = e.get("webpage_url") or e.get("url") or e.get("original_url")
            if e.get("id") and str(e["id"]) in have:
                skipped += 1                              # finished in an earlier run
                print(f"   already downloaded: {e.get('title') or url}", flush=True)
                T.progress_finish(Path(f"{i}"))
                continue
            if not url:
                failed += 1
                T.progress_finish(Path(f"{i}"))
                continue
            try:
                info = ydl.extract_info(url, download=True)
            except Exception as ex:                       # keep going if one video is bad
                print(f"   FAILED: {type(ex).__name__}: {str(ex)[:200]}", flush=True)
                info = None
            if info and not state["got"]:
                skipped += 1                              # already in the archive from an earlier run
                print(f"   already downloaded: {info.get('title', url)}", flush=True)
            elif info:
                ok += 1
                try:
                    with open(SOURCES, "a", encoding="utf-8") as f:
                        f.write(f"{info.get('title', '')}\t{info.get('webpage_url', url)}\t"
                                f"{info.get('uploader', '')}\t{info.get('upload_date', '')}\t{info.get('id', '')}\n")
                    # remember where this file came from, so the panel can delete it cleanly and allow a re-download
                    fp = ((info.get("requested_downloads") or [{}])[0]).get("filepath")
                    if fp:
                        side = Path(fp).with_name("." + Path(fp).stem + ".source.json")
                        side.write_text(json.dumps({"id": info.get("id"), "extractor": info.get("extractor_key"),
                                                    "url": info.get("webpage_url", url), "title": info.get("title")}),
                                        encoding="utf-8")
                except OSError:
                    pass
                print(f"   done in {int(time.time() - t0)}s total", flush=True)
            else:
                failed += 1
            T.progress_finish(Path(f"{i}"))
    print(f"\n{ok} downloaded, {skipped} already had, {failed} failed.")
    print("\nAll done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
