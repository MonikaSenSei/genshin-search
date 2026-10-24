#!/usr/bin/env python3
"""M2 alias candidate nomination (human-review report, never auto-added).

Given a term + its verified aliases in alias_table.json:
  S = docs in the index matching the literal term or any verified alias
  candidate CJK n-grams (2..6) occurring >= MIN_IN_S times inside S
  nominate if: rare in corpus (df_corpus <= MAX_DF), concentrated in S
  (count_in_S / df_corpus >= PRECISION), not an existing term/alias,
  not a substring/superstring of one.
Report: aliases/candidates_<term>.md + .json
"""
import argparse
import json
import os
import re
import sqlite3
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "index", "genshin.db")
ALIASES = os.path.join(ROOT, "aliases", "alias_table.json")

MIN_IN_S = 3
MAX_DF = 60
PRECISION = 0.5
MAX_REPORT = 25

CJK_RUN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]{2,}")


def phrase(t):
    toks = re.findall(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+", t)
    return '"' + " ".join(toks) + '"'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("term")
    args = ap.parse_args()

    table = json.load(open(ALIASES, encoding="utf-8"))
    entry = next((e for e in table if e["term"] == args.term), None)
    if entry is None:
        raise SystemExit(f"{args.term} not in alias table; add verified forms first")
    known = [args.term] + entry.get("aliases", [])

    db = sqlite3.connect(DB)
    S = []          # seed docs: (body,)
    seen = set()
    for t in known:
        for (body,) in db.execute("SELECT body FROM docs WHERE docs MATCH ?",
                                  (phrase(t),)):
            if body not in seen:
                seen.add(body)
                S.append(body)
    print(f"seed docs: {len(S)}")

    # candidate n-grams inside S
    in_s = Counter()
    for doc in S:
        grams = set()
        for run in CJK_RUN.findall(doc):
            n = len(run)
            for L in range(2, min(6, n) + 1):
                for i in range(n - L + 1):
                    grams.add(run[i:i + L])
        in_s.update(grams)
    cands = {g: c for g, c in in_s.items() if c >= MIN_IN_S}
    print(f"candidates with >={MIN_IN_S} in-S occurrences: {len(cands)}")

    def norm(g):
        return g not in known and not any(
            g in k or k in g for k in known)

    # drop fragments that start/end on a function word — real entity names
    # do not begin with 的/之/与 or end on them
    FUNC = set("的了和与之是在于其此该等being ")
    def func_bounded(g):
        return g[0] in FUNC or g[-1] in FUNC

    scored = []
    for g, c in cands.items():
        if not norm(g) or func_bounded(g):
            continue
        df = db.execute("SELECT count(*) FROM docs WHERE docs MATCH ?",
                        (phrase(g),)).fetchone()[0]
        if df == 0 or df > MAX_DF:
            continue
        prec = c / df
        if prec < PRECISION or prec >= 0.999 and len(g) <= 3:
            # >0.999 means every corpus hit is inside the seed set — fine for
            # long phrases, but for <=3-char grams that is suspicious: the
            # gram was found through an alias, so its "S" membership is circular
            if not (prec > 0.999 and len(g) >= 4):
                continue
        example = next(doc for doc in S if g in doc)
        scored.append({"gram": g, "in_seed": c, "df_corpus": df,
                       "precision": round(prec, 3),
                       "example": example[:120]})
    scored.sort(key=lambda x: (-x["in_seed"], x["df_corpus"]))
    # keep only maximal grams: drop any candidate contained in a longer one
    by_gram = {s["gram"]: s for s in scored}
    keep = [s for s in scored
            if not any(other != s["gram"] and s["gram"] in other
                       and other in by_gram for other in by_gram)]
    scored = keep

    out_md = os.path.join(ROOT, "aliases", f"candidates_{args.term}.md")
    out_js = os.path.join(ROOT, "aliases", f"candidates_{args.term}.json")
    json.dump(scored, open(out_js, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# 别名候选提名：{args.term}\n")
        f.write(f"种子文档 {len(S)} 篇；候选 {len(cands)} 个；"
                f"通过筛选 {len(scored)} 个（前 {min(MAX_REPORT, len(scored))} 列出）。\n")
        f.write("仅为提名，须人工验证后再入别名表。\n\n")
        for s in scored[:MAX_REPORT]:
            f.write(f"## {s['gram']}\n- 种子集内出现 {s['in_seed']} / "
                    f"全库 {s['df_corpus']}（precision {s['precision']}）\n"
                    f"- 例：{s['example']}\n\n")
    print(f"nominated: {len(scored)} -> {out_md}")
    for s in scored[:MAX_REPORT]:
        print(f"  {s['gram']}\tin_seed={s['in_seed']} df={s['df_corpus']}")


if __name__ == "__main__":
    main()
