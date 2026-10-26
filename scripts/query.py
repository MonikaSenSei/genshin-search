#!/usr/bin/env python3
"""M2 query: literal + alias-expanded search with context denoising,
speaker attribution, and optional semantic (implication) recall.

Usage:
  python3 query.py 关键词 [--limit N] [--json] [--no-alias] [--semantic]
Run with .venv/bin/python to enable --semantic (needs numpy/onnxruntime).
"""
import argparse
import json
import math
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "index", "genshin.db")
ALIASES = os.path.join(ROOT, "aliases", "alias_table.json")
VECTORS = os.path.join(ROOT, "index", "vectors.npz")

SELECT = ('SELECT rowid, body, corpus_type, source, speaker, "cast" '
          'FROM docs WHERE docs MATCH ?')


def load_aliases():
    if not os.path.exists(ALIASES):
        return {}
    with open(ALIASES, encoding="utf-8") as f:
        table = json.load(f)
    return {e["term"]: e for e in table}


def fts_tokens(q):
    return re.findall(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+", q)


def phrase(q):
    toks = fts_tokens(q)
    if not toks:
        return None
    return '"' + " ".join(t.replace('"', '""') for t in toks) + '"'


def match_docs(db, term):
    """FTS5 candidates (token-adjacent, punctuation-blind) are then
    validated strictly: exact substring, or gaps of whitespace/newline only
    (same semantics as the static web engine, M4). Same-line punctuation
    gaps ("当天，父亲" ~ 天父) are word-boundary accidents and rejected.
    Returns full rows; no collection cap."""
    if not term or not phrase(term):
        return []
    rx = re.compile("".join(re.escape(c) + r"\s*" for c in term))
    cands = db.execute(SELECT, (phrase(term),)).fetchall()
    return [r for r in cands if rx.search(r[1])]


def semantic_recall(query, topk):
    """Brute-force cosine over the precomputed doc vectors. Returns
    [(rowid, score)] or raises ImportError if deps are missing."""
    import numpy as np
    from embed import encode_texts, QUERY_PREFIX
    data = np.load(VECTORS)
    vecs = data["vectors"].astype(np.float32)
    rowids = data["rowids"]
    qv = encode_texts([QUERY_PREFIX + query])[0]
    sims = vecs @ qv
    idx = sims.argsort()[::-1][:topk]
    return [(int(rowids[i]), float(sims[i])) for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("term")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--weak-limit", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-alias", action="store_true")
    ap.add_argument("--semantic", action="store_true")
    ap.add_argument("--semantic-k", type=int, default=15)
    args = ap.parse_args()

    db = sqlite3.connect(DB)
    N = db.execute("SELECT count(*) FROM docs").fetchone()[0]
    alias_map = load_aliases()

    term = args.term
    entry = alias_map.get(term)
    terms = [term]
    if entry and not args.no_alias:
        terms += entry.get("aliases", [])

    # per-term validated matches -> df -> IDF weight (M2 denoising core)
    term_hits = {}
    for t in terms:
        if not phrase(t):
            continue
        term_hits[t] = match_docs(db, t)
    weights = {t: (math.log2(N / (len(rows) + 1)), len(rows))
               for t, rows in term_hits.items()}

    results = {}
    for t, rows in term_hits.items():
        for rowid, body, ctype, source, spk, cast in rows:
            r = results.setdefault(body, {
                "text": body, "corpus_type": ctype, "source": source,
                "speaker": spk, "cast": cast, "matched_via": [], "rowid": rowid})
            r["matched_via"].append(t)

    for r in results.values():
        uniq = sorted(set(r["matched_via"]))
        r["matched_via"] = uniq
        # Title-match priority (mirrors web/app.js): book source labels embed
        # the title (书籍:<title>); a term that is a title substring boosts
        # that book's title-card and body docs to the top of the list.
        title = r["source"][len("书籍:"):] if r["source"].startswith("书籍:") else ""
        boost = 10 if title and any(t in title for t in uniq) else 1
        r["score"] = sum(weights[t][0] for t in uniq) * boost
        # strong: literal hit, or >=2 independent aliases corroborate,
        # or a single near-unique alias phrase (df <= 5)
        alias_hits = [t for t in uniq if t != term]
        strong = (term in uniq) or len(alias_hits) >= 2 or any(
            weights[t][1] <= 5 for t in alias_hits)
        r["strong"] = bool(strong)

    # M4.12 rank rule (mirrors web/app.js LOW_TIERS): world docs / item
    # stories / wiki transcriptions rank below the main corpus.
    LOW_TIERS = {"maptext", "maptext_obc", "pickup", "flavor"}
    strong = sorted([r for r in results.values() if r["strong"]],
                    key=lambda r: (r["corpus_type"] in LOW_TIERS, -r["score"]))[:args.limit]
    weak = sorted([r for r in results.values() if not r["strong"]],
                  key=lambda r: (r["corpus_type"] in LOW_TIERS, -r["score"]))[:args.weak_limit]

    sem = []
    if args.semantic:
        # anchor the semantic query with verified aliases when known: a bare
        # rare proper noun embeds as surface noise (法涅斯->法里斯), but the
        # alias context grounds it in the entity's actual language.
        qtext = term
        if entry and not args.no_alias:
            als = entry.get("aliases", [])[:8]
            if als:
                qtext = f"{term}（{'，'.join(als)}）"
        try:
            hits = semantic_recall(qtext, args.semantic_k)
        except ImportError as e:
            print(f"!! --semantic needs .venv: {e}", file=sys.stderr)
            sys.exit(2)
        seen = set(results)
        for rowid, score in hits:
            row = db.execute(
                'SELECT rowid, body, corpus_type, source, speaker, "cast" '
                "FROM docs WHERE rowid=?", (rowid,)).fetchone()
            if row[1] in seen:
                continue
            sem.append({"text": row[1], "corpus_type": row[2],
                        "source": row[3], "speaker": row[4], "cast": row[5],
                        "matched_via": ["semantic"], "score": score,
                        "strong": False, "rowid": rowid})

    if args.json:
        print(json.dumps({"strong": strong, "weak": weak, "semantic": sem},
                         ensure_ascii=False, indent=1))
        return

    def show(r):
        via = ",".join(r["matched_via"])
        tags = [r["corpus_type"], r["source"]]
        if r["speaker"]:
            tags.append("说话人:" + r["speaker"])
        if r["cast"]:
            tags.append("在场:" + r["cast"])
        tags.append(f"via:{via} score:{r['score']:.1f}")
        print(f"\n[{' | '.join(tags)}]\n{r['text']}")

    alias_info = f"  aliases: {entry['aliases']}" if entry and len(terms) > 1 else ""
    print(f"query: {term}{alias_info}")
    n_all_weak = len([r for r in results.values() if not r["strong"]])
    print(f"strong: {len(strong)}  weak(noise-suspect, shown {len(weak)}/{n_all_weak})"
          + (f"  semantic: {len(sem)}" if sem else ""))
    if len(terms) > 1:
        print("alias df: " + ", ".join(
            f"{t}={weights[t][1]}" for t in sorted(terms[1:],
                                                   key=lambda t: weights[t][1])))
    print("\n===== 强相关 =====")
    for r in strong:
        show(r)
    if weak:
        print("\n===== 弱相关（仅词面/单一常用别名，可能是噪声）=====")
        for r in weak:
            show(r)
    if sem:
        print("\n===== 语义相关（暗示检索）=====")
        for r in sem:
            show(r)


if __name__ == "__main__":
    main()
