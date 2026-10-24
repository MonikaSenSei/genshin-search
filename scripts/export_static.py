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
  web/data/meta.json       alias table + corpus baseline + counts
Re-run after index rebuilds / social_fetch update to refresh site data.
"""
import gzip
import json
import os
import sqlite3
import struct

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
    with gzip.open(path, "wb") as f:
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
    # OBC-verified URL in index/book_titles.db (obc / bwiki->obc only)
    title_url = {}
    bt = os.path.join(ROOT, "index", "book_titles.db")
    if os.path.exists(bt):
        btc = sqlite3.connect(bt)
        for t, u, s in btc.execute(
                "SELECT title, url, source FROM book_titles "
                "WHERE source IN ('obc','bwiki->obc') AND url != ''"):
            title_url.setdefault(t, u)
    src_url = [title_url.get(v[3:], "") if v.startswith("书籍:") else ""
               for v in src_tbl]
    print(f"src jump URLs: {sum(1 for u in src_url if u)} / {len(src_tbl)} source labels")

    blob, off_bytes = build_blob(texts)
    cols = [col_bytes(ty, "B"), col_bytes(src, "H"), col_bytes(spk, "H"),
            col_bytes(cast, "H")]
    lens = [len(off_bytes), len(blob)] + [len(c) for c in cols]
    header = {"n": len(texts), "lens": lens, "ty": ty_tbl, "src": src_tbl,
              "spk": spk_tbl, "cast": cast_tbl, "src_url": src_url}
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


if __name__ == "__main__":
    main()
