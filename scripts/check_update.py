#!/usr/bin/env python3
"""M3 version auto-update pipeline for the AnimeGameData dump.

Checks the latest commit of DimbreathBot/AnimeGameData via api.github.com
(reachable from CN network). If it differs from the stored state, downloads the
changed corpus files (via the gh-proxy mirror — direct raw.githubusercontent is
unreliable here) into data/repo/, and optionally rebuilds index + vectors.

Only directories consumed by build_index.py are tracked:
  TextMap/ Readable/ Subtitle/ ExcelBinOutput/
(BinOutput/ untouched: nothing in the pipeline reads it.)

Usage:
  python3 scripts/check_update.py                 # check only (cheap, daily)
  python3 scripts/check_update.py --apply         # download changed files
  python3 scripts/check_update.py --apply --rebuild   # + rebuild index & vectors (~30 min)
  python3 scripts/check_update.py --simulate <old_sha>  # dry-run diff against an older commit

Prints exactly one human-readable summary line on success.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "index", "update_state.json")
REPO_DIR = os.path.join(ROOT, "data", "repo")
REPO = "DimbreathBot/AnimeGameData"
GH = "https://api.github.com"
PROXY = "https://gh-proxy.com/https://raw.githubusercontent.com"
TRACK_DIRS = ("TextMap", "Readable", "Subtitle", "ExcelBinOutput")

def gh_get(url):
    """curl subprocess: api.github.com works from CN network, but payloads can be
    large and urllib chokes on chunked reads (IncompleteRead). API error bodies
    (rate limit etc.) fail fast with a clear message — retrying can't fix those."""
    for attempt in range(3):
        r = subprocess.run(
            ["curl", "-s", "--max-time", "90", "-H", "User-Agent: genshin-search-updater",
             "-H", "Accept: application/vnd.github+json", url],
            capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            try:
                j = json.loads(r.stdout)
            except json.JSONDecodeError:
                j = None
            if isinstance(j, dict) and "message" in j and "tree" not in j and "sha" not in j:
                raise RuntimeError(f"GitHub API error: {j['message']}")
            if j is not None:
                return j
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"gh_get failed after retries: {url}")

def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {}

def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

def latest_commit():
    c = gh_get(f"{GH}/repos/{REPO}/commits?per_page=1")[0]
    return c["sha"], c["commit"]["committer"]["date"], c["commit"]["message"].splitlines()[0]

# exact inputs build_index.py reads (CHS only — not the whole repo):
#  blobs: TextMap/TextMapCHS.json TextMap/TextMap_MediumCHS.json
#  dirs:  ExcelBinOutput Readable/CHS Subtitle/CHS
TRACK_BLOBS = ["TextMap/TextMapCHS.json", "TextMap/TextMap_MediumCHS.json"]
TRACK_DIRS = ["ExcelBinOutput", "Readable/CHS", "Subtitle/CHS"]

def tree_listing(sha):
    """one non-recursive git/trees call -> {name: {'type','sha'}}"""
    j = gh_get(f"{GH}/repos/{REPO}/git/trees/{sha}")
    return {t["path"]: {"type": t["type"], "sha": t["sha"]} for t in j.get("tree", [])}

def root_tree(commit_sha):
    return tree_listing(commit_sha)

def resolve(root, path):
    """walk a slash path from the commit root tree -> entry or None"""
    listing, ok = root, True
    for part in path.split("/"):
        if not ok or part not in listing:
            return None
        e = listing[part]
        if e["type"] == "blob":
            return e
        listing, ok = tree_listing(e["sha"]), True
    return e

def subtree_blobs(root, dirpath):
    """{path: blob_sha} under a directory, layered non-recursive calls."""
    entry = resolve(root, dirpath)
    if not entry or entry["type"] != "tree":
        return {}
    out, queue = {}, [(dirpath, entry["sha"])]
    while queue:
        prefix, sha = queue.pop()
        for name, e in tree_listing(sha).items():
            if e["type"] == "blob":
                out[f"{prefix}/{name}"] = e["sha"]
            else:
                queue.append((f"{prefix}/{name}", e["sha"]))
    return out

def tree_diff(old_sha, new_sha):
    """changed corpus inputs: list of {filename, status}"""
    old_root, new_root = root_tree(old_sha), root_tree(new_sha)
    files = []
    old, new = {}, {}
    for d in TRACK_DIRS:
        old.update(subtree_blobs(old_root, d))
        new.update(subtree_blobs(new_root, d))
    for b in TRACK_BLOBS:
        for root, acc in ((old_root, old), (new_root, new)):
            e = resolve(root, b)
            if e and e["type"] == "blob":
                acc[b] = e["sha"]
    for p, s in new.items():
        if old.get(p) != s:
            files.append({"filename": p, "status": "modified" if p in old else "added"})
    for p in old:
        if p not in new:
            files.append({"filename": p, "status": "removed"})
    return files

def apply_files(files, sha):
    n_dl = n_del = 0
    for f in files:
        fn = f["filename"]
        local = os.path.join(REPO_DIR, fn)
        if f["status"] == "removed":
            if os.path.exists(local):
                os.remove(local)
                n_del += 1
            continue
        url = f"{PROXY}/{sha}/{fn}"
        tmp = local + ".tmp"
        os.makedirs(os.path.dirname(local), exist_ok=True)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r, open(tmp, "wb") as w:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        w.write(chunk)
                os.replace(tmp, local)
                n_dl += 1
                break
            except Exception as e:
                if attempt == 2:
                    print(f"download failed {fn}: {e}", file=sys.stderr)
                else:
                    time.sleep(3 * (attempt + 1))
    return n_dl, n_del

UA = "genshin-search-updater"

def rebuild():
    print("[rebuild] index ...", flush=True)
    subprocess.run([sys.executable, os.path.join(HERE, "build_index.py")], check=True)
    print("[rebuild] vectors (~21 min) ...", flush=True)
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    subprocess.run([venv_py if os.path.exists(venv_py) else sys.executable,
                    os.path.join(HERE, "build_vectors.py")], check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--simulate", metavar="OLD_SHA")
    args = ap.parse_args()

    st = load_state()
    new_sha, date, tag = latest_commit()
    base_sha = args.simulate or st.get("sha")

    if not base_sha:
        # first run: adopt current state, corpus already present on disk
        if args.simulate is None:
            save_state({"sha": new_sha, "tag": tag, "checked_at": time.strftime("%F %T")})
        print(f"基线已记录：当前数据版本 {tag}（sha {new_sha[:8]}），未做比较" if args.simulate is None
              else f"[simulate] 无基线，无法比较")
        return
    if not args.simulate and new_sha == base_sha:
        save_state({**st, "checked_at": time.strftime("%F %T")})
        print(f"无新版本：语料仍为 {st.get('tag', tag)}（检查于 {time.strftime('%F %T')}）")
        return

    scope = tree_diff(base_sha, new_sha)
    if args.simulate:
        n_scope = len(scope) if scope is not None else "?"
        print(f"[simulate {base_sha[:8]}→{new_sha[:8]}] 语料相关变更 {n_scope} 个（新提交: {tag}）")
        for f in (scope or [])[:10]:
            print("  ", f["status"], f["filename"])
        return

    print(f"发现新版本：{st.get('tag','?')} → {tag}（{date}），语料相关变更 {len(scope) if scope is not None else '?'} 个文件", flush=True)
    if args.apply:
        if scope is None:
            print("无法增量比较；请手动重取全部语料目录。", file=sys.stderr)
            sys.exit(2)
        n_dl, n_del = apply_files(scope, new_sha)
        print(f"已下载 {n_dl} 个文件（删除 {n_del}）", flush=True)
        if args.rebuild:
            rebuild()
        save_state({"sha": new_sha, "tag": tag, "checked_at": time.strftime("%F %T"),
                    "updated_at": time.strftime("%F %T")})
        print(f"更新完成：{tag}（sha {new_sha[:8]}）")
    else:
        print("（仅检测；如需更新请加 --apply --rebuild）")

if __name__ == "__main__":
    main()
