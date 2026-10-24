#!/usr/bin/env python3
"""Dry-run: what would the tolerant join add/change vs the current book_titles.db?"""
import json, os, re, sqlite3, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import obc_books as ob

raw = json.load(open(os.path.join(ROOT, "data", "obc_books_raw.json")))
local, matches = ob.join_all(raw)
db = sqlite3.connect(os.path.join(ROOT, "index", "book_titles.db"))
cur = {r[0]: r[1] for r in db.execute("select book,title from book_titles")}
add = [(b, t) for b, (t, e) in matches.items() if b not in cur]
chg = [(b, cur[b], t) for b, (t, e) in matches.items() if b in cur and cur[b] != t]
print(f"matched now: {len(matches)}  (current rows: {len(cur)})")
print(f"would ADD {len(add)}: ")
for b, t in sorted(add): print("  +", b, t)
print(f"would RETITLE {len(chg)}:")
for b, o, n in sorted(chg): print("  ~", b, repr(o), "->", repr(n))
