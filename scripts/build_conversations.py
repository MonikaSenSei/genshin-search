#!/usr/bin/env python3
"""M4.15 conversation stitching: adjacent dialogue lines -> readable runs.

The Talk tree (BinOutput/Talk/<kind>/<id>.json) stores dialogue as a node
graph: each element's LKECPJIFFEE is its line (TextMap hash) and
GLJCECCOEDP lists the next element(s). Following single-child chains yields
the conversation AS IT PLAYS: consecutive lines, in order, with speakers.
A branch point (player choice / option) ends the run and is flagged so the
UI can say 对话在此分歧.

Output: index/conversations.db
  seq(id INTEGER PRIMARY KEY, kind TEXT, file TEXT, n INT, branch INT,
      body TEXT)   body = JSON [[speaker, text], ...]
  map(text TEXT PRIMARY KEY, seq INT, pos INT)  (first sequence per text)

Consumed by export_static.py: bodies ship as lazy per-chunk JSON under
web/data/conv/, and genshin.bin gains a docIndex -> (seq, pos) column so a
result card can offer 展开对话上下文.

Usage: python3 scripts/build_conversations.py [--repo data/repo]
                                             [--out index/conversations.db]
"""
import argparse
import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(ROOT, "data", "repo"))
    ap.add_argument("--out", default=os.path.join(ROOT, "index",
                                                  "conversations.db"))
    args = ap.parse_args()

    tm = json.load(open(os.path.join(args.repo, "TextMap",
                                     "TextMapCHS.json"), encoding="utf-8"))
    medium = {}
    mpath = os.path.join(args.repo, "TextMap", "TextMap_MediumCHS.json")
    if os.path.exists(mpath):
        medium = json.load(open(mpath, encoding="utf-8"))

    def txt(h):
        return (medium.get(str(h)) or tm.get(str(h)) or "").strip()

    # npc config id -> display name (same dev-scaffold rejection as resolve_qe)
    dev_mark = re.compile(r"\$UNRELEASED|\$HIDDEN|[（(]\s*(?:test|hide)\s*[)）]"
                         r"|(?:^|[\s\-])test", re.I)
    npc_name = {}
    for row in json.load(open(os.path.join(args.repo, "ExcelBinOutput",
                                           "NpcExcelConfigData.json"),
                              encoding="utf-8")):
        if isinstance(row, dict) and isinstance(row.get("id"), int) \
                and isinstance(row.get("nameTextMapHash"), int):
            t = txt(row["nameTextMapHash"])
            if t and len(t) <= 30 and not dev_mark.search(t):
                npc_name[row["id"]] = t

    def speaker_of(el):
        stack = [el]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                t = o.get("type")
                if isinstance(t, str):
                    if t == "TALK_ROLE_PLAYER":
                        return "旅行者"
                    if t == "NARRATOR":
                        return "旁白"
                    if t == "TALK_ROLE_NPC":
                        rid = str(o.get("id", ""))
                        if rid.isdigit():
                            return npc_name.get(int(rid), "")
                else:
                    stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
        return ""

    out = sqlite3.connect(args.out)
    out.execute("DROP TABLE IF EXISTS seq")
    out.execute("DROP TABLE IF EXISTS map")
    out.execute("CREATE TABLE seq(id INTEGER PRIMARY KEY, kind TEXT, "
                "file TEXT, n INT, branch INT, body TEXT)")
    out.execute("CREATE TABLE map(text TEXT PRIMARY KEY, seq INT, pos INT)")

    talk = os.path.join(args.repo, "BinOutput", "Talk")
    n_seq = n_lines = n_files = 0
    for kind in sorted(os.listdir(talk)):
        kd = os.path.join(talk, kind)
        if not os.path.isdir(kd):
            continue
        for fn in sorted(os.listdir(kd)):
            if not fn.endswith(".json"):
                continue
            try:
                d = json.load(open(os.path.join(kd, fn), encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            els = d.get("PCIAMAFDDAA")
            if not isinstance(els, list) or len(els) < 3:
                continue
            n_files += 1
            byid = {e.get("id"): e for e in els
                    if isinstance(e, dict) and e.get("id") is not None}
            if not byid:
                continue
            indeg = {i: 0 for i in byid}
            for e in byid.values():
                for nx in (e.get("GLJCECCOEDP") or []):
                    if nx in indeg:
                        indeg[nx] += 1
            roots = [e.get("id") for e in els if e.get("id") in byid
                     and indeg[e["id"]] == 0] or list(byid)[:1]
            visited = set()
            for r0 in roots:
                if r0 not in byid:
                    continue
                run, cur, branch = [], r0, 0
                while cur in byid and cur not in visited and len(run) < 120:
                    visited.add(cur)
                    e = byid[cur]
                    h = e.get("LKECPJIFFEE")
                    line = txt(h) if isinstance(h, int) else ""
                    if len(line) >= 4:
                        run.append([speaker_of(e), line])
                    nx = [n for n in (e.get("GLJCECCOEDP") or [])
                          if n in byid and n not in visited]
                    if len(nx) == 1:
                        cur = nx[0]
                    else:
                        branch = 1 if len(nx) > 1 else 0
                        break
                if len(run) >= 4:
                    out.execute("INSERT INTO seq VALUES (?,?,?,?,?,?)",
                                (n_seq, kind, fn, len(run), branch,
                                 json.dumps(run, ensure_ascii=False)))
                    for pos, (_sp, t) in enumerate(run):
                        out.execute("INSERT OR IGNORE INTO map VALUES (?,?,?)",
                                    (t, n_seq, pos))
                    n_seq += 1
                    n_lines += len(run)
        print(f"  {kind}: seqs so far {n_seq}", flush=True)
    out.commit()
    mapped = out.execute("SELECT COUNT(*) FROM map").fetchone()[0]
    print(f"files walked: {n_files}; conversations: {n_seq}; "
          f"lines: {n_lines}; distinct texts mapped: {mapped}")


if __name__ == "__main__":
    main()
