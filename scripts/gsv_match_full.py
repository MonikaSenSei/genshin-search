#!/usr/bin/env python3
"""Full-index probe: parse all Chinese/*.pck external media ids, then test which
hash of GDS Voice source paths reproduces them."""
import json, os, struct, glob, sys, itertools

PCK_DIR = "/mnt/windows_ro/Program Files/miHoYo Launcher/games/Genshin Impact Game/YuanShen_Data/StreamingAssets/AudioAssets/Chinese"
VDIR = os.path.expanduser("~/projects/genshin-search/data/repo/BinOutput/Voice")

def parse_pck_ext(path):
    """return list of (id, off, size) for Externals (media) entries only"""
    out = []
    with open(path, 'rb') as f:
        data = f.read(1 << 20)  # header+index live at the head
    if data[:4] != b'AKPK':
        return out
    p = 4
    def u32():
        nonlocal p
        v = struct.unpack_from('<I', data, p)[0]; p += 4; return v
    header_size = u32(); version = u32()
    sec1 = u32(); sec2 = u32(); sec3 = u32()
    sec4 = 0
    if sec1 + sec2 + sec3 + 0x10 < header_size:
        sec4 = u32()
    # skip Languages (sec1), Banks (sec2: u32 ids), Sounds (sec3: u32 ids)
    pos = 0x1C if sec1 == 0 else None
    # compute section start positions explicitly
    cur = 0x1C
    cur += sec1  # languages
    # banks table
    cur += sec2
    cur += sec3
    if sec4:
        p = cur
        cnt = u32()
        for _ in range(cnt):
            fid = struct.unpack_from('<Q', data, p)[0]; p += 8
            blocksize = struct.unpack_from('<I', data, p)[0]; p += 4
            size = struct.unpack_from('<I', data, p)[0]; p += 4
            offb = struct.unpack_from('<I', data, p)[0]; p += 4
            lang = struct.unpack_from('<I', data, p)[0]; p += 4
            off = offb * blocksize if blocksize else offb
            out.append((fid, off, size, lang))
    return out

def fnv1a64(data):
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b; h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def fnv1_64(data):
    h = 0xcbf29ce484222325
    for b in data:
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        h ^= b
    return h

def main():
    all_ids = {}
    for p in sorted(glob.glob(os.path.join(PCK_DIR, "*.pck"))):
        ents = parse_pck_ext(p)
        for e in ents:
            all_ids[e[0]] = (p, e[1], e[2], e[3])
    print("total media ids:", len(all_ids))

    samples = set()
    for fn in os.listdir(VDIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(VDIR, fn)) as f:
                d = json.load(f)
        except Exception:
            continue
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, dict):
                    for sn in v.get("sourceNames", []):
                        samples.add(sn["sourceFileName"])
    print("distinct source paths from GDS:", len(samples))

    test = list(samples)[:4000]
    algos = {
        'fnv1a-utf8': lambda s: fnv1a64(s.encode('utf-8')),
        'fnv1a-utf16le': lambda s: fnv1a64(s.encode('utf-16-le')),
        'fnv1a-utf16be': lambda s: fnv1a64(s.encode('utf-16-be')),
        'fnv1-utf8': lambda s: fnv1_64(s.encode('utf-8')),
    }
    forms = {
        'raw': lambda s: s,
        'prefix-Chinese-bs': lambda s: "Chinese\\" + s,
        'prefix-Chinese-fs': lambda s: "Chinese/" + s,
        'upper-bs': lambda s: ("Chinese\\" + s).upper(),
        'lower-bs': lambda s: ("Chinese\\" + s).lower(),
        'raw-lower': lambda s: s.lower(),
        'raw-upper': lambda s: s.upper(),
    }
    hit_counts = {}
    for fname, fform in forms.items():
        for aname, alg in algos.items():
            hits = 0
            first = None
            for sp in test:
                hv = alg(fform(sp))
                if hv in all_ids:
                    hits += 1
                    if first is None:
                        first = (sp, hv)
            key = f"{fname}+{aname}"
            hit_counts[key] = hits
            if hits:
                print("HIT", key, hits, first)
    top = sorted(hit_counts.items(), key=lambda kv: -kv[1])[:8]
    for k, v in top:
        print(f"{k}: {v}/{len(test)}")

if __name__ == "__main__":
    main()
