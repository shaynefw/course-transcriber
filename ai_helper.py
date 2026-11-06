"""
Helpers for pointing an AI assistant at your material.

  * AI-GUIDE.md   how the folders and files are laid out and how to take notes (generated per computer, so the
                  paths are always right for the machine the panel is running on)
  * LIBRARY.md    a compact map of every course / module / lesson and what exists for it
  * findings/     one small notes file per lesson (<ID>-findings.md) so an AI keeps what it learned between
                  sessions instead of re-reading transcripts, plus findings/_INDEX.md

Used by the panel's AI tab and by findings.py (the command-line helper). Standard library only.
"""
import hashlib
import re
import shlex
import time
from pathlib import Path

import transcribe as T

ROOT = T.BASE
FIND_DIR = ROOT / "findings"
GUIDE = ROOT / "AI-GUIDE.md"
LIBRARY = ROOT / "LIBRARY.md"
INDEX = FIND_DIR / "_INDEX.md"
SETS = [("combined", "snapshots-combined", "COMBINED"), ("visual", "snapshots-visual", "VISUAL-ONLY"), ("all", "snapshots", "OVERVIEW")]
STATUSES = ("not-started", "in-progress", "done")
WEB, SINGLE = "Web videos", "Single files"


# ----------------------------------------------------------------- naming
def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-") or "item"


def h6(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]


def course_slug(course: str) -> str:
    """Short folder name for a course: 'P01 - Photography Basics' -> 'P01'."""
    if course == SINGLE:
        return "SINGLE"
    if course == WEB:
        return "WEB"
    if not course:
        return "LOOSE"
    m = re.match(r"^([A-Za-z]{1,4}\d{1,3})\b", course)
    return m[1].upper() if m else slug(course, 20).upper()


def lesson_id(title: str, rel: str) -> str:
    """Short unique-ish id: 'P01 - 02 - Reading a Histogram' -> 'P01-02'; otherwise a slug plus a short hash."""
    m = re.match(r"^([A-Za-z]{1,4}\d{1,3})\s*[-–_.: ]\s*(\d{1,3})\b", title)
    if m:
        return f"{m[1].upper()}-{int(m[2]):02d}"
    return f"{slug(title, 36)}-{h6(rel)}"


def read_header(p: Path) -> dict:
    """The small 'key: value' block between the --- lines at the top of a findings file, plus a summary line."""
    out = {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    if lines and lines[0].strip() == "---":
        for ln in lines[1:30]:
            if ln.strip() == "---":
                break
            k, _, v = ln.partition(":")
            if _:
                out[k.strip()] = v.split("#")[0].strip()
    grab = False
    for ln in lines:
        if ln.strip().lower().startswith("## summary"):
            grab = True
            continue
        if grab:
            t = ln.strip()
            if t.startswith("## "):
                break
            if t and not t.startswith("<!--"):
                out["summary"] = t.lstrip("-* ").strip()[:160]
                break
    return out


def findings_path(L: dict) -> Path:
    cs, lid = course_slug(L["course"]), lesson_id(L["title"], L["rel"])
    p = FIND_DIR / cs / f"{lid}-findings.md"
    if p.exists():
        src = read_header(p).get("source")
        if src and src != L["rel"]:                       # same short id used by another lesson: keep them apart
            p = FIND_DIR / cs / f"{lid}-{h6(L['rel'])}-findings.md"
    return p


def findings_status(L: dict):
    p = findings_path(L)
    if not p.exists():
        return None
    h = read_header(p)
    return {"status": h.get("status", "in-progress"), "updated": h.get("updated", ""), "path": p.relative_to(ROOT).as_posix()}


def rel_to_root(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def safe_module_name(module: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", module).strip() or "module"


# -------------------------------------------------------------- material
def material(L: dict) -> dict:
    """What exists on disk for a lesson, as paths relative to the tool folder."""
    rel, out = L["rel"], {}
    if L.get("transcript"):
        out["transcript"] = f"transcripts/{rel}.txt"
        out["timestamps"] = f"transcripts/{rel}.timestamps.txt"
        out["cues"] = f"transcripts/{rel}.visual-cues.txt"
        b = ROOT / "transcripts" / L["course"] / "_bundles" / (safe_module_name(L["module"]) + ".md")
        if b.exists():
            out["bundle"] = rel_to_root(b)
    out["snapshots"] = {name: {"dir": f"{d}/{rel}/", "images": L["snaps"][name]["count"]} for name, d, _ in SETS if name in L["snaps"]}
    return out


def today() -> str:
    return time.strftime("%Y-%m-%d")


def stub_text(L: dict) -> str:
    m, lid = material(L), lesson_id(L["title"], L["rel"])
    w = [f"---", f"lesson: {L['title']}", f"id: {lid}", f"source: {L['rel']}", "status: not-started   # not-started | in-progress | done",
         f"updated: {today()}", "---", f"# {lid} · {L['title']}", "",
         "## Where the material is (paths relative to the Transcriber folder)"]
    if "transcript" in m:
        w += [f"- transcript (clean text): {m['transcript']}", f"- timestamps ([VISUAL] lines mark something on screen): {m['timestamps']}", f"- visual cues only: {m['cues']}"]
        if "bundle" in m:
            w.append(f"- whole module in one file: {m['bundle']}")
    else:
        w.append("- (no transcript yet)")
    for name, d, label in SETS:
        if name in m["snapshots"]:
            w.append(f"- snapshots, {label.lower()} set ({m['snapshots'][name]['images']} images): {m['snapshots'][name]['dir']}  (list: {m['snapshots'][name]['dir']}_snapshots.txt)")
    w += ["", "## Summary", "<!-- 3-5 lines: what this lesson teaches -->", "",
          "## Key rules, definitions and numbers", "<!-- one bullet each; end with the source, e.g. [00:04:37] or image 00-04-37.jpg -->", "",
          "## What the screenshots showed", "<!-- images you actually looked at: file name and what it shows -->", "",
          "## Still to check / open questions", ""]
    return "\n".join(w)


def ensure_findings(L: dict):
    p = findings_path(L)
    if p.exists():
        return p, False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(stub_text(L), encoding="utf-8")
    return p, True


def rebuild_index() -> dict:
    stats = {"done": 0, "in-progress": 0, "not-started": 0, "total": 0}
    groups = {}
    if FIND_DIR.exists():
        for p in sorted(FIND_DIR.rglob("*-findings.md"), key=lambda x: T.natural_key(str(x))):
            h = read_header(p)
            st = h.get("status", "in-progress")
            st = st if st in STATUSES else "in-progress"
            stats[st] += 1
            stats["total"] += 1
            groups.setdefault(p.parent.name, []).append(
                f"- [{st}] {h.get('id', p.stem.replace('-findings', ''))} · {h.get('lesson', '')} · updated {h.get('updated', '?')}"
                f"{' · ' + h['summary'] if h.get('summary') else ''}  → {rel_to_root(p)}")
    out = ["# Findings index", "",
           f"Generated {time.strftime('%Y-%m-%d %H:%M')}. {stats['done']} done · {stats['in-progress']} in progress · {stats['not-started']} not started.",
           "Read this file at the start of a session instead of opening every findings file. Open a lesson's file only when you need its detail.", ""]
    for g, lines in groups.items():
        out += [f"## {g}", *lines, ""]
    if not groups:
        out.append("(no findings files yet)")
    FIND_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text("\n".join(out) + "\n", encoding="utf-8")
    return stats


# ---------------------------------------------------------------- library
def _tree():
    import files_api as FA
    return FA.tree(force=True)


def build_library(tree=None) -> str:
    tree = tree or _tree()
    lessons = [l for c in tree["courses"] for m in c["modules"] for l in m["lessons"]]
    words = sum(l.get("words") or 0 for l in lessons)
    imgs = sum(s.get("count", 0) for l in lessons for s in l["snaps"].values())
    fs = [findings_status(l) for l in lessons]
    out = ["# LIBRARY: map of the material", "",
           f"Generated {time.strftime('%Y-%m-%d %H:%M')} on this computer. Root folder: {ROOT}",
           f"{sum(1 for l in lessons if l['transcript'])} lessons transcribed · {words:,} words · {imgs:,} snapshot images · findings: "
           f"{sum(1 for f in fs if f and f['status'] == 'done')} done, {sum(1 for f in fs if f and f['status'] != 'done')} in progress.",
           "", "Read only the sections you need (search for a course or module name). File locations follow the patterns in AI-GUIDE.md: "
           "a lesson's files are `transcripts/<course>/<module>/<lesson>.txt` (and `.timestamps.txt`, `.visual-cues.txt`) and "
           "`<snapshot set>/<course>/<module>/<lesson>/`. Lessons directly inside a course folder have no `<module>` level.", ""]
    for c in tree["courses"]:
        n = sum(len(m["lessons"]) for m in c["modules"])
        out += [f"## {c['name'] or '(loose files)'}  ({n} lessons)"]
        if c["index"]:
            out.append(f"index: transcripts/{c['name']}/INDEX.md")
        for m in c["modules"]:
            title = m["module"] if m["path"] else "(lessons directly in this folder)"
            out += [f"### {title}  ({len(m['lessons'])} lessons)"]
            if m["bundle"]:
                out.append(f"bundle (all lessons in one file): transcripts/{c['name']}/_bundles/{safe_module_name(m['module'])}.md")
            for l in m["lessons"]:
                snaps = " ".join(f"{k[0].upper()}{v['count']}" for k, v in sorted(l["snaps"].items()))
                f = findings_status(l)
                bits = [l["title"]]
                bits.append(f"{int((l['dur'] or 0) // 60)}:{int((l['dur'] or 0) % 60):02d} · {l['words']}w · ★{l['cues']}" if l["transcript"] else "no transcript")
                bits.append(f"snaps: {snaps}" if snaps else "no snaps")
                bits.append(f"findings: {f['status']}" if f else "findings: none")
                out.append("- " + " | ".join(bits))
            out.append("")
    out += ["Legend: ★n = lines where the speaker is probably showing something on screen · snaps: C = combined set, V = visual-only set, "
            "A = overview set, followed by image count."]
    return "\n".join(out) + "\n"


def build_guide() -> str:
    py = "python3"
    cmd = f"{py} {shlex.quote(str(ROOT / 'findings.py'))}"
    return f"""# AI GUIDE: how to work with this material

Generated {time.strftime('%Y-%m-%d %H:%M')} by the Transcriber panel for THIS computer.
**Root folder: `{ROOT}`**  (all other paths below are relative to it)
If the folder has moved, open the Transcriber panel → AI tab → Refresh, or run `{cmd} guide` to regenerate this file with the right paths.

## What this is
Course videos and audio were transcribed locally, and screenshots were taken of the video around the moments where the speaker shows
something on screen. You do not need the videos: study the transcripts and screenshots. The user will ask you to study, summarise,
check or answer questions about this material.

## Where things are
| What | Where |
|---|---|
| Map of everything (courses, modules, lessons, what exists) | `LIBRARY.md` |
| Your own notes from earlier sessions | `findings/_INDEX.md` (index) and `findings/<course>/<ID>-findings.md` |
| Clean transcript of a lesson | `transcripts/<course>/<module>/<lesson>.txt` |
| Transcript with timestamps | `transcripts/<course>/<module>/<lesson>.timestamps.txt`: one line per spoken segment, `[HH:MM:SS] text`. A line starting `[VISUAL]` means the speaker is probably pointing at / showing something on screen. |
| Only the visual-cue lines | `transcripts/<course>/<module>/<lesson>.visual-cues.txt` |
| A whole module in one file (timestamps included) | `transcripts/<course>/_bundles/<module>.md` |
| Course index (durations, word counts, cue counts) | `transcripts/<course>/INDEX.md` |
| Screenshots, best set first | `snapshots-combined/` (bursts at every visual cue + background frames) → `snapshots-visual/` (bursts at visual cues only) → `snapshots/` (overview every few seconds), each as `<set>/<course>/<module>/<lesson>/` |
| Screenshot file names | `HH-MM-SS.jpg` is the video time. `_VISUAL` in the name = taken at a visual cue. |
| Which words were being said at each screenshot | `_snapshots.txt` inside each snapshot folder (`file   [HH:MM:SS] spoken line`) |

`<course>` is the folder the user added, `<module>` is a subfolder (lessons directly inside the course folder have no module level), and
`Single files` and `Web videos` are sources that work like courses. A lesson may be missing some of these (see `LIBRARY.md`).

## Study efficiently (this saves your context)
1. Start by reading `LIBRARY.md` (only the parts you need) and `findings/_INDEX.md`. Do NOT open every file.
2. For a lesson: open its findings file first. If its status is `done`, rely on the notes and open the transcript only to verify a detail or quote.
3. Read the transcript in order (`.timestamps.txt`, or the module bundle when covering a whole module). Don't paste large parts of it into your replies.
4. Look at screenshots where it matters: at every `[VISUAL]` line, and whenever the speaker says things like "as you can see", "right here", "this line". Use the
   timestamp to pick the nearest `HH-MM-SS.jpg`, or read `_snapshots.txt` to see which image goes with which sentence. Look at the image itself; don't guess from the words.
5. To find something by keyword: `grep -rin "keyword" transcripts/<course>/ --include='*.timestamps.txt'`, then go to those timestamps.
6. Write down what you learn as you go (below) instead of keeping it in the conversation.

## Your notes: one findings file per lesson
- Location: `findings/<course-short>/<ID>-findings.md`, e.g. lesson "P01 - 02 - Reading a Histogram" → `findings/P01/P01-02-findings.md`.
  The ID is the course/module prefix and lesson number from the file name (for other names it is a short slug plus a hash).
- Create one (it pre-fills where the lesson's files are):  `{cmd} new "P01-02"`  (a unique part of the lesson name also works).
  If you can't run commands, create the file yourself using the template below.
- Other commands:  `{cmd} path "<lesson>"`  (show the lesson's file paths) ·  `{cmd} list`  (status of every findings file) ·
  `{cmd} index`  (rebuild `findings/_INDEX.md`; do this after finishing a lesson or module) ·  `{cmd} guide`  (regenerate this guide and `LIBRARY.md`).
- Keep each file short (under about 150 lines): the point is a compact, reliable memory. Use bullets. End every fact with its source,
  like `[00:04:37]` or `image 00-04-37.jpg`, so it can be re-checked.
- Update the header as you work: `status: not-started | in-progress | done` and `updated: YYYY-MM-DD`.
- Record what you were unsure about under "Still to check", so the next session can pick it up.

Template:
```
---
lesson: <full lesson title>
id: <ID>
source: <course>/<module>/<lesson>        # path without extension, as in LIBRARY.md
status: in-progress                      # not-started | in-progress | done
updated: YYYY-MM-DD
---
# <ID> · <lesson title>
## Where the material is        (paths relative to the root folder)
## Summary                       (3-5 lines)
## Key rules, definitions and numbers
## What the screenshots showed   (image file name + what it shows)
## Still to check / open questions
```

## Rules
- Only write inside `findings/`. Never edit, move or delete transcripts, snapshots, videos or any other file.
- Don't invent. If the material doesn't say something, say so. Quote or cite timestamps/images for important claims.
- The transcripts are speech-to-text: names, numbers and jargon can be mis-heard. Cross-check against screenshots when a number or level matters.
"""


# ---------------------------------------------------------------- prompts
TASKS = {
    "study": ("STUDY AND LEARN",
              "Learn this material thoroughly and keep notes so we never have to redo the work. Go lesson by lesson, in order. For each lesson: "
              "create or open its findings file, read the transcript, look at the screenshots wherever the transcript has [VISUAL] markers, and "
              "record concise findings (rules, definitions, numbers, examples, and what the screenshots showed). When a lesson is finished set "
              "`status: done`. After each module run the index command and give me a short summary (10 lines max)."),
    "resume": ("CONTINUE FROM YOUR NOTES",
               "Continue where you left off. Read the findings index, pick the lessons in my focus that are not-started or in-progress, and carry on "
               "as in a normal study pass. Do not re-read transcripts for lessons already marked done unless I ask. Tell me what's left when you stop."),
    "ask": ("ANSWER FROM THE MATERIAL",
            "Answer my questions using only this material. Check your findings first; open the transcripts or screenshots only to verify specifics. "
            "Cite timestamps and image names, and say plainly when the material doesn't cover something. Wait for my question after you've oriented yourself."),
}


def _focus(tree, course, module_path, lesson_rel):
    """-> (heading, [lines]) describing what the AI should concentrate on, with absolute paths."""
    lines = []
    cs = next((c for c in tree["courses"] if c["name"] == course), None) if course else None
    if lesson_rel:
        L = next((l for c in tree["courses"] for m in c["modules"] for l in m["lessons"] if l["rel"] == lesson_rel), None)
        if L:
            m = material(L)
            lines = [f"Lesson: {L['title']}", f"  course: {L['course'] or '(loose)'}" + (f" · module: {L['module']}" if L["module_path"] else "")]
            for k, label in (("transcript", "transcript"), ("timestamps", "timestamps"), ("cues", "visual cues")):
                if k in m:
                    lines.append(f"  {label}: {ROOT / m[k]}")
            for name, d, lab in SETS:
                if name in m["snapshots"]:
                    lines.append(f"  snapshots ({lab.lower()}, {m['snapshots'][name]['images']} images): {ROOT / m['snapshots'][name]['dir']}")
            lines.append(f"  your notes for it: {findings_path(L)}")
            return "ONE LESSON", lines
    if cs and module_path is not None and module_path != "":
        mod = next((m for m in cs["modules"] if m["path"] == module_path), None)
        if mod:
            lines = [f"Module: {mod['module']}  (course: {cs['name']}, {len(mod['lessons'])} lessons)"]
            if mod["bundle"]:
                lines.append(f"  whole module in one file: {ROOT / 'transcripts' / cs['name'] / '_bundles' / (safe_module_name(mod['module']) + '.md')}")
            lines += [f"  - {l['title']}" for l in mod["lessons"][:60]]
            return "ONE MODULE", lines
    if cs:
        n = sum(len(m["lessons"]) for m in cs["modules"])
        lines = [f"Course: {cs['name'] or '(loose files)'}  ({len(cs['modules'])} module(s), {n} lessons)"]
        if cs["index"]:
            lines.append(f"  course index: {ROOT / 'transcripts' / cs['name'] / 'INDEX.md'}")
        lines += [f"  - {m['module'] if m['path'] else '(lessons directly in the folder)'}: {len(m['lessons'])} lessons" for m in cs["modules"][:60]]
        return "ONE COURSE", lines
    n = sum(len(m["lessons"]) for c in tree["courses"] for m in c["modules"])
    return "THE WHOLE LIBRARY", [f"All courses and modules listed in LIBRARY.md ({n} lessons in total). Work through them in the order they appear."]


def make_prompt(task="study", course="", module_path="", lesson_rel="", goal="", tree=None) -> str:
    tree = tree or _tree()
    ttl, body = TASKS.get(task, TASKS["study"])
    heading, flines = _focus(tree, course, module_path, lesson_rel)
    cmd = f"python3 {shlex.quote(str(ROOT / 'findings.py'))}"
    out = [
        "You are helping me study course material that a local tool has already transcribed and screenshotted. Everything is on this computer.",
        "",
        "START HERE",
        f"1. Read {GUIDE} first. It explains the folder layout, the file formats and how to keep notes.",
        f"   (If that path doesn't exist because the folder moved, find it with: find ~ -maxdepth 6 -name AI-GUIDE.md 2>/dev/null)",
        f"2. Then read {LIBRARY} (a map of every course, module and lesson; read only the parts you need) "
        f"and {INDEX} if it exists (your notes from earlier sessions).",
        "",
        f"TASK: {ttl}",
        body,
        "",
        f"FOCUS: {heading}",
        *flines,
    ]
    if goal.strip():
        out += ["", "MY GOAL / QUESTION", goal.strip()]
    out += ["", "NOTES (so the conversation stays small)",
            f"- Keep what you learn in one findings file per lesson, in {FIND_DIR}/<course>/<ID>-findings.md.",
            f"  Create one with: {cmd} new \"<lesson id or part of its name>\"   (e.g. new \"P01-02\"), and refresh the index with: {cmd} index",
            "- Write only inside the findings folder. Don't modify transcripts, snapshots or videos. Don't paste long transcript sections into the chat."]
    return "\n".join(out)


# ----------------------------------------------------------------- wiring
def write_all(tree=None) -> dict:
    tree = tree or _tree()
    FIND_DIR.mkdir(exist_ok=True)
    GUIDE.write_text(build_guide(), encoding="utf-8")
    LIBRARY.write_text(build_library(tree), encoding="utf-8")
    stats = rebuild_index()
    return {"root": str(ROOT), "guide": rel_to_root(GUIDE), "library": rel_to_root(LIBRARY), "index": rel_to_root(INDEX), "findings": stats}


def ensure_fresh(max_age=120):
    """Regenerate the guide and library if they're missing or stale (they hold this computer's paths)."""
    try:
        age = time.time() - min(GUIDE.stat().st_mtime, LIBRARY.stat().st_mtime)
    except OSError:
        age = 1e9
    if age > max_age or str(ROOT) not in GUIDE.read_text(encoding="utf-8", errors="ignore")[:600]:
        return write_all()
    return None


def all_lessons(tree=None):
    tree = tree or _tree()
    return [l for c in tree["courses"] for m in c["modules"] for l in m["lessons"]]


def find_lessons(query: str, tree=None):
    """Lessons whose id or name contains the query (ignoring case, spaces and punctuation)."""
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
    q = norm(query)
    if not q:
        return []
    ls = all_lessons(tree)
    exact = [l for l in ls if norm(lesson_id(l["title"], l["rel"])) == q]
    return exact or [l for l in ls if q in norm(l["rel"])]
