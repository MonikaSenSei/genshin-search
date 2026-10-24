#!/usr/bin/env python3
"""M2 probe: where per-line speaker info lives in the dump."""
import json, sys, collections

REPO = "data/repo"

def sample_table(fn, n=3):
    p = f"{REPO}/ExcelBinOutput/{fn}"
    data = json.load(open(p, encoding="utf-8"))
    rows = data if isinstance(data, list) else list(data.values())
    print(f"\n===== {fn}: {len(rows)} rows =====")
    keys = collections.Counter()
    for r in rows:
        keys.update(r.keys())
    for k, c in keys.most_common():
        print(f"  {k}: {c}")
    for r in rows[:n]:
        s = json.dumps(r, ensure_ascii=False)
        print("  SAMPLE:", s[:600])

for fn in ["DialogExcelConfigData.json", "TalkExcelConfigData_0.json",
           "QuestScheduleTalkExcelConfigData.json", "BubbleTalkDataExcelConfigData.json"]:
    try:
        sample_table(fn)
    except Exception as e:
        print(f"!! {fn}: {e}")
