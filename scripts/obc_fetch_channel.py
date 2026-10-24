#!/usr/bin/env python3
"""Pull the full entry catalog of a 观测枢 channel (paged) into data/obc_channel_<id>.json.
Usage: python3 scripts/obc_fetch_channel.py <channel_id> [...]
"""
import json
import sys
import time

sys.path.insert(0, "scripts")
from obc_probe import channel_entries


def fetch_channel(cid):
    items = {}
    page = 1
    while True:
        d = channel_entries(cid, page, 50)
        lst = d.get("list") or []
        new = 0
        for it in lst:
            for sub in it.get("list") or []:
                key = str(sub.get("content_id"))
                if key not in items:
                    items[key] = sub
                    new += 1
            # channel node itself may carry entries directly
            if it.get("content_id"):
                key = str(it["content_id"])
                if key not in items:
                    items[key] = it
                    new += 1
        print(f"page {page}: listed {len(lst)} nodes, new entries {new}, total {len(items)}", flush=True)
        if not lst or new == 0:
            break
        page += 1
        time.sleep(0.6)
    return items


if __name__ == "__main__":
    for cid in sys.argv[1:]:
        items = fetch_channel(int(cid))
        out = f"data/obc_channel_{cid}.json"
        json.dump(list(items.values()), open(out, "w"), ensure_ascii=False, indent=1)
        print(f"channel {cid}: {len(items)} entries -> {out}")
