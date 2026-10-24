#!/usr/bin/env python3
"""M4.5 provenance backfill for QE-script dialogue (the 出处未定 bucket).

These TextMap strings are referenced by no ExcelBinOutput table, but they DO
appear inside BinOutput/Talk/{Quest,Npc,Activity,...}/<id>.json dialogue rows
(spot check: 13/15 sampled hashes hit). This resolver:

  1. maps genshin.db docs with source=出处未定 back to their TextMap ids
     (exact stripped-text match; duplicate texts keep all ids),
  2. walks every BinOutput/Talk file, finds target textmap ids inside
     dialogue elements, and records the context (file kind + id) and the
     speaker role of that element,
  3. resolves human-readable labels:
       Quest/<questId>.json   -> QuestExcelConfigData.titleTextMapHash 任务「…」
       Npc/<npcConfigId>.json -> NpcExcelConfigData.nameTextMapHash     NPC对话「…」
       other kinds            -> <kind>#<id>
     speakers: TALK_ROLE_NPC -> NpcExcelConfigData name (TextMap_Medium first),
               TALK_ROLE_PLAYER -> 旅行者, NARRATOR -> 旁白.
  4. writes index/qe_src.db  (qe(id INTEGER PRIMARY KEY, source TEXT, speaker TEXT))
     consumed by build_index.py when it emits the orphan section.

Usage: python3 scripts/resolve_qe.py [--repo data/repo] [--db index/genshin.db]
                                     [--out index/qe_src.db]
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

KIND_LABELS = {
    "Activity": "活动对话",
    "ActivityGroup": "活动对话组",
    "Coop": "多人任务对话",
    "Cutscene": "剧情演出",
    "Storyboard": "故事板剧情",
    "Gadget": "物件对话",
    "GadgetGroup": "物件对话组",
    "Blossom": "地脉对话",
    "FreeGroup": "自由对话组",
    "FurnitureGroup": "家具对话",
    "NpcOther": "NPC附加对话",
    "NpcGroup": "NPC对话组",
    "QuestGroup": "任务对话组",
}
# context priority when one string appears in several talk files
KIND_PRIORITY = {"Quest": 0, "Npc": 1, "NpcGroup": 2, "QuestGroup": 2,
                 "Cutscene": 3, "Storyboard": 4, "Coop": 5}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_tm_id(o, tm_keys):
    if isinstance(o, int) and not isinstance(o, bool):
        return o if o in tm_keys else None
    if isinstance(o, str) and o.isdigit() and len(o) > 9:
        v = int(o)
        return v if v in tm_keys else None
    return None


def find_roles(d):
    """Collect TALK_ROLE_* / NARRATOR role refs nested inside element dict d."""
    roles = []
    stack = [d]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            t = o.get("type")
            if isinstance(t, str) and (t.startswith("TALK_ROLE") or t == "NARRATOR"):
                roles.append((t, str(o.get("id", ""))))
            else:
                stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return roles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(ROOT, "data", "repo"))
    ap.add_argument("--db", default=os.path.join(ROOT, "index", "genshin.db"))
    ap.add_argument("--out", default=os.path.join(ROOT, "index", "qe_src.db"))
    args = ap.parse_args()

    # 1) unreferenced bodies -> textmap ids
    print("collecting 出处未定 bodies...")
    con = sqlite3.connect(args.db)
    bodies = {b for (b,) in con.execute(
        "SELECT body FROM docs WHERE source='出处未定'")}
    print(f"  {len(bodies)} bodies")

    print("loading TextMapCHS...")
    tm = load_json(os.path.join(args.repo, "TextMap", "TextMapCHS.json"))
    targets = set()
    for k, v in tm.items():
        if v.strip() in bodies:
            targets.add(int(k))
    tm_keys = targets  # only search for ids we care about
    print(f"  {len(targets)} textmap ids targeted")

    # medium textmap for short npc labels (same fallback order as build_index)
    medium = {}
    mpath = os.path.join(args.repo, "TextMap", "TextMap_MediumCHS.json")
    if os.path.exists(mpath):
        medium = load_json(mpath)

    def tm_text(h):
        return (medium.get(str(h)) or tm.get(str(h)) or "").strip()

    # 2) config joins
    print("loading quest/npc configs...")
    main_title = {}   # MainQuestExcelConfigData id -> titleTextMapHash
    for row in load_json(os.path.join(args.repo, "ExcelBinOutput",
                                      "MainQuestExcelConfigData.json")):
        if isinstance(row, dict) and isinstance(row.get("id"), int) \
                and isinstance(row.get("titleTextMapHash"), int):
            main_title[row["id"]] = row["titleTextMapHash"]
    sub2main = {}     # QuestExcelConfigData subId -> mainId (Talk/Quest files
                      # are named by subId, e.g. 100001.json)
    for row in load_json(os.path.join(args.repo, "ExcelBinOutput",
                                      "QuestExcelConfigData.json")):
        if isinstance(row, dict) and isinstance(row.get("subId"), int) \
                and isinstance(row.get("mainId"), int):
            sub2main[row["subId"]] = row["mainId"]
    npc_name = {}
    for row in load_json(os.path.join(args.repo, "ExcelBinOutput",
                                      "NpcExcelConfigData.json")):
        if isinstance(row, dict) and isinstance(row.get("id"), int) \
                and isinstance(row.get("nameTextMapHash"), int):
            npc_name[row["id"]] = row["nameTextMapHash"]
    print(f"  {len(sub2main)} quest subIds / {len(main_title)} main titles, {len(npc_name)} npcs")

    def speaker_name(t, rid):
        if t == "TALK_ROLE_PLAYER":
            return "旅行者"
        if t == "NARRATOR":
            return "旁白"
        if t == "TALK_ROLE_NPC" and rid.isdigit():
            h = npc_name.get(int(rid))
            if h:
                nm = tm_text(h)
                if nm and len(nm) <= 40:
                    return nm
        return ""

    def ctx_label(kind, cid):
        if kind == "Quest" and cid.isdigit() and int(cid) in sub2main:
            h = main_title.get(sub2main[int(cid)])
            if h:
                t = tm_text(h)
                if t and len(t) <= 60:
                    return f"任务「{t}」"
        if kind in ("Npc", "NpcOther") and cid.isdigit() and int(cid) in npc_name:
            t = tm_text(npc_name[int(cid)])
            if t and len(t) <= 40:
                return f"NPC对话「{t}」"
        return f"{KIND_LABELS.get(kind, kind)}#{cid}"

    # 3) walk Talk tree
    hits = defaultdict(list)  # textmap id -> [(prio, label, speaker)]
    talk = os.path.join(args.repo, "BinOutput", "Talk")
    files = 0
    kinds = defaultdict(int)
    for kind in sorted(os.listdir(talk)):
        kd = os.path.join(talk, kind)
        if not os.path.isdir(kd):
            continue
        for fn in os.listdir(kd):
            if not fn.endswith(".json"):
                continue
            files += 1
            path = os.path.join(kd, fn)
            try:
                data = load_json(path)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            cid = fn[:-5]
            prio = KIND_PRIORITY.get(kind, 9)
            label = ctx_label(kind, cid)
            # find dialogue-element dicts that directly contain target ids
            stack = [data]
            while stack:
                o = stack.pop()
                if isinstance(o, dict):
                    direct = set()
                    for v in o.values():
                        m = is_tm_id(v, tm_keys)
                        if m is not None:
                            direct.add(m)
                        elif isinstance(v, (dict, list)):
                            stack.append(v)
                    if direct:
                        spk = ""
                        for t, r in find_roles(o):
                            nm = speaker_name(t, r)
                            if nm:
                                spk = nm
                                break
                        for mid in direct:
                            hits[mid].append((prio, label, spk))
                elif isinstance(o, list):
                    stack.extend(o)
        print(f"  {kind}: total files so far {files}", flush=True)

    # 4) aggregate + write
    print(f"walked {files} files; matched {len(hits)} textmap ids")
    if os.path.exists(args.out):
        os.remove(args.out)
    out = sqlite3.connect(args.out)
    out.execute("CREATE TABLE qe(id INTEGER PRIMARY KEY, source TEXT, speaker TEXT)")
    n = 0
    with_role = 0
    for mid, occ in hits.items():
        occ.sort(key=lambda x: x[0])
        labels = []
        for _, lbl, _s in occ:
            if lbl not in labels:
                labels.append(lbl)
            if len(labels) == 3:
                break
        speakers = []
        for _, _, s in occ:
            if s and s not in speakers:
                speakers.append(s)
            if len(speakers) == 4:
                break
        out.execute("INSERT INTO qe VALUES (?,?,?)",
                    (mid, "｜".join(labels), "、".join(speakers)))
        n += 1
        with_role += 1 if speakers else 0
    out.commit()
    print(f"wrote {n} rows ({with_role} with speaker) -> {args.out}")
    miss = len(targets) - len(hits)
    print(f"targeted {len(targets)}, matched {len(hits)}, still 出处未定 {miss} "
          f"({100.0 * len(hits) / max(len(targets), 1):.1f}% resolved)")


if __name__ == "__main__":
    main()
