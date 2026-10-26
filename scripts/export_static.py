#!/usr/bin/env python3
"""M4 export: build static web bundle from index/genshin.db + index/social.db.

Binary container (then gzipped) to keep download ~10MB class:
  header: 'GSBN' + u32 headerLen + header JSON (string tables, counts)
  then raw sections per header offsets/lengths:
    offsets u32(n+1), text blob UTF-8 (docs joined with \\x00 not needed;
    offsets carry boundaries), index columns u8/u16/u16/u16.
Outputs:
  web/data/genshin.bin.gz  386k docs: text + type/source/speaker/cast
  web/data/social.bin.gz   posts: title+body blob, url/pub/source columns
  web/data/items.bin.gz    M4.7 items layer: plain JSON array (lite cards)
  web/data/books.bin.gz    M4.8 book-title layer: plain JSON array (icon cards)
  web/data/meta.json       alias table + corpus baseline + counts
Re-run after index rebuilds / social_fetch update to refresh site data.
"""
import gzip
import json
import os
import re
import sqlite3
import struct
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "web", "data")


def table_write(vals):
    tbl, idx, out = [], {}, []
    for v in vals:
        v = v if v is not None else ""
        i = idx.get(v)
        if i is None:
            i = len(tbl)
            idx[v] = i
            tbl.append(v)
        out.append(i)
    return tbl, out


def col_bytes(idxs, fmt):
    return struct.pack(f"<{len(idxs)}{fmt}", *idxs)


def pack_bin(header, sections):
    body = b"".join(sections)
    hj = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode()
    return b"GSBN" + struct.pack("<I", len(hj)) + hj + body


def write_gz(path, data):
    """Write <name>.bin.gz (compat) and <name>.bin.zst (preferred, if zstd
    CLI available). Returns dict of sizes.
    NOTE: zstd must compress the RAW bytes — compressing the .gz file yields
    a zst wrapper around gzip, which DecompressionStream('zstd') then hands to
    parseBin as gzip bytes ("bad magic", silent fallback to .gz)."""
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(data)
    sizes = {path: os.path.getsize(path)}
    import shutil, subprocess, tempfile
    zp = path[:-3] + ".zst"
    if shutil.which("zstd"):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
            tf.write(data)
            raw = tf.name
        try:
            subprocess.run([
                "zstd", "-19", "-q", "-f", raw, "-o", zp], check=True)
            sizes[zp] = os.path.getsize(zp)
        finally:
            os.unlink(raw)
    return sizes


def export_items():
    """M4.7 items layer: OBC item entries -> items.bin (plain JSON array,
    gz/zst dual-format; fetched by the same fetchDecompressed path).
    Lite card fields only; numeric tables are viewed on the OBC page itself."""
    src = os.path.join(ROOT, "data", "obc_items.json")
    if not os.path.exists(src):
        print("items: no data/obc_items.json, skipping items.bin")
        return
    raw = json.load(open(src, encoding="utf-8"))
    keep = ("id", "kind", "name", "alias", "category", "star", "icon",
            "desc", "effect", "story", "obtain", "rarity", "url")
    slim = []
    for r in raw:
        o = {k: r.get(k, "") for k in keep}
        if r.get("slots"):
            o["slots"] = [{k2: s.get(k2, "") for k2 in
                           ("slot", "name", "icon", "desc", "story")}
                          for s in r["slots"]]
        if o["name"]:
            slim.append(o)
    data = json.dumps(slim, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    sizes = write_gz(os.path.join(OUT, "items.bin.gz"), data)
    print(f"items.bin: {', '.join(f'{os.path.basename(k)} {v/1e6:.2f} MB' for k, v in sizes.items())} ({len(slim)} entries)")


def export_books():
    """M4.8 book-title layer: joined book titles from index/book_titles.db +
    cover icons from the cached 观测枢 book-channel listing (refresh with
    scripts/obc_fetch_channel.py 68). Plain JSON array; cards link straight
    to the OBC entry (no in-site modal)."""
    bt = os.path.join(ROOT, "index", "book_titles.db")
    if not os.path.exists(bt):
        print("books: no index/book_titles.db, skipping books.bin")
        return
    icons = {}
    ch = os.path.join(ROOT, "data", "obc_channel_68.json")
    if os.path.exists(ch):
        acc = []

        def find(o):
            if isinstance(o, dict):
                if "content_id" in o:
                    acc.append(o)
                else:
                    for v in o.values():
                        find(v)
            elif isinstance(o, list):
                for v in o:
                    find(v)
        find(json.load(open(ch, encoding="utf-8")))
        icons = {str(e["content_id"]): e.get("icon", "") for e in acc}
    btc = sqlite3.connect(bt)
    slim, seen = [], set()
    for title, url, src in btc.execute(
            "SELECT title, url, source FROM book_titles "
            "WHERE url != '' ORDER BY title"):
        if title in seen:
            continue
        seen.add(title)
        m = re.search(r"/content/(\d+)/", url)
        o = {"title": title, "url": url,
             "disp": title if title.startswith("《") else f"《{title}》",
             "icon": icons.get(m.group(1), "") if m else ""}
        slim.append(o)
    slim.sort(key=lambda o: o["title"])
    data = json.dumps(slim, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    sizes = write_gz(os.path.join(OUT, "books.bin.gz"), data)
    n_icon = sum(1 for o in slim if o["icon"])
    print(f"books.bin: {', '.join(f'{os.path.basename(k)} {v/1e3:.0f} KB' for k, v in sizes.items())} ({len(slim)} titles, {n_icon} with icon)")


def export_charlayer():
    """M4.9 character & creature layers: 观测枢 channel listings (25=角色,
    6=敌人) -> characters.bin / creatures.bin. Plain JSON arrays; cards
    link straight to the OBC entry (like books, no modal). match = name
    variants with 【预告】/「…」 decorations split out so '若娜瓦' hits
    '「死之执政」若娜瓦'."""
    chans = [("25", "characters"), ("6", "creatures")]
    for cid, outname in chans:
        src = os.path.join(ROOT, "data", f"obc_channel_{cid}.json")
        if not os.path.exists(src):
            print(f"{outname}: no data/obc_channel_{cid}.json, skipping")
            continue
        entries = json.load(open(src, encoding="utf-8"))
        slim, seen = [], set()
        for e in entries:
            title = (e.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            base = re.sub(r"【[^】]*】", "", title).strip()
            mvars = {title, base}
            for seg in re.findall(r"「([^」]+)」|」(.+)", title):
                for s in seg:
                    if s.strip():
                        mvars.add(s.strip())
            mvars = sorted(m for m in mvars if m)
            o = {"name": base or title, "match": mvars,
                 "alias": e.get("alias_name") or "",
                 "summary": e.get("summary") or "",
                 "icon": e.get("icon") or "",
                 "url": f"https://baike.mihoyo.com/ys/obc/content/"
                        f"{e['content_id']}/detail"}
            slim.append(o)
        slim.sort(key=lambda o: o["name"])
        data = json.dumps(slim, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        sizes = write_gz(os.path.join(OUT, f"{outname}.bin.gz"), data)
        n_icon = sum(1 for o in slim if o["icon"])
        print(f"{outname}.bin: {', '.join(f'{os.path.basename(k)} {v/1e3:.0f} KB' for k, v in sizes.items())} ({len(slim)} entries, {n_icon} with icon)")


def main():
    os.makedirs(OUT, exist_ok=True)

    db = sqlite3.connect(os.path.join(ROOT, "index", "genshin.db"))
    rows = db.execute(
        "SELECT body, corpus_type, source, speaker, \"cast\" FROM docs ORDER BY rowid"
    ).fetchall()
    texts = [r[0] for r in rows]
    ty_tbl, ty = table_write(r[1] for r in rows)
    src_tbl, src = table_write(r[2] for r in rows)
    spk_tbl, spk = table_write(r[3] for r in rows)
    cast_tbl, cast = table_write(r[4] for r in rows)

    def build_blob(strings, sep="\u0000"):
        """Join texts; return (utf8 blob, u32 UTF-16-unit offsets n+1).
        Offsets are valid JS string indices as long as text is BMP-only
        (asserted); docs slice = [off[i], off[i+1]-1)."""
        def u16len(s):
            return len(s.encode("utf-16-le")) // 2
        # offsets in UTF-16 code units == JS string indices (surrogate-safe)
        offs, acc = [], 0
        for s in strings:
            offs.append(acc)
            acc += u16len(s) + 1
        offs.append(acc)
        return sep.join(strings).encode("utf-8"), struct.pack(
            f"<{len(offs)}I", *offs)

    # optional per-source jump URLs: 书籍:<title> labels that carry an
    # OBC-verified URL in index/book_titles.db (obc / bwiki->obc only),
    # plus 任务「title」 labels verified by scripts/obc_quests.py
    title_url = {}
    bt = os.path.join(ROOT, "index", "book_titles.db")
    if os.path.exists(bt):
        btc = sqlite3.connect(bt)
        for t, u, s in btc.execute(
                "SELECT title, url, source FROM book_titles "
                "WHERE source IN ('obc','bwiki->obc') AND url != ''"):
            title_url.setdefault(t, u)
    quest_path = os.path.join(ROOT, "data", "quest_urls.json")
    quest_norm = {}
    if os.path.exists(quest_path):
        for t, e in json.load(open(quest_path, encoding="utf-8"))["map"].items():
            if e.get("ok") and e.get("url"):
                title_url.setdefault(f"「{t}」", e["url"])

                nq = re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", t).lower(),
                           flags=re.UNICODE)
                quest_norm.setdefault(nq, e["url"])
                parts = [unicodedata.normalize("NFKC", p).lower()
                         for p in re.split(r"[·・.．]", t)]
                if len(parts) >= 2:
                    head = re.sub(r"[\W_]+", "", parts[0], flags=re.UNICODE)
                    if head:
                        quest_norm.setdefault("<series>" + head, e["url"])

    def series_inherit(t):
        # 'S·X' inherits the jump of matched bare-series key 'S', or of a
        # matched 'S·V' entry (its series half was indexed under <series>S)
        tparts = [unicodedata.normalize("NFKC", p).lower()
                  for p in re.split(r"[·・.．]", t)]
        if len(tparts) >= 2:
            head = re.sub(r"[\W_]+", "", tparts[0], flags=re.UNICODE)
            return quest_norm.get(head) or quest_norm.get("<series>" + head, "")
        return ""

    def quest_bracket_url(tail):
        # 任务「踏鞴物语·终幕」 style labels: exact title, else series inherit
        nt = re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", tail).lower(),
                    flags=re.UNICODE)
        return quest_norm.get(nt) or series_inherit(tail)

    def quest_label_url(v):
        # other provenance label shapes carry the bare title after '｜'
        # (mainquest｜踏鞴物语·终幕 etc); same exact-then-inherit rule
        if "｜" not in v:
            return ""
        head, tail = v.split("｜", 1)
        if head not in ("mainquest", "dailytask", "quest"):
            return ""
        return quest_bracket_url(tail)

    # M4.12: 世界文书: labels joined to 观测枢 map-text entries and 物品故事:
    # labels named via weapon/relic id tables carry their verified URLs
    # (data/pickup_labels.json + data/maptext_urls.json, HEAD-verified).
    plabel_url = {}
    pl_path = os.path.join(ROOT, "data", "pickup_labels.json")
    if os.path.exists(pl_path):
        for v in json.load(open(pl_path, encoding="utf-8")).values():
            if v.get("url") and v.get("label"):
                plabel_url.setdefault(v["label"], v["url"])
    mt_path = os.path.join(ROOT, "data", "maptext_urls.json")
    mt_raw = os.path.join(ROOT, "data", "obc_maptext_raw")
    if os.path.exists(mt_path) and os.path.isdir(mt_raw):
        mtv = json.load(open(mt_path, encoding="utf-8"))
        for fn in os.listdir(mt_raw):
            eid = fn[:-5]
            e = mtv.get(eid)
            if not e or not e.get("ok"):
                continue
            rec = json.load(open(os.path.join(mt_raw, fn), encoding="utf-8"))
            plabel_url.setdefault(f"世界文书:{rec['title']}", e["url"])

    # creature-codex labels (codex｜<name>) -> OBC enemy entry (M4.13,
    # scripts/obc_creatures.py join, HEAD-verified in codex_match.json)
    codex_url = {}
    cx_path = os.path.join(ROOT, "data", "codex_match.json")
    if os.path.exists(cx_path):
        for r in json.load(open(cx_path, encoding="utf-8")).values():
            if r.get("ok") and r.get("url") and r.get("name"):
                codex_url.setdefault(r["name"], r["url"])

    def label_jump(v):
        if v.startswith("书籍:"):
            return title_url.get(v[3:], "")
        if v.startswith("世界文书:") or v.startswith("物品故事:"):
            return plabel_url.get(v, "")
        if v.startswith("codex｜"):
            return codex_url.get(v[len("codex｜"):], "")
        for pfx in ("任务「", "主线任务「", "每日任务「", "多人任务「",
                    "活动任务「", "任务对话组「"):
            if v.startswith(pfx):
                return quest_bracket_url(v[len(pfx):])
        return quest_label_url(v)

    src_url = [label_jump(v) for v in src_tbl]
    print(f"src jump URLs: {sum(1 for u in src_url if u)} / {len(src_tbl)} source labels")

    # per-doc jump URLs (viewpoint descs have no per-source label: the join
    # is per text) — data/viewpoint_urls.json map key == exact doc body
    doc_url = {}
    vp_path = os.path.join(ROOT, "data", "viewpoint_urls.json")
    if os.path.exists(vp_path):
        vp = json.load(open(vp_path, encoding="utf-8")).get("map", {})
        for i, t in enumerate(texts):
            e = vp.get(t)
            if e and e.get("ok") and e.get("url"):
                doc_url[str(i)] = e["url"]
    print(f"doc jump URLs: {len(doc_url)} (viewpoints)")

    blob, off_bytes = build_blob(texts)
    cols = [col_bytes(ty, "B"), col_bytes(src, "H"), col_bytes(spk, "H"),
            col_bytes(cast, "H")]
    lens = [len(off_bytes), len(blob)] + [len(c) for c in cols]
    header = {"n": len(texts), "lens": lens, "ty": ty_tbl, "src": src_tbl,
              "spk": spk_tbl, "cast": cast_tbl, "src_url": src_url,
              "doc_url": doc_url}
    sizes = write_gz(os.path.join(OUT, "genshin.bin.gz"),
                     pack_bin(header, [off_bytes, blob] + cols))
    print(f"genshin.bin: {', '.join(f'{os.path.basename(k)} {v/1e6:.2f} MB' for k, v in sizes.items())} ({len(texts)} docs, blob {len(blob)/1e6:.1f} MB)")

    sdb = sqlite3.connect(os.path.join(ROOT, "index", "social.db"))
    posts = sdb.execute(
        "SELECT title, body, url, pub_str, source FROM posts ORDER BY pub_ts DESC"
    ).fetchall()
    pblob, poff_bytes = build_blob([f"{p[0]}\u0001{p[1]}" for p in posts])
    so_tbl, so = table_write(p[4] for p in posts)
    pu_tbl, pu = table_write(p[3] or "" for p in posts)
    ur_tbl, ur = table_write(p[2] or "" for p in posts)
    pcols = [col_bytes(so, "B"), col_bytes(pu, "H"), col_bytes(ur, "H")]
    plens = [len(poff_bytes), len(pblob)] + [len(c) for c in pcols]
    pheader = {"n": len(posts), "lens": plens, "so": so_tbl, "pu": pu_tbl,
               "ur": ur_tbl}
    sizes = write_gz(os.path.join(OUT, "social.bin.gz"),
                     pack_bin(pheader, [poff_bytes, pblob] + pcols))
    print(f"social.bin: {', '.join(f'{os.path.basename(k)} {v/1e6:.2f} MB' for k, v in sizes.items())} ({len(posts)} posts)")

    aliases = json.load(open(os.path.join(ROOT, "aliases", "alias_table.json"),
                             encoding="utf-8"))
    state = json.load(open(os.path.join(ROOT, "index", "update_state.json")))
    meta = {"aliases": aliases, "baseline": state.get("tag", ""),
            "counts": {"docs": len(texts), "posts": len(posts)}}
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"meta.json ({len(aliases)} alias entries)")

    export_items()
    export_books()
    export_charlayer()


if __name__ == "__main__":
    main()
