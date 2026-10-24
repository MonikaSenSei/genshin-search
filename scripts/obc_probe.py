#!/usr/bin/env python3
"""Observation枢 (观测枢) wiki API probe. Endpoints discovered 2026-10-25 by
reverse-engineering the Nuxt bundle served at baike.mihoyo.com/ys/obc/.

Confirmed GET endpoints (need UA + Referer/Origin on baike.mihoyo.com, else 403):
  tree:  https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1/getChannelTree?app_sn=ys_obc
  list:  https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1/home/content/list?app_sn=ys_obc&channel_id=<id>
  search: https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi/search?app_sn=ys_obc&keyword=<kw>
Entry page URL form: https://baike.mihoyo.com/ys/obc/content/<entry_page_id>/detail
Channel page URL form: https://baike.mihoyo.com/ys/obc/channel/map/<parent_id>/<channel_id>
"""
import json
import sys
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
BASE = "https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1"


def get(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://baike.mihoyo.com/",
            "Origin": "https://baike.mihoyo.com",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def channel_tree():
    return get(f"{BASE}/getChannelTree?app_sn=ys_obc")["data"]


def flatten(node, path=()):
    here = path + (node["name"],)
    yield node["channel_id"], here, node.get("parent_id")
    for c in node.get("children") or []:
        yield from flatten(c, here)


def channel_entries(channel_id, page=1, page_size=50):
    url = (f"{BASE}/home/content/list?app_sn=ys_obc"
           f"&channel_id={channel_id}&page={page}&page_size={page_size}")
    return get(url)["data"]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tree"
    if cmd == "tree":
        root = channel_tree()
        rows = list(flatten(root))
        json.dump(rows, open("data/obc_channels.json", "w"), ensure_ascii=False, indent=1)
        print("channels:", len(rows))
        for cid, path, _ in rows:
            if any(k in path[-1] for k in ("书籍", "读书", "文献")):
                print("BOOK?", cid, " > ".join(path))
    elif cmd == "list":
        cid = int(sys.argv[2])
        page = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        d = channel_entries(cid, page)
        print("keys:", list(d.keys()))
        print({k: v for k, v in d.items() if not isinstance(v, list)})
        items = d.get("list") or d.get("content_list") or []
        print("items on page:", len(items))
        for it in items[:12]:
            print(it.get("id") or it.get("entry_page_id"), it.get("title") or it.get("name"))
