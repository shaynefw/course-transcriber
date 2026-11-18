"""
"My folders": your own folders for sorting lessons in the FILES tab.

These folders are a LABEL LAYER. They are saved in my-folders.json (next to this file) and never
move, rename or delete a transcript, snapshot or video. Sorting is safe to change at any time.

Data:
  folders: {id: {"name": str, "parent": id | None}}
  assign:  {key: folder id | ""}      key = "c:<channel>"  |  "m:<channel>/<module path>"  |  "l:<lesson rel>"
           "" means "explicitly unsorted" (used to pull one item out of a folder that holds its channel)
A lesson belongs to the folder of its most specific key (lesson, then module, then channel).
Standard library only.
"""
import json
import os
import re
import secrets
import threading
from pathlib import Path

FILE = Path(__file__).resolve().parent / "my-folders.json"
MAX_DEPTH = 8
MAX_FOLDERS = 500
_lock = threading.Lock()
KEY_RE = re.compile(r"^[clm]:.{1,900}$", re.S)


def _blank():
    return {"folders": {}, "assign": {}}


def _load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return _blank()
        d.setdefault("folders", {})
        d.setdefault("assign", {})
        return d
    except (OSError, ValueError):
        return _blank()


def _save(d):
    tmp = FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, FILE)


def _clean_name(name):
    name = re.sub(r"[\x00-\x1f\x7f]", " ", str(name or "")).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        raise ValueError("Give the folder a name.")
    if len(name) > 80:
        raise ValueError("That name is too long (80 characters at most).")
    return name


def _depth(d, fid):
    n = 0
    while fid:
        n, fid = n + 1, d["folders"].get(fid, {}).get("parent")
        if n > MAX_DEPTH + 2:
            break
    return n


def _descendants(d, fid):
    out, stack = set(), [fid]
    while stack:
        cur = stack.pop()
        for k, f in d["folders"].items():
            if f.get("parent") == cur and k not in out:
                out.add(k)
                stack.append(k)
    return out


def _sibling_clash(d, parent, name, skip=None):
    low = name.lower()
    return any(k != skip and f.get("parent") == parent and f["name"].lower() == low for k, f in d["folders"].items())


def _view(d):
    # drop assignments that point to a folder that no longer exists
    ok = set(d["folders"])
    assign = {k: v for k, v in d["assign"].items() if v == "" or v in ok}
    return {"folders": [{"id": k, "name": f["name"], "parent": f.get("parent")} for k, f in d["folders"].items()],
            "assign": assign}


def get():
    with _lock:
        return _view(_load())


def create(name, parent=None):
    name = _clean_name(name)
    parent = parent or None
    with _lock:
        d = _load()
        if parent and parent not in d["folders"]:
            raise ValueError("That parent folder no longer exists.")
        if len(d["folders"]) >= MAX_FOLDERS:
            raise ValueError("Too many folders.")
        if _depth(d, parent) >= MAX_DEPTH:
            raise ValueError(f"Folders can only go {MAX_DEPTH} levels deep.")
        if _sibling_clash(d, parent, name):
            raise ValueError("A folder with that name is already there.")
        fid = "f" + secrets.token_hex(4)
        d["folders"][fid] = {"name": name, "parent": parent}
        _save(d)
        return {"id": fid, **_view(d)}


def rename(fid, name):
    name = _clean_name(name)
    with _lock:
        d = _load()
        f = d["folders"].get(fid)
        if f is None:
            raise ValueError("That folder no longer exists.")
        if _sibling_clash(d, f.get("parent"), name, skip=fid):
            raise ValueError("A folder with that name is already there.")
        f["name"] = name
        _save(d)
        return _view(d)


def move_folder(fid, parent):
    parent = parent or None
    with _lock:
        d = _load()
        f = d["folders"].get(fid)
        if f is None:
            raise ValueError("That folder no longer exists.")
        if parent and parent not in d["folders"]:
            raise ValueError("The target folder no longer exists.")
        if parent == fid or (parent and parent in _descendants(d, fid)):
            raise ValueError("A folder can't go inside itself.")
        if _sibling_clash(d, parent, f["name"], skip=fid):
            raise ValueError("The target already has a folder with this name.")
        sub = max([_depth(d, x) - _depth(d, fid) for x in _descendants(d, fid)] + [0])
        if _depth(d, parent) + 1 + sub > MAX_DEPTH:
            raise ValueError(f"Folders can only go {MAX_DEPTH} levels deep.")
        f["parent"] = parent
        _save(d)
        return _view(d)


def delete_folder(fid):
    """Remove the folder only. Its sub-folders and sorted items move up one level."""
    with _lock:
        d = _load()
        f = d["folders"].get(fid)
        if f is None:
            raise ValueError("That folder no longer exists.")
        up = f.get("parent")
        for k, g in list(d["folders"].items()):
            if g.get("parent") == fid:
                if _sibling_clash(d, up, g["name"], skip=k):
                    g["name"] = g["name"] + " (2)"
                g["parent"] = up
        for k, v in list(d["assign"].items()):
            if v == fid:
                if up:
                    d["assign"][k] = up
                else:
                    del d["assign"][k]
        del d["folders"][fid]
        _tidy(d)
        _save(d)
        return _view(d)


def _under(key, other):
    """True when `other` is strictly below `key` (a channel holds its modules and lessons)."""
    kk, kp = key[0], key[2:]
    ok, op = other[0], other[2:]
    if kk == "c":
        return ok in "ml" and (op == kp or op.startswith(kp + "/")) and kp != ""
    if kk == "m":
        return ok in "ml" and op.startswith(kp + "/")
    return False


def _covered_by(d, key):
    """The folder an ancestor key would put this item in (None if no ancestor key exists)."""
    best = None
    for k, v in d["assign"].items():
        if k != key and _under(k, key):
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return best


def _tidy(d):
    """Drop 'explicitly unsorted' markers that no longer override anything."""
    for k, v in list(d["assign"].items()):
        if v == "" and _covered_by(d, k) is None:
            del d["assign"][k]


def assign(keys, fid):
    fid = fid or None
    keys = [str(k) for k in (keys or [])]
    if not keys or len(keys) > 5000 or any(not KEY_RE.match(k) for k in keys):
        raise ValueError("Nothing valid to move.")
    with _lock:
        d = _load()
        if fid and fid not in d["folders"]:
            raise ValueError("That folder no longer exists.")
        for k in keys:
            for o in [o for o in list(d["assign"]) if _under(k, o)]:      # moving a whole channel/module takes its parts too
                del d["assign"][o]
            d["assign"].pop(k, None)
            if fid:
                d["assign"][k] = fid
            elif _covered_by(d, k) is not None:
                d["assign"][k] = ""                                          # pull it out of the folder that holds its channel
        _tidy(d)
        _save(d)
        return _view(d)
