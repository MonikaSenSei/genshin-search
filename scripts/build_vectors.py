#!/usr/bin/env python3
"""Embed every indexed doc with the local bge-small-zh ONNX model and save
index/vectors.npz (float16 vectors + rowids), doc order = docs.rowid.
Run with .venv/bin/python:  .venv/bin/python scripts/build_vectors.py"""
import os
import sys
import sqlite3
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from embed import encode_texts

DB = os.path.join(ROOT, "index", "genshin.db")
OUT = os.path.join(ROOT, "index", "vectors.npz")
BATCH = 96


def main():
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT rowid, body FROM docs ORDER BY rowid").fetchall()
    n = len(rows)
    print(f"embedding {n} docs...")
    rowids = np.fromiter((r for r, _ in rows), dtype=np.int64, count=n)
    dim = 512
    vecs = np.zeros((n, dim), dtype=np.float16)
    t0 = time.time()
    for i in range(0, n, BATCH):
        chunk = [b for _, b in rows[i:i + BATCH]]
        v = encode_texts(chunk)
        vecs[i:i + len(chunk)] = v.astype(np.float16)
        if (i // BATCH) % 100 == 0:
            done = i + len(chunk)
            rate = done / (time.time() - t0)
            eta = (n - done) / max(rate, 1)
            print(f"  {done}/{n}  {rate:.0f} docs/s  eta {eta:.0f}s", flush=True)
    np.savez(OUT, vectors=vecs, rowids=rowids)
    print(f"saved {OUT}  ({os.path.getsize(OUT)/1e6:.0f} MB)")
    # sanity: a few self-consistency checks
    probe = "那位王 高天之主 僭主"
    q = encode_texts([probe])[0].astype(np.float32)
    sims = (vecs.astype(np.float32) @ q)
    top = sims.argsort()[::-1][:5]
    for t in top:
        print(f"probe sim={sims[t]:.3f} rowid={rowids[t]}: {rows[t][1][:60]}")


if __name__ == "__main__":
    main()
