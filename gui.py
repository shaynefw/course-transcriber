#!/usr/bin/env python3
"""
Transcriber control panel: a tiny local web page (127.0.0.1 only, stdlib only) that runs
transcribe.py for you. Start it by double-clicking Transcriber.app (or gui.command).

It never uploads anything; the page only talks to this process on your own Mac.
"""
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ai_helper as AI
import files_api as FA
import snapshots as SN
import transcribe as T

BASE = T.BASE
SCRIPT = BASE / "transcribe.py"
# TRANSCRIBER_PORT pins one port (used for demos and tests so a second panel never collides with your real one)
PORTS = [int(os.environ["TRANSCRIBER_PORT"])] if os.environ.get("TRANSCRIBER_PORT", "").isdigit() else range(8765, 8776)
TOKEN = secrets.token_hex(16)
MODELS = ["tiny", "base", "small", "medium"]
DL_PY = Path.home() / ".transcriber" / "venv-dl" / "bin" / "python"   # Python 3.10+ env for the downloader (yt-dlp needs it)
SINGLE_COURSE = "Single files"     # folder in ./videos holding links to individually chosen files
WEB_COURSE = "Web videos"          # folder in ./videos that downloaded videos go to (see webdl.py)

lock = threading.Lock()
state = {
    "proc": None, "mode": "transcribe", "capture": "all", "running": False, "watch": False, "stopping": False,
    "log": [], "current": "", "percent": 0, "file_started": 0.0,
    "phase": "idle", "last_exit": None, "run_done": 0, "run_failed": 0,
    "speed": "", "started": 0.0,
    "units_done": 0.0, "units_total": 0.0, "plan_files": 0, "batch_started": 0.0,
    "queue": [], "stage_i": 1, "stage_n": 1,
}
_scan_cache = {"t": 0.0, "courses": []}


# ------------------------------------------------------------------ process
def _reader(proc):
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        with lock:
            s = state
            if line.startswith("PLAN "):                       # start of a batch: how much work there is
                _, files, total = line.split()
                s.update(plan_files=int(files), units_total=float(total), units_done=0.0, batch_started=time.time(),
                         run_done=0, run_failed=0)
                continue
            if line.startswith("PROGRESS "):
                _, done, total, frac = line.split()
                s.update(units_done=float(done), units_total=float(total), percent=int(float(frac) * 100))
                continue
            if line.strip():
                s["log"].append(line)
                del s["log"][:-400]
            if line.startswith("Loading model"):
                s["phase"] = _phase("loading model (first use downloads it)")
            elif line.startswith(">> "):
                s["phase"], s["current"], s["percent"] = _phase(
                    {"snapshots": "taking snapshots", "download": "downloading"}.get(s["mode"], "transcribing")), line[3:], 0
                s["file_started"] = time.time()
            elif (m := re.match(r"\s+(\d+)%", line)):
                s["percent"] = int(m.group(1))
            elif line.strip().startswith("done in"):
                s["run_done"] += 1
                s["percent"] = 100
                m = re.search(r"([\d.]+)x realtime", line)
                if m:
                    s["speed"] = m.group(1) + "x realtime"
            elif line.strip().startswith("FAILED"):
                s["run_failed"] += 1
            elif line.startswith("Waiting for new files"):
                s["phase"], s["current"] = _phase("watching for new files"), ""
    code = proc.wait()
    nxt = None
    with lock:
        if state["queue"] and not state["stopping"] and code == 0:
            nxt = state["queue"].pop(0)
        else:
            state["log"].append("— stopped —" if state["stopping"] or code else "— finished —")
            state.update(running=False, proc=None, last_exit=code, phase="idle", stopping=False,
                         current="", percent=0, queue=[])
    if nxt:
        _launch(nxt)


def _phase(text):
    return f"step {state['stage_i']} of {state['stage_n']}: {text}" if state["stage_n"] > 1 else text


def _launch(stage):
    """Start one stage {mode, capture, label, cmd} of a job (jobs with several stages run one after another)."""
    cmd = stage["cmd"]
    if Path("/usr/bin/caffeinate").exists():
        cmd = ["/usr/bin/caffeinate", "-i"] + cmd      # keep the Mac awake while working
    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, start_new_session=True,
                            env={**os.environ, "TRANSCRIBER_PROGRESS": "1"})
    with lock:
        state["stage_i"] = state["stage_n"] - len(state["queue"])
        state.update(proc=proc, mode=stage["mode"], capture=stage["capture"], running=True,
                     current="", percent=0, run_done=0, run_failed=0, speed="", stopping=False,
                     units_done=0.0, units_total=0.0, plan_files=0, batch_started=0.0)
        state["phase"] = _phase("starting")
        state["log"].append(f"— {stage['label']} —" if state["stage_n"] > 1 else f"Starting ({stage['label']})…")
    threading.Thread(target=_reader, args=(proc,), daemon=True).start()


def _selection_args(body, name):
    """If the page sent an explicit list of videos, save it to a file for the script and return its flags."""
    sel = body.get("select")
    if not isinstance(sel, list):
        return []
    sel = [x for x in sel if isinstance(x, str)][:5000]
    d = Path.home() / ".transcriber"
    d.mkdir(exist_ok=True)
    f = d / f"selection-{name}.json"
    f.write_text(json.dumps(sel), encoding="utf-8")
    return ["--select-file", str(f)]


def _transcribe_stage(body, only=None):
    model = body.get("model", "small")
    model = model if model in MODELS else "small"
    watch = bool(body.get("watch")) and not only
    cmd = [sys.executable, "-u", str(SCRIPT), "--model", model, "--lang", "en" if body.get("english", True) else "auto"]
    if watch:
        cmd.append("--watch")
    if only:
        cmd += ["--only", only]
    elif not watch:
        cmd += _selection_args(body, "transcribe")      # only the videos ticked in the TRANSCRIBE tab
    return {"mode": "transcribe", "capture": "all", "label": "transcribing", "cmd": cmd,
            "desc": f"{model}{', watch' if watch else ''}"}


def _snapshot_stage(body, only=None):
    try:
        interval = min(max(float(body.get("interval", 5)), 1), 120)
        change = min(max(float(body.get("change", 1.0)), 0), 20)
        burst = f"{min(max(float(body.get('burst', 5)), 1), 60):g}"
    except (TypeError, ValueError):
        interval, change, burst = 5.0, 1.0, "5"
    cmd = [sys.executable, "-u", str(BASE / "snapshots.py"), "--interval", f"{interval:g}", "--change", f"{change:g}"]
    capture = body.get("capture") if body.get("capture") in ("visual", "combined") else "all"
    if body.get("redo"):
        cmd.append("--redo")
    if capture == "visual":
        cmd += ["--visual-only", "--burst", burst]
    elif capture == "combined":
        cmd += ["--combined", "--burst", burst]
    elif not body.get("speech_only", True):
        cmd.append("--all-video")
    if only:
        cmd += ["--only", only]
    else:
        cmd += _selection_args(body, "snapshots")       # only the videos ticked in the SNAPSHOTS tab
    desc = {"visual": "visual-only snapshots", "combined": "combined snapshots (bursts + background)"}.get(
        capture, f"snapshots every {interval:g}s")
    return {"mode": "snapshots", "capture": capture, "label": "taking snapshots", "cmd": cmd, "desc": desc}


def _web_stage(body):
    urls = body.get("urls") or []
    if isinstance(urls, str):
        urls = urls.splitlines()
    urls = [u.strip() for u in urls if u.strip()][:50]
    urls = [u for u in urls if u.lower().startswith(("http://", "https://")) and len(u) < 2000]
    if not urls:
        return None
    q = body.get("quality") if body.get("quality") in ("720", "1080", "best") else "1080"
    cmd = [str(DL_PY) if DL_PY.exists() else sys.executable, "-u", str(BASE / "webdl.py"), *urls, "--quality", q]
    if body.get("playlist"):
        cmd.append("--playlist")
    return {"mode": "download", "capture": "all", "label": "downloading", "cmd": cmd, "desc": f"{len(urls)} link(s)"}


def start(body):
    kind = body.get("mode")
    if kind in ("transcribe", "snapshots", None) and isinstance(body.get("select"), list) and not body["select"] \
            and not (kind != "snapshots" and body.get("watch")):
        return False                                    # nothing selected, nothing to do
    if kind == "files":
        stages = [_transcribe_stage(body, only=SINGLE_COURSE)]
        if body.get("do_snapshots"):
            stages.append(_snapshot_stage(body.get("snap") or {}, only=SINGLE_COURSE))
    elif kind == "web":
        stages = [_web_stage(body)]
        if stages[0] is None:
            return False
        if body.get("do_transcribe", True):
            stages.append(_transcribe_stage(body, only=WEB_COURSE))
        if body.get("do_snapshots", True):
            stages.append(_snapshot_stage(body.get("snap") or {}, only=WEB_COURSE))
    elif kind == "snapshots":
        stages = [_snapshot_stage(body)]
    else:
        stages = [_transcribe_stage(body)]
    with lock:
        if state["running"]:
            return False
        state.update(queue=stages[1:], stage_n=len(stages), stage_i=1, log=[], started=time.time(), last_exit=None,
                     running=True)
    _launch(stages[0])
    return True


def stop():
    with lock:
        proc = state["proc"]
        if not proc:
            return
        state["stopping"] = True
        state["queue"] = []
        state["phase"] = "stopping…"
    try:
        os.killpg(proc.pid, signal.SIGTERM)   # SIGINT can be inherited as "ignored" from the launcher
    except ProcessLookupError:
        return

    def force():
        time.sleep(8)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    threading.Thread(target=force, daemon=True).start()


# ------------------------------------------------------------------ courses
def scan_courses(force=False):
    if not force and time.time() - _scan_cache["t"] < 2:
        return _scan_cache["courses"]
    T.IN_DIR.mkdir(exist_ok=True)
    stats = {}
    for v in T.list_videos():
        rel = v.relative_to(T.IN_DIR)
        c = rel.parts[0] if len(rel.parts) > 1 else "(loose files)"
        d = stats.setdefault(c, [0, 0, 0, 0, 0])
        d[0] += 1
        d[1] += T.out_paths(rel)["txt"].exists()
        d[2] += SN.is_done(rel)
        d[3] += SN.is_done(rel, "visual")
        d[4] += SN.is_done(rel, "combined")
    courses = []
    for p in sorted(T.IN_DIR.iterdir(), key=lambda p: T.natural_key(p.name)):
        if p.name.startswith(".") or not p.is_dir():
            continue
        total, done, snaps, vis, combo = stats.get(p.name, [0, 0, 0, 0, 0])
        courses.append({"name": p.name, "total": total, "done": done, "snaps": snaps, "vis": vis, "combo": combo, "link": p.is_symlink(),
                        "target": str(p.resolve()) if p.is_symlink() else ""})
    if "(loose files)" in stats:
        courses.append({"name": "(loose files)", "total": stats["(loose files)"][0],
                        "done": stats["(loose files)"][1], "snaps": stats["(loose files)"][2],
                        "vis": stats["(loose files)"][3], "combo": stats["(loose files)"][4], "link": False, "target": ""})
    _scan_cache.update(t=time.time(), courses=courses)
    return courses


def pick_folder():
    script = 'POSIX path of (choose folder with prompt "Choose a course folder (its subfolders are the modules)")'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        return None, "cancelled"
    src = Path(r.stdout.strip()).resolve()
    if not src.is_dir():
        return None, "not a folder"
    T.IN_DIR.mkdir(exist_ok=True)
    name, n = src.name, 2
    while (T.IN_DIR / name).exists():
        if (T.IN_DIR / name).is_symlink() and (T.IN_DIR / name).resolve() == src:
            return name, "already added"
        name, n = f"{src.name} ({n})", n + 1
    (T.IN_DIR / name).symlink_to(src, target_is_directory=True)
    _scan_cache["t"] = 0
    return name, "added"


def add_files(paths):
    """Link individually chosen audio/video files into videos/Single files/ (the originals are only read).
    Returns (added names, skipped descriptions)."""
    dest = T.IN_DIR / SINGLE_COURSE
    dest.mkdir(parents=True, exist_ok=True)
    added, skipped = [], []
    for raw in paths:
        src = Path(raw).expanduser().resolve()
        if not src.is_file():
            skipped.append(f"{src.name} (not a file)")
        elif src.suffix.lower() not in T.VIDEO_EXTS:
            skipped.append(f"{src.name} (not a supported audio/video type)")
        elif src.stat().st_size == 0:
            skipped.append(f"{src.name} (empty)")
        else:
            name, n = src.name, 2
            while (dest / name).exists() or (dest / name).is_symlink():
                if (dest / name).is_symlink() and (dest / name).resolve() == src:
                    break
                name, n = f"{src.stem} ({n}){src.suffix}", n + 1
            else:
                (dest / name).symlink_to(src)
            added.append(name)
    _scan_cache["t"] = 0
    return added, skipped


def pick_files():
    script = ('set fs to choose file with prompt "Choose audio or video files to transcribe" with multiple selections allowed\n'
              'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    r = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True)
    if r.returncode != 0:
        return [], [], "cancelled"
    added, skipped = add_files([ln for ln in r.stdout.splitlines() if ln.strip()])
    return added, skipped, "ok"


def list_singles():
    d = T.IN_DIR / SINGLE_COURSE
    out = []
    if d.is_dir():
        for p in sorted(d.iterdir(), key=lambda x: T.natural_key(x.name)):
            if p.is_symlink() and p.suffix.lower() in T.VIDEO_EXTS:
                out.append({"name": p.name, "target": str(p.resolve()), "exists": p.exists(),
                            "done": T.out_paths(Path(SINGLE_COURSE) / p.name)["txt"].exists()})
    return out


def remove_single(name):
    """Unlink one picked file from the Single files list (the original file is never touched)."""
    d = T.IN_DIR / SINGLE_COURSE
    p = d / name
    if p.parent != d or not p.is_symlink():
        return False
    p.unlink()
    _scan_cache["t"] = 0
    return True


def missing_links():
    """Dead shortcuts in ./videos: symlinks whose original file or folder no longer exists. Only symlinks are ever
    listed, never real files, and linked folders are not entered (they belong to you)."""
    out = []
    for dp, dns, fns in os.walk(T.IN_DIR, followlinks=False):
        for n in dns + fns:
            p = Path(dp) / n
            if p.is_symlink() and not p.exists():
                out.append(p)
    return out


def clear_missing(dry_run=False):
    gone = missing_links()
    names = [p.relative_to(T.IN_DIR).as_posix() for p in gone]
    if not dry_run:
        for p in gone:
            if p.is_symlink() and not p.exists():       # re-checked right before deleting; never touches a real file
                p.unlink()
        _scan_cache["t"] = 0
    return names


def remove_course(name):
    p = T.IN_DIR / name
    if p.parent != T.IN_DIR or not p.is_symlink():
        return "Only linked course folders can be removed here (your original files are never touched)."
    p.unlink()
    _scan_cache["t"] = 0
    return "removed"


def open_path(what, name=""):
    target = {
        "transcripts": T.OUT_DIR,
        "index": T.OUT_DIR / name / "INDEX.md",
        "bundles": T.OUT_DIR / name / "_bundles",
        "failed": T.OUT_DIR / "_failed.log",
        "snapshots": SN.SNAP_DIR / name if name else SN.SNAP_DIR,
        "snapshots-visual": SN.VIS_DIR / name if name else SN.VIS_DIR,
        "webvideos": T.IN_DIR / WEB_COURSE,
        "singlefiles": T.OUT_DIR / SINGLE_COURSE,
        "snapshots-combined": SN.COMBO_DIR / name if name else SN.COMBO_DIR,
        "snapfailed-combined": SN.COMBO_DIR / "_failed.log",
        "snapfailed": SN.SNAP_DIR / "_failed.log",
        "snapfailed-visual": SN.VIS_DIR / "_failed.log",
    }.get(what)
    if target is None:
        return False
    if target is None or not target.exists():
        return False
    target = target.resolve()
    if not any(root.resolve() in [target, *target.parents] for root in (T.OUT_DIR, SN.SNAP_DIR, SN.VIS_DIR, SN.COMBO_DIR, T.IN_DIR / WEB_COURSE)):
        return False
    subprocess.Popen(["open", str(target)])
    return True


# --------------------------------------------------------------------- http
def status():
    with lock:
        s = dict(state)
        s.pop("proc")
        s["log"] = s["log"][-120:]
        s["elapsed_file"] = int(time.time() - s["file_started"]) if s["current"] and s["running"] else 0
        s["elapsed_run"] = int(time.time() - s["started"]) if s["running"] else 0
        now = time.time()
        s["eta_file"] = s["eta_batch"] = None
        if s["running"] and s["current"] and s["percent"] >= 2 and s["elapsed_file"] >= 5:
            s["eta_file"] = int(s["elapsed_file"] * (100 - s["percent"]) / s["percent"])
        if s["running"] and s["units_total"] > 0:
            eb = now - s["batch_started"]
            if s["units_done"] > 0 and eb >= 10 and s["units_done"] / s["units_total"] >= 0.005:
                s["eta_batch"] = int(eb * (s["units_total"] - s["units_done"]) / s["units_done"])
    s["courses"] = scan_courses()
    if s["mode"] == "transcribe":
        s["failed"] = (T.OUT_DIR / "_failed.log").exists()
    else:
        s["failed"] = (SN.ROOTS.get(s["capture"], SN.SNAP_DIR) / "_failed.log").exists()
    s["has_snaps"] = [c["name"] for c in s["courses"] if (SN.SNAP_DIR / c["name"]).is_dir()]
    s["has_vis"] = [c["name"] for c in s["courses"] if (SN.VIS_DIR / c["name"]).is_dir()]
    s["has_combo"] = [c["name"] for c in s["courses"] if (SN.COMBO_DIR / c["name"]).is_dir()]
    s["has_index"] = [c["name"] for c in s["courses"] if (T.OUT_DIR / c["name"] / "INDEX.md").exists()]
    s["token"] = TOKEN
    return s


ICONS = {"/icon.svg": ("icon.svg", "image/svg+xml"), "/favicon.png": ("favicon.png", "image/png"),
         "/favicon.ico": ("favicon.png", "image/png")}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        host = self.headers.get("Host", "")
        return host.split(":")[0] in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json", cache="no-store"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json", "application/javascript")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "{}")
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        if path == "/api/ping":
            return self._send(200, json.dumps({"app": "transcriber-gui"}))
        if path == "/api/log":
            with lock:
                text = "\n".join(state["log"]) + "\n"
            return self._send(200, text, "text/plain")
        if path == "/api/status":
            return self._send(200, json.dumps(status()))
        if path.startswith("/api/"):
            try:
                return self._api_get(path, q)
            except (ValueError, OSError) as e:
                return self._send(400, json.dumps({"error": str(e)}))
        icon = ICONS.get(path)
        if icon and (BASE / "assets" / icon[0]).exists():
            return self._send(200, (BASE / "assets" / icon[0]).read_bytes(), icon[1])
        ui = BASE / "ui"
        if path in ("/", "/index.html"):
            return self._send(200, (ui / "index.html").read_bytes(), "text/html")
        if path.startswith("/ui/") and "/" not in path[4:] and (ui / path[4:]).is_file():
            ctype = {".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml",
                     ".png": "image/png"}.get(Path(path).suffix, "application/octet-stream")
            return self._send(200, (ui / path[4:]).read_bytes(), ctype)
        self._send(404, "{}")

    def _api_get(self, path, q):
        if path == "/api/tree":
            return self._send(200, json.dumps(FA.tree(force=q.get("force") == "1")))
        if path == "/api/storage":
            return self._send(200, json.dumps(FA.storage(force=q.get("force") == "1")))
        if path == "/api/text":
            return self._send(200, json.dumps(FA.read_text(q.get("kind", ""), q.get("rel", ""), q.get("module", ""))))
        if path == "/api/snaps":
            return self._send(200, json.dumps(FA.snap_list(q.get("mode", ""), q.get("rel", ""))))
        if path == "/api/img":
            p = FA.image_path(q.get("mode", ""), q.get("rel", ""), q.get("name", ""))
            if not p.is_file():
                return self._send(404, "{}")
            return self._send(200, p.read_bytes(), "image/jpeg", cache="private, max-age=300")
        if path == "/api/ai/prompt":
            AI.ensure_fresh()
            return self._send(200, json.dumps({"prompt": AI.make_prompt(q.get("task", "study"), q.get("course", ""), q.get("module", ""), q.get("lesson", ""), q.get("goal", "")),
                                               "root": str(AI.ROOT)}))
        if path == "/api/ai/status":
            AI.ensure_fresh()
            ex = lambda p: p.exists()
            return self._send(200, json.dumps({"root": str(AI.ROOT), "guide": ex(AI.GUIDE), "library": ex(AI.LIBRARY), "index": ex(AI.INDEX),
                                               "findings": AI.rebuild_index() if AI.FIND_DIR.exists() else {"done": 0, "in-progress": 0, "not-started": 0, "total": 0}}))
        if path == "/api/sources":
            return self._send(200, json.dumps(FA.sources()))
        if path == "/api/singles":
            return self._send(200, json.dumps(list_singles()))
        self._send(404, "{}")

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, json.dumps({"error": "forbidden"}))
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        p = self.path
        res = {"ok": True}
        if p == "/api/start":
            res["ok"] = start(body)
        elif p == "/api/stop":
            stop()
        elif p == "/api/add-course":
            name, msg = pick_folder()
            res.update(name=name, msg=msg)
        elif p == "/api/ai/refresh":
            res.update(AI.write_all())
        elif p == "/api/findings/new":
            L = next((l for l in AI.all_lessons() if l["rel"] == str(body.get("rel", ""))), None)
            if L is None:
                res.update(ok=False, error="lesson not found")
            else:
                fp, created = AI.ensure_findings(L)
                AI.rebuild_index()
                FA.invalidate()
                res.update(path=AI.rel_to_root(fp), created=created)
        elif p == "/api/delete-preview":
            try:
                res.update(FA.plan(body.get("items") or []))
            except (ValueError, OSError) as e:
                res.update(ok=False, error=str(e))
        elif p == "/api/delete":
            with lock:
                busy = state["running"]
            if busy:
                res.update(ok=False, error="A job is running. Stop it or wait for it to finish first.")
            else:
                try:
                    res.update(FA.delete(body.get("items") or []))
                except (ValueError, OSError) as e:
                    res.update(ok=False, error=str(e))
                _scan_cache["t"] = 0
        elif p == "/api/reveal":
            try:
                FA.reveal(str(body.get("root", "")), str(body.get("rel", "")))
            except (ValueError, OSError) as e:
                res.update(ok=False, error=str(e))
        elif p == "/api/clear-missing":
            with lock:
                busy = state["running"]
            if busy and not body.get("dry_run"):
                res.update(ok=False, error="A job is running. Wait for it to finish first.")
            else:
                res.update(names=clear_missing(bool(body.get("dry_run"))))
        elif p == "/api/remove-single":
            res.update(ok=remove_single(str(body.get("name", ""))))
        elif p == "/api/pick-files":
            added, skipped, msg = pick_files()
            res.update(added=added, skipped=skipped, msg=msg)
        elif p == "/api/remove-course":
            msg = remove_course(str(body.get("name", "")))
            res.update(ok=msg == "removed", msg=msg)
        elif p == "/api/open":
            res["ok"] = open_path(str(body.get("what", "")), str(body.get("name", "")))
        elif p == "/api/update-downloader":
            py = str(DL_PY) if DL_PY.exists() else sys.executable
            r = subprocess.run([py, "-m", "pip", "install", "-q", "-U", "yt-dlp"], capture_output=True, text=True)
            v = subprocess.run([py, "-c", "import yt_dlp;print(yt_dlp.version.__version__)"],
                               capture_output=True, text=True).stdout.strip()
            res.update(ok=r.returncode == 0, msg=f"yt-dlp {v}" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["failed"])[-1])
        elif p == "/api/retag":
            r = subprocess.run([sys.executable, str(SCRIPT), "--retag"], cwd=str(BASE), capture_output=True, text=True)
            res.update(ok=r.returncode == 0, msg=(r.stdout or r.stderr).strip().splitlines()[-1:] or [""])
        elif p == "/api/quit":
            self._send(200, json.dumps(res))
            stop()
            threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
            return
        else:
            return self._send(404, "{}")
        self._send(200, json.dumps(res))


def already_running():
    for port in PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4) as c:
                c.sendall(b"GET /api/ping HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                if b"transcriber-gui" in c.recv(2048):
                    return port
        except OSError:
            continue
    return None


def main():
    port = already_running()
    if port:
        if not os.environ.get("TRANSCRIBER_NO_BROWSER"):
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    srv = None
    for port in PORTS:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            if already_running() == port:      # a second launch raced us: just reuse the first
                return
            continue
    if not srv:
        sys.exit("No free port between 8765 and 8775.")
    url = f"http://127.0.0.1:{port}/"
    print(f"Transcriber control panel running at {url}  (Quit from the page, or Ctrl-C)", flush=True)
    if not os.environ.get("TRANSCRIBER_NO_BROWSER"):
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
