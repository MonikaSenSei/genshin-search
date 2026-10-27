#!/usr/bin/env python3
"""M4.5 provenance backfill for QE-script dialogue (the 出处未定 bucket).

These TextMap strings are referenced by no ExcelBinOutput table, but they DO
appear inside BinOutput/Talk/{Quest,Npc,Activity,...}/<id>.json dialogue rows
(spot check: 13/15 sampled hashes hit). This resolver:

  1. targets every story-shaped TextMap id (same filter as build_index's
     orphan section; self-contained, independent of the current index),
  2. walks every BinOutput/Talk file, finds target textmap ids inside
     dialogue elements, and records the context (file kind + id) and the
     speaker role of that element,
  3. resolves human-readable labels:
       Quest/<questId>.json   -> QuestExcelConfigData.titleTextMapHash 任务「…」
         fallback: TalkExcelConfigData_{0,1} registry id -> questId ->
                   MainQuestExcelConfigData.titleTextMapHash 任务「…」
       Npc/<npcConfigId>.json -> NpcExcelConfigData.nameTextMapHash     NPC对话「…」
       NpcGroup/<npcConfigId>.json -> 同上（组 id 就是 npc id）
       Coop/<questSubId>_<n>.json -> quest title 多人任务「…」
       Activity/*             -> talk-registry beginCond ActivityId -> 活动「…」
       FreeGroup/Gadget/...   -> talk-registry questId 任务「…」 else npc 名
       other kinds            -> <kind>#<id>
     speakers: TALK_ROLE_NPC -> NpcExcelConfigData name (TextMap_Medium first),
               TALK_ROLE_PLAYER -> 旅行者, NARRATOR -> 旁白.
  4. resolves Subtitle/CHS/*.srt asset names: embedded quest numbers are
     mapped through the same quest joins -> 过场字幕（任务「…」）
  5. writes index/qe_src.db  (qe(id INTEGER PRIMARY KEY, source TEXT, speaker TEXT),
     subs(asset TEXT PRIMARY KEY, source TEXT)) consumed by build_index.py.

Usage: python3 scripts/resolve_qe.py [--repo data/repo] [--out index/qe_src.db]
"""
import argparse
import json
import os
import re
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
    "Npc": "NPC对话",
    "NpcOther": "NPC附加对话",
    "NpcGroup": "NPC对话组",
    "Quest": "任务对话",
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
    ap.add_argument("--out", default=os.path.join(ROOT, "index", "qe_src.db"))
    args = ap.parse_args()

    # 1) story-shaped TextMap texts -> candidate ids. Self-contained: derived
    # from the TextMap dump with the same story-shape filter build_index uses
    # for its orphan section, NOT from the current index (which would only
    # re-resolve last run's leftovers).
    print("loading TextMapCHS...")
    tm = load_json(os.path.join(args.repo, "TextMap", "TextMapCHS.json"))
    targets = {int(k) for k, v in tm.items()
               if len(v.strip()) >= 6 and re.search(r"[。！？…]", v)}
    tm_keys = targets  # only search for ids we care about
    print(f"  {len(targets)} story-shaped textmap ids targeted")

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

    # talk registry: TalkExcelConfigData rows keyed by talk id — this is the
    # only place that links Talk/{Quest,Activity,FreeGroup,...}/<id>.json file
    # names that are NOT quest subIds back to their quest/npc/activity context.
    talk_reg = {}
    for part in ("TalkExcelConfigData_0.json", "TalkExcelConfigData_1.json"):
        p = os.path.join(args.repo, "ExcelBinOutput", part)
        if not os.path.exists(p):
            continue
        for row in load_json(p):
            if isinstance(row, dict) and isinstance(row.get("id"), int):
                talk_reg[row["id"]] = row
    print(f"  talk registry rows: {len(talk_reg)}")
    act_name = {}
    for row in load_json(os.path.join(args.repo, "ExcelBinOutput",
                                      "ActivityExcelConfigData.json")):
        if isinstance(row, dict) and isinstance(row.get("ActivityId"), int) \
                and isinstance(row.get("NameTextMapHash"), int):
            act_name[row["ActivityId"]] = row["NameTextMapHash"]
    # 2026 dump: ActivityExcelConfigData is a stub (2 rows). The real
    # per-patch activity name table is NewActivityExcelConfigData
    # (activityId -> nameTextMapHash); tab labels live in
    # NewActivityEntryConfigData. Both share one id space with the
    # QUEST_COND_ACTIVITY_CLIENT_COND / ITEM_GIVING_ACTIVED params.
    for part in ("NewActivityExcelConfigData.json",
                 "NewActivityEntryConfigData.json"):
        p = os.path.join(args.repo, "ExcelBinOutput", part)
        if not os.path.exists(p):
            continue
        for row in load_json(p):
            if not isinstance(row, dict):
                continue
            aid = row.get("activityId", row.get("id"))
            h = row.get("nameTextMapHash", row.get("tabNameTextMapHash"))
            if isinstance(aid, int) and isinstance(h, int) \
                    and aid not in act_name:
                act_name[aid] = h
    print(f"  activity names: {len(act_name)}")

    def speaker_name(t, rid):
        if t == "TALK_ROLE_PLAYER":
            return "旅行者"
        if t == "NARRATOR":
            return "旁白"
        if t == "TALK_ROLE_NPC" and rid.isdigit():
            h = npc_name.get(int(rid))
            if h:
                return npc_display(h) or ""
        return ""

    # 未上线/dev markers in quest titles: $HIDDEN/$UNRELEASED/(test)/(hide)/
    # bare leading "test" (5.x scaffolding titles omit the parens)
    dev_mark = re.compile(r"\$UNRELEASED|\$HIDDEN")
    test_mark = re.compile(r"[（(]\s*(?:test|hide)\s*[)）]|(?:^|[\s\-])test[\s\-]*",
                           re.I)

    def quest_title(nid):
        """quest subId (or talk-registry questId, or a bare main-quest id) ->
        (human quest title, dev_flag) or (None, False). dev_flag means the
        quest is internal/unreleased scaffolding ($HIDDEN etc)."""
        m = sub2main.get(nid)
        if m is None:
            row = talk_reg.get(nid)
            if isinstance(row, dict) and isinstance(row.get("questId"), int):
                m = row["questId"]
        h = main_title.get(m) if m is not None else main_title.get(nid)
        if h:
            t = tm_text(h)
            if t:
                # runtime placeholders inside titles: {QuestNpcID} -> 某人
                t = re.sub(r"\{[A-Za-z0-9_]+(?:\[[^\]]*\])?\}", "某人", t)
            if t and len(t) <= 60:
                dev = bool(dev_mark.search(t))
                if dev:
                    t = test_mark.sub("", dev_mark.sub("", t)).strip()
                return t, dev
        return None, False

    def npc_label(row):
        ids = row.get("npcId")
        for nid in (ids if isinstance(ids, list) else [ids] if ids else []):
            if isinstance(nid, int):
                h = npc_name.get(nid)
                if h:
                    t = npc_display(h)
                    if t:
                        return t
        return ""

    def act_label(row):
        for cond in (row.get("beginCond") or []):
            if not isinstance(cond, dict):
                continue
            for p in (cond.get("param") or []):
                if isinstance(p, str) and p.isdigit() and int(p) in act_name:
                    t = tm_text(act_name[int(p)])
                    if t and len(t) <= 60:
                        return t
        return ""

    def quest_label(cid_kind_prefix, nid, kind_label=None):
        t, dev = quest_title(nid)
        if t is None:
            return None
        if dev:
            return "未上线任务内容" if not t else "未上线任务" + brk(t)
        return f"{kind_label or '任务'}" + brk(t)

    def npc_display(h):
        """npc name label text, or None if it is dev/test scaffolding."""
        t = tm_text(h)
        # host placeholders (#{REALNAME[ID(n)|HOSTONLY…]}) = the Traveler
        if re.fullmatch(r"#?\{REALNAME\[[^{}]*\}\}?", t or ""):
            return "旅行者"
        # dev scaffolding names: test/hide prefix (any separator or none),
        # (隐藏) marker
        if re.match(r"^\s*(?:test|hide)", t or "", re.I) \
                or re.match(r"^[（(](?:隐藏|hidden)[)）]", t or ""):
            return None
        if t and len(t) <= 40 and re.search(r"[\u4e00-\u9fff]", t) \
                and not re.search(
                r"\$UNRELEASED|\$HIDDEN|[（(]\s*(?:test|hide)\s*[)）]", t, re.I):
            return t
        return None

    def cond_quest(row):
        """last-resort anchor: quest numbers embedded in beginCond params
        (QUEST_COND_QUEST_GLOBAL_VAR_EQUAL etc.) -> quest title"""
        for cond in (row.get("beginCond") or []):
            if not isinstance(cond, dict):
                continue
            for p in (cond.get("param") or []):
                if isinstance(p, str) and p.isdigit():
                    t, dev = quest_title(int(p))
                    if t is not None and not dev:
                        return t
        return None

    def brk(t):
        """wrap a title in 「」 without doubling when the stored title/name
        already embeds brackets (e.g. 「水仙十字大冒险」, NPC 「减七琶音」)."""
        if "「" in t or "」" in t:
            return t
        return "「" + t + "」"

    def id_prefix_quest(idstr):
        """talk-group / dialog-seq / coop ids encode their owning quest
        subId: 730379907.json sits under quest 7303799, talk 1203602 under
        120360, coop 1903110_176 under 190311, seq 3470101 under 347010.
        Strip 1-3 trailing digits and accept the stem only if the quest
        table knows that subId (or the stem is itself a main-quest id)."""
        s = str(idstr)
        if len(s) < 8:
            return None
        for cut in (1, 2, 3):
            if len(s) - cut < 6:
                continue
            qid = int(s[:-cut])
            if qid in sub2main:
                return qid
            if len(s) >= 10 and qid in main_title:
                return qid
        return None

    def ctx_label(kind, cid):
        if kind == "Quest" and cid == "GlobalDialog":
            return "任务通用对白"
        if kind in ("Quest", "QuestGroup") and cid.isdigit():
            lab = quest_label(None, int(cid),
                             "任务对话组" if kind == "QuestGroup" else "任务")
            if lab:
                return lab
        if kind == "Coop" and cid.split("_")[0].isdigit():
            lab = quest_label(None, int(cid.split("_")[0]), "多人任务")
            if lab:
                return lab
        if kind in ("Npc", "NpcOther") and cid.isdigit() and int(cid) in npc_name:
            t = npc_display(npc_name[int(cid)])
            if t:
                return "NPC对话" + brk(t)
        if kind == "NpcGroup" and cid.isdigit() and int(cid) in npc_name:
            t = npc_display(npc_name[int(cid)])
            if t:
                return "NPC对话组" + brk(t)
        row = talk_reg.get(int(cid)) if cid.isdigit() else None
        if isinstance(row, dict):
            if kind in ("Npc", "NpcGroup", "NpcOther"):
                # Talk/Npc files are named by talk id, not npc config id:
                # resolve through the registry's npcId.
                nm = npc_label(row)
                if nm:
                    kind_lbl = "NPC对话组" if kind == "NpcGroup" else "NPC对话"
                    return kind_lbl + brk(nm)
            t = (quest_title(row["questId"])[0]
                 if isinstance(row.get("questId"), int) else None)
            if kind == "Activity":
                a = act_label(row)
                if a:
                    return "活动" + brk(a)
                if t:
                    return "活动任务" + brk(t)
            if t:
                return f"{KIND_LABELS.get(kind, kind)}（任务" + brk(t) + "）"
            nm = npc_label(row)
            if nm and kind in ("FreeGroup", "NpcOther", "Gadget", "GadgetGroup"):
                return KIND_LABELS.get(kind, kind) + brk(nm)
            cq = cond_quest(row)
            if cq:
                return f"{KIND_LABELS.get(kind, kind)}（任务" + brk(cq) + "）"
        # id-prefix fallback: group/seq ids that embed a known quest subId
        pq = id_prefix_quest(cid.split("_")[0]) if cid.isdigit() or "_" in cid else None
        if pq is not None:
            t, dev = quest_title(pq)
            if t is not None:
                if dev:
                    return f"{KIND_LABELS.get(kind, kind)}｜未上线任务" + brk(t)
                return f"{KIND_LABELS.get(kind, kind)}（任务" + brk(t) + "）"
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

    # 3b) DialogExcelConfigData: the dialogue-sequence layer (cutscene/popup
    # lines with no Talk-file reference). Seq ids carry the owning quest
    # prefix; label honestly as 剧情对白, never a bare quest claim.
    dpath = os.path.join(args.repo, "ExcelBinOutput",
                         "DialogExcelConfigData.json")
    if os.path.exists(dpath):
        n_seq = 0
        for row in load_json(dpath):
            if not isinstance(row, dict):
                continue
            h = row.get("talkContentTextMapHash")
            m = is_tm_id(h, tm_keys) if isinstance(h, int) else None
            if m is None:
                continue
            label = "剧情对白"
            pq = id_prefix_quest(row.get("GFLDJMJKIKE"))
            if pq is not None:
                t, dev = quest_title(pq)
                if t is not None:
                    if dev:
                        label = "剧情对白｜未上线任务" + brk(t)
                    else:
                        label = "剧情对白（任务" + brk(t) + "）"
            spk = ""
            role = row.get("talkRole")
            if isinstance(role, dict):
                spk = speaker_name(role.get("type", ""), str(role.get("id", "")))
            hits[m].append((7, label, spk))
            n_seq += 1
        print(f"  dialog-seq rows matched: {n_seq}")

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

    # 5) subtitle asset names -> 过场字幕（任务「…」）via embedded quest numbers.
    # Asset stems look like Cs_Sumeru_AQ_30310701_HB_Boy / EQ4019208; the
    # digits inside resolve through the same quest joins. Stems that resolve
    # to nothing still get a Chinese label: the region token is translated
    # (Mengde/MD→蒙德 …) and the clip is honestly marked 未关联任务 — the
    # internal cutscene numbers exist in no table and must not be shown raw.
    out.execute("CREATE TABLE subs(asset TEXT PRIMARY KEY, source TEXT)")
    region_cn = {
        "fontaine": "枫丹", "fd": "枫丹", "natlan": "纳塔", "nodkrai": "纳塔",
        "nk": "纳塔", "sumeru": "须弥", "smr": "须弥", "inazuma": "稻妻",
        "iz": "稻妻", "md": "蒙德", "mengde": "蒙德", "mdaq": "蒙德",
        "liyue": "璃月", "ly": "璃月", "lyaq": "璃月", "ambor": "须弥",
    }
    ns = 0
    nr = 0
    sd = os.path.join(args.repo, "Subtitle", "CHS")
    if os.path.isdir(sd):
        for fn in sorted(os.listdir(sd)):
            if not fn.endswith(".srt"):
                continue
            stem = fn[:-4]
            resolved = None
            for num in re.findall(r"\d{4,}", stem):
                t, dev = quest_title(int(num))
                if t is not None:
                    src = ("未上线任务" + brk(t)) if dev else "任务" + brk(t)
                    resolved = f"过场字幕（{src}）"
                    break
            if resolved:
                out.execute("INSERT OR REPLACE INTO subs VALUES (?,?)",
                            (stem, resolved))
                ns += 1
                continue
            parts = stem.split("_")
            reg = ""
            probe = parts[1] if len(parts) > 1 and parts[0] == "Cs" else parts[0]
            for k in sorted(region_cn, key=len, reverse=True):
                if probe.lower().startswith(k):
                    reg = region_cn[k]
                    break
            label = f"过场字幕（{reg}·未关联任务）" if reg else "过场字幕（未关联任务）"
            out.execute("INSERT OR REPLACE INTO subs VALUES (?,?)", (stem, label))
            nr += 1
        out.commit()
    print(f"subtitle provenance: {ns} resolved to quests, {nr} marked 未关联任务")


if __name__ == "__main__":
    main()
