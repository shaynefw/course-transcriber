#!/usr/bin/env python3
"""
Notes helper for an AI that studies your transcribed material.

    python3 findings.py new "P01-02"      create findings/<course>/P01-02-findings.md (pre-filled with where the lesson's files are)
    python3 findings.py path "P01-02"     show a lesson's file paths (transcript, timestamps, snapshots, notes)
    python3 findings.py list              status of every findings file
    python3 findings.py index             rebuild findings/_INDEX.md (a one-page summary of all notes)
    python3 findings.py guide             regenerate AI-GUIDE.md and LIBRARY.md for this computer
    python3 findings.py prompt            print the copy-paste prompt for your AI (see the panel's AI tab for options)

A lesson can be named by its short ID (P01-02) or by any unique part of its name. Works from any folder.
"""
import argparse
import sys

import ai_helper as AI


def pick(query):
    hits = AI.find_lessons(query)
    if not hits:
        sys.exit(f"No lesson matches “{query}”. Try part of its title, or its ID (like P01-02). See LIBRARY.md.")
    if len(hits) > 1:
        print(f"“{query}” matches {len(hits)} lessons; be more specific:", file=sys.stderr)
        for l in hits[:15]:
            print(f"  {AI.lesson_id(l['title'], l['rel'])}  {l['rel']}", file=sys.stderr)
        sys.exit(2)
    return hits[0]


def main():
    ap = argparse.ArgumentParser(description="Notes helper for an AI studying your material")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("new", "path"):
        p = sub.add_parser(name)
        p.add_argument("lesson", nargs="+", help="lesson ID or part of its name")
    for name in ("list", "index", "guide"):
        sub.add_parser(name)
    p = sub.add_parser("prompt")
    p.add_argument("--task", choices=["study", "resume", "ask"], default="study")
    p.add_argument("--lesson", default="", help="focus on one lesson (ID or part of its name)")
    p.add_argument("--goal", default="")
    a = ap.parse_args()

    if a.cmd == "new":
        L = pick(" ".join(a.lesson))
        p, created = AI.ensure_findings(L)
        print(("Created: " if created else "Already exists: ") + str(p))
        if created:
            AI.rebuild_index()
    elif a.cmd == "path":
        L = pick(" ".join(a.lesson))
        m = AI.material(L)
        print(f"lesson:     {L['title']}\nid:         {AI.lesson_id(L['title'], L['rel'])}")
        for k in ("transcript", "timestamps", "cues", "bundle"):
            if k in m:
                print(f"{k + ':':<11} {AI.ROOT / m[k]}")
        for name, d, label in AI.SETS:
            if name in m["snapshots"]:
                print(f"snapshots ({label.lower()}): {AI.ROOT / m['snapshots'][name]['dir']}  [{m['snapshots'][name]['images']} images]")
        p = AI.findings_path(L)
        print(f"notes:      {p}  [{'exists' if p.exists() else 'not created yet; run: findings.py new'}]")
    elif a.cmd == "list":
        rows = sorted(AI.FIND_DIR.rglob("*-findings.md")) if AI.FIND_DIR.exists() else []
        if not rows:
            print("No findings files yet.")
        for p in rows:
            h = AI.read_header(p)
            print(f"[{h.get('status', '?'):11}] {h.get('id', p.stem):12} {h.get('updated', ''):10}  {h.get('lesson', '')}")
    elif a.cmd == "index":
        s = AI.rebuild_index()
        print(f"Rebuilt {AI.INDEX}: {s['done']} done, {s['in-progress']} in progress, {s['not-started']} not started.")
    elif a.cmd == "guide":
        s = AI.write_all()
        print(f"Wrote {AI.GUIDE}\nWrote {AI.LIBRARY}\nRebuilt {AI.INDEX} ({s['findings']['total']} findings files).")
    elif a.cmd == "prompt":
        AI.ensure_fresh()
        L = pick(a.lesson) if a.lesson else None
        print(AI.make_prompt(a.task, L["course"] if L else "", L["module_path"] if L else "", L["rel"] if L else "", a.goal))


if __name__ == "__main__":
    main()
