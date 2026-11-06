"""
File manager for the control panel: browse, read and delete what the tool has produced
(transcripts, snapshot sets, downloaded web videos). Standard library only.

Safety rules (everything goes through resolve_inside / the plan functions):
  * only paths inside the tool's own output folders can be read or deleted,
  * the root folders themselves are never deleted, symlinks are never followed or deleted,
  * course videos you linked in (your originals) are never touched; only files in
    videos/Web videos/ (downloaded by this tool) can be deleted from the "downloads" root.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import ai_helper as AI
import snapshots as SN
import transcribe as T

WEB = "Web videos"
SNAP_ROOTS = {"all": SN.SNAP_DIR, "visual": SN.VIS_DIR, "combined": SN.COMBO_DIR}
IMG_RE = re.compile(r"^\d\d-\d\d-\d\d(_VISUAL)?\.jpg$")
MAX_TEXT = 4_000_000
_cache = {"tree": (0.0, None), "storage": (0.0, None)}


# --------------------------------------------------------------- sources
_dur_cache = {}


def _duration(p: Path):
    """Length in seconds (cached by file size + modified time); None if it can't be read."""
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_size, st.st_mtime_ns)
    if key not in _dur_cache:
        _dur_cache[key] = T.video_seconds(p) or None
    return _dur_cache[key]


def sources():
    """Every video the tool can see in ./videos, with what's been done for it (for the 'what to process' lists)."""
    out = []
    for v in T.list_videos():
        rel = v.relative_to(T.IN_DIR)
        parts = rel.parts
        course = parts[0] if len(parts) > 1 else ""
        module = " / ".join(parts[1:-1]) if len(parts) > 2 else ""
        try:
            size = v.stat().st_size
        except OSError:
            size = None                       # broken link (original moved or deleted)
        out.append({
            "rel": rel.as_posix(), "course": course, "module": module, "title": rel.stem, "size": size,
            "dur": _duration(v) if size else None, "broken": size is None,
            "done_tr": T.out_paths(rel)["txt"].exists(),
            "snaps": {m: SN.is_done(rel, m) for m in ("all", "visual", "combined")},
            "kind": "single" if course == "Single files" else "web" if course == WEB else "course",
        })
    return {"videos": out}


# ------------------------------------------------------------------ paths
def roots():
    return {"transcripts": T.OUT_DIR, "snap-all": SN.SNAP_DIR, "snap-visual": SN.VIS_DIR,
            "snap-combined": SN.COMBO_DIR, "downloads": T.IN_DIR / WEB, "findings": AI.FIND_DIR}


def clean_rel(rel: str) -> str:
    rel = str(rel or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or "\x00" in rel:
        raise ValueError("bad path")
    return "/".join(parts)


def resolve_inside(root: Path, rel: str, allow_root=False) -> Path:
    rel = clean_rel(rel)
    if not rel and not allow_root:
        raise ValueError("empty path")
    base = root.resolve()
    p = (base / rel) if rel else base
    # refuse symlinks anywhere below the root, then make sure we really are inside it
    cur = base
    for part in rel.split("/") if rel else []:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError("symlinks are not followed")
    p = p.resolve()
    if p != base and base not in p.parents:
        raise ValueError("outside the allowed folder")
    return p


def invalidate():
    _cache["tree"] = (0.0, None)
    _cache["storage"] = (0.0, None)


def dir_stats(p: Path):
    """(files, bytes) under p (a file counts as 1 file)."""
    if p.is_file():
        return 1, p.stat().st_size
    n = b = 0
    for dp, dns, fns in os.walk(p):
        for f in fns:
            try:
                b += os.lstat(os.path.join(dp, f)).st_size
                n += 1
            except OSError:
                pass
    return n, b


def safe_module_name(module: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", module).strip() or "module"


def split_rel(rel: str):
    parts = clean_rel(rel).split("/")
    course = parts[0] if len(parts) > 1 else ""
    module_path = "/".join(parts[1:-1])
    module = " - ".join(parts[1:-1]) if len(parts) > 2 else (course or "(root)")
    return course, module_path, module, parts[-1]


# ------------------------------------------------------------------- tree
def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tree(force=False):
    t0, cached = _cache["tree"]
    if cached is not None and not force and time.time() - t0 < 3:
        return cached
    lessons = {}

    def lesson(rel):
        if rel not in lessons:
            course, module_path, module, title = split_rel(rel)
            lessons[rel] = {"rel": rel, "course": course, "module_path": module_path, "module": module,
                            "title": title, "transcript": False, "words": None, "dur": None, "cues": None,
                            "snaps": {}, "download": None}
        return lessons[rel]

    # transcripts
    for p in T.walk_files(T.OUT_DIR):
        n = p.name
        if n.startswith(".") or not n.endswith(".txt") or n.endswith((".timestamps.txt", ".visual-cues.txt")):
            continue
        r = p.relative_to(T.OUT_DIR)
        if "_bundles" in r.parts[:-1]:
            continue
        rel = r.with_suffix("").as_posix()
        L = lesson(rel)
        L["transcript"] = True
        meta = _read_json(p.with_name("." + p.name[:-4] + ".meta.json"))
        L["words"], L["dur"] = meta.get("words"), meta.get("duration")
        cf = p.with_name(p.name[:-4] + ".visual-cues.txt")
        try:
            L["cues"] = sum(1 for ln in cf.read_text(encoding="utf-8").splitlines() if ln.startswith("["))
        except OSError:
            L["cues"] = 0
    # snapshots
    for mode, root in SNAP_ROOTS.items():
        if not root.exists():
            continue
        for dp, dns, fns in os.walk(root):
            if ".done.json" in fns:
                rel = Path(dp).relative_to(root).as_posix()
                if rel in ("", "."):
                    continue
                info = _read_json(Path(dp) / ".done.json")
                lesson(rel)["snaps"][mode] = {"count": info.get("count", 0), "visual": info.get("visual", 0)}
    # downloaded web videos
    webdir = T.IN_DIR / WEB
    if webdir.exists():
        for p in T.walk_files(webdir):
            if p.suffix.lower() in T.VIDEO_EXTS and not p.name.startswith(".") and not p.is_symlink():
                rel = (Path(WEB) / p.relative_to(webdir)).with_suffix("").as_posix()
                try:
                    lesson(rel)["download"] = {"file": p.name, "size": p.stat().st_size}
                except OSError:
                    pass
    items = sorted(lessons.values(), key=lambda x: (T.natural_key(x["course"]), T.natural_key(x["module_path"]),
                                                    T.natural_key(x["title"])))
    for L in items:
        L["has_snaps"] = bool(L["snaps"])
        L["findings"] = AI.findings_status(L)
    courses = {}
    for L in items:
        c = courses.setdefault(L["course"], {"name": L["course"], "index": (T.OUT_DIR / L["course"] / "INDEX.md").exists(),
                                             "modules": {}})
        m = c["modules"].setdefault(L["module_path"], {"path": L["module_path"], "module": L["module"],
                                                       "bundle": (T.OUT_DIR / L["course"] / "_bundles" /
                                                                  (safe_module_name(L["module"]) + ".md")).exists(),
                                                       "lessons": []})
        m["lessons"].append(L)
    out = {"courses": [{"name": c["name"], "index": c["index"], "modules": list(c["modules"].values())}
                       for c in sorted(courses.values(), key=lambda c: T.natural_key(c["name"]))]}
    _cache["tree"] = (time.time(), out)
    return out


def storage(force=False):
    t0, cached = _cache["storage"]
    if cached is not None and not force and time.time() - t0 < 20:
        return cached
    out = {}
    for key, root in roots().items():
        if not root.exists():
            out[key] = {"files": 0, "bytes": 0}
            continue
        n, b = 0, 0
        for dp, dns, fns in os.walk(root):
            for f in fns:
                try:
                    b += os.lstat(os.path.join(dp, f)).st_size
                    n += 1
                except OSError:
                    pass
        out[key] = {"files": n, "bytes": b}
    _cache["storage"] = (time.time(), out)
    return out


# ------------------------------------------------------------------ viewing
def read_text(kind: str, rel: str, module: str = ""):
    """kind: txt | ts | cues | index | bundle. For index, rel is the course; for bundle, rel is the course and
    module is the module name used by the bundle file."""
    if kind in ("txt", "ts", "cues"):
        suffix = {"txt": ".txt", "ts": ".timestamps.txt", "cues": ".visual-cues.txt"}[kind]
        p = resolve_inside(T.OUT_DIR, rel + suffix)
    elif kind in ("aiguide", "library", "findingsindex"):
        AI.ensure_fresh()
        p = {"aiguide": AI.GUIDE, "library": AI.LIBRARY, "findingsindex": AI.INDEX}[kind]
        if not p.is_file():
            return {"text": "", "missing": True}
        return {"text": p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT]}
    elif kind == "findings":
        L = next((l for c in tree()["courses"] for m in c["modules"] for l in m["lessons"] if l["rel"] == clean_rel(rel)), None)
        if L is None:
            return {"text": "", "missing": True}
        p = AI.findings_path(L)
        if not p.is_file():
            return {"text": "", "missing": True}
        return {"text": p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT], "path": AI.rel_to_root(p)}
    elif kind == "index":
        p = resolve_inside(T.OUT_DIR, (clean_rel(rel) + "/" if clean_rel(rel) else "") + "INDEX.md")
    elif kind == "bundle":
        base = clean_rel(rel)
        p = resolve_inside(T.OUT_DIR, (base + "/" if base else "") + "_bundles/" + safe_module_name(module) + ".md")
    else:
        raise ValueError("unknown kind")
    if not p.is_file():
        return {"text": "", "missing": True}
    size = p.stat().st_size
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        text = f.read(MAX_TEXT)
    return {"text": text, "size": size, "truncated": size > MAX_TEXT}


def snap_list(mode: str, rel: str):
    if mode not in SNAP_ROOTS:
        raise ValueError("unknown snapshot set")
    folder = resolve_inside(SNAP_ROOTS[mode], rel)
    if not folder.is_dir():
        return {"images": []}
    said = {}
    try:
        for ln in (folder / "_snapshots.txt").read_text(encoding="utf-8").splitlines():
            if ln.startswith("#") or not ln.strip():
                continue
            name, _, rest = ln.partition("   ")
            said[name.strip()] = rest.strip()
    except OSError:
        pass
    imgs = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name):
        if IMG_RE.match(p.name):
            h, m, s = (int(x) for x in p.name[:8].split("-"))
            imgs.append({"name": p.name, "t": h * 3600 + m * 60 + s, "visual": "_VISUAL" in p.name,
                         "said": said.get(p.name, "")})
    return {"images": imgs}


def image_path(mode: str, rel: str, name: str) -> Path:
    if mode not in SNAP_ROOTS or not IMG_RE.match(name):
        raise ValueError("bad image")
    return resolve_inside(SNAP_ROOTS[mode], clean_rel(rel) + "/" + name)


def reveal(root_key: str, rel: str):
    root = roots().get(root_key)
    if root is None:
        raise ValueError("unknown root")
    p = resolve_inside(root, rel, allow_root=True)
    if not p.exists():
        raise ValueError("not found")
    subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])


# ----------------------------------------------------------------- deleting
def _lesson_transcript_files(rel):
    base = resolve_inside(T.OUT_DIR, rel + ".txt").with_suffix("")      # .../Name  (strip .txt)
    name = base.name
    d = base.parent
    cands = [d / (name + ".txt"), d / (name + ".timestamps.txt"), d / (name + ".visual-cues.txt"), d / ("." + name + ".meta.json")]
    return [c for c in cands if c.exists() and not c.is_symlink()]


def _download_files(rel):
    """Video file(s) in videos/Web videos matching this lesson, plus their source sidecar."""
    rel = clean_rel(rel)
    if not rel.startswith(WEB + "/"):
        return []
    sub = rel[len(WEB) + 1:]
    base = resolve_inside(T.IN_DIR / WEB, sub + ".x").with_suffix("")
    out = []
    if base.parent.is_dir():
        for p in base.parent.iterdir():
            if p.is_file() and not p.is_symlink() and p.stem == base.name and p.suffix.lower() in T.VIDEO_EXTS:
                out.append(p)
                side = p.with_name("." + p.stem + ".source.json")
                if side.exists():
                    out.append(side)
    return out


def targets(item):
    """-> [(label, [paths], root_key)] for one request item {kind: lesson|folder, rel, parts: [...]}"""
    kind, rel, parts = item.get("kind"), clean_rel(item.get("rel", "")), item.get("parts") or []
    out = []
    for part in parts:
        if part == "transcript":
            if kind == "lesson":
                out.append(("Transcript files", _lesson_transcript_files(rel), "transcripts"))
            else:
                paths = [resolve_inside(T.OUT_DIR, rel)]
                segs = rel.split("/")
                if len(segs) >= 2:
                    b = T.OUT_DIR / segs[0] / "_bundles" / (safe_module_name(" - ".join(segs[1:])) + ".md")
                    if b.exists():
                        paths.append(resolve_inside(T.OUT_DIR, "/".join([segs[0], "_bundles", b.name])))
                out.append(("Transcripts, index and bundles", [p for p in paths if p.exists()], "transcripts"))
        elif part in ("snap-all", "snap-visual", "snap-combined"):
            root = roots()[part]
            p = resolve_inside(root, rel)
            out.append((f"Snapshots ({part[5:]})", [p] if p.exists() else [], part))
        elif part == "download":
            if kind == "lesson":
                out.append(("Downloaded video", _download_files(rel), "downloads"))
            else:
                segs = rel.split("/")
                if len(segs) < 2 or segs[0] != WEB:
                    raise ValueError("downloads can only be deleted from inside Web videos")
                p = resolve_inside(T.IN_DIR / WEB, "/".join(segs[1:]))
                out.append(("Downloaded videos", [p] if p.exists() else [], "downloads"))
        else:
            raise ValueError("unknown part")
    return out


def plan(items):
    steps, files, size = [], 0, 0
    for it in items:
        for label, paths, root_key in targets(it):
            n = b = 0
            for p in paths:
                f, by = dir_stats(p)
                n, b = n + f, b + by
            if paths:
                steps.append({"label": label, "rel": it.get("rel"), "root": root_key, "files": n, "bytes": b,
                              "names": [p.name for p in paths][:6]})
            files, size = files + n, size + b
    return {"steps": steps, "files": files, "bytes": size}


def _ids_for_videos(video_files):
    """Download-list ids for these video files. Must run BEFORE they are deleted (it reads their source notes)."""
    ids = set()
    for p in video_files:
        side = p.with_name("." + p.stem + ".source.json")
        info = _read_json(side) if side.exists() else {}
        if info.get("id"):
            ids.add(str(info["id"]))
            continue
        # older downloads: find the link in _sources.txt by title, take the YouTube id from it
        try:
            for ln in (T.IN_DIR / WEB / "_sources.txt").read_text(encoding="utf-8").splitlines():
                cols = ln.split("\t")
                if len(cols) >= 5 and cols[4] and cols[0] and cols[0][:60] in p.stem:
                    ids.add(cols[4])
                elif len(cols) >= 2 and cols[0] and cols[0][:60] in p.stem:
                    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", cols[1])
                    if m:
                        ids.add(m.group(1))
        except OSError:
            pass
    return ids


def _archive_remove(ids):
    """Forget deleted web videos in yt-dlp's download list, so pasting the link again re-downloads it."""
    arch = T.IN_DIR / WEB / ".downloaded.txt"
    if not ids or not arch.exists():
        return
    keep = [ln for ln in arch.read_text(encoding="utf-8").splitlines() if ln.split()[-1:] and ln.split()[-1] not in ids]
    arch.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")


def delete(items):
    removed_files = removed_bytes = 0
    ids = set()
    errors = []
    all_targets = [t for it in items for t in targets(it)]
    for label, paths, root_key in all_targets:           # read download ids before anything is deleted
        if root_key == "downloads":
            for p in paths:
                vids = [p] if p.is_file() else [q for q in p.rglob("*") if q.is_file()]
                ids |= _ids_for_videos([v for v in vids if v.suffix.lower() in T.VIDEO_EXTS])
    for label, paths, root_key in all_targets:
        for p in paths:
            try:
                if p.is_symlink():
                    continue
                root = roots()[root_key].resolve()
                if p.resolve() == root or root not in p.resolve().parents:
                    errors.append(f"refused: {p.name}")
                    continue
                f, b = dir_stats(p)
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                removed_files, removed_bytes = removed_files + f, removed_bytes + b
                _prune_empty_parents(p, root)
            except OSError as e:
                errors.append(f"{p.name}: {e}")
    if ids:
        try:
            _archive_remove(ids)
        except Exception as e:
            errors.append(f"download list: {e}")
    try:
        T.build_outputs()          # refresh INDEX.md and bundles for whatever is left
    except Exception as e:
        errors.append(f"index refresh: {e}")
    invalidate()
    return {"files": removed_files, "bytes": removed_bytes, "errors": errors}


def _prune_empty_parents(p: Path, root: Path):
    """Remove folders left empty by a deletion (never the root itself)."""
    d = p.parent
    while d != root and root in d.parents:
        try:
            if any(x.name != ".DS_Store" for x in d.iterdir()):
                break
            shutil.rmtree(d)
        except OSError:
            break
        d = d.parent
