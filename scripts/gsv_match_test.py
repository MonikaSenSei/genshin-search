#!/usr/bin/env python3
"""Match GDS Voice sourceNames to pck entries by trying Wwise-style hashes."""
import json, os, struct, glob, sys

PCK = "/mnt/windows_ro/Program Files/miHoYo Launcher/games/Genshin Impact Game/YuanShen_Data/StreamingAssets/AudioAssets/Chinese/1001.pck"

def parse_pck(path):
    with open(path,'rb') as f:
        if f.read(4) != b'AKPK':
            raise ValueError('bad magic')
        u32 = lambda: struct.unpack('<I', f.read(4))[0]
        u64 = lambda: struct.unpack('<Q', f.read(8))[0]
        header_size = u32(); version = u32()
        sec1 = u32(); sec2 = u32(); sec3 = u32()
        if sec1+sec2+sec3+0x10 < header_size:
            sec4 = u32()
        else:
            sec4 = 0
        entries = []
        use64 = False
        for secsize in (sec1, sec2, sec3, sec4):
            if secsize == 0:
                continue
            # file table: entry_size inference like ZZAR
            count = u32()
            if count == 0:
                continue
            entry_size = (secsize - 4) / count
            use64 = entry_size >= 24
            for _ in range(count):
                fid = u64() if use64 else u32()
                blocksize = u32(); size = u32(); offb = u32(); lang = u32()
                off = offb * blocksize if blocksize else offb
                entries.append((fid, off, size, lang))
        return entries

def fnv1a64(data: bytes) -> int:
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def fnv1_64(data: bytes) -> int:
    h = 0xcbf29ce484222325
    for b in data:
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        h ^= b
    return h

def variants(path: str):
    """candidate normalized strings for hashing"""
    cands = set()
    up = path.upper()
    for p in (path, up):
        for sep in ('\\', '/'):
            s = p.replace('\\', sep)
            for prefix in ('', 'Chinese' + sep, 'Chinese'+sep+'VO'+sep):
                cands.add(prefix + s)
                cands.add(prefix + s.lower())
    return cands

def hashes(s: str):
    out = {}
    for enc in ('utf-8', 'utf-16-le', 'utf-16-be'):
        b = s.encode(enc)
        out[f'fnv1a:{enc}'] = fnv1a64(b)
        out[f'fnv1:{enc}'] = fnv1_64(b)
    return out

# collect sample source names from a couple GDS files
vdir = os.path.expanduser("~/projects/genshin-search/data/repo/BinOutput/Voice")
samples = []
for fn in sorted(x for x in os.listdir(vdir) if x.endswith(".json"))[:50]:
    with open(os.path.join(vdir, fn)) as f:
        d = json.load(f)
    for v in d.values():
        for sn in v.get("sourceNames", []):
            samples.append(sn["sourceFileName"])
print("samples collected:", len(samples))

ids = set(e[0] for e in parse_pck(PCK))
print("entries in 1001.pck:", len(ids))

# brute force: for each sample compute many hash variants, test membership
hits = {}
for sp in samples:
    for cand in variants(sp):
        for label, hv in hashes(cand).items():
            if hv in ids:
                hits[(label, 'orig' if cand == sp else 'variant')] = (sp, cand)
                break
        if hits: break
    if hits: break

for k, (sp, cand) in list(hits.items())[:10]:
    print("HIT", k, sp, "->", cand)
if not hits:
    # show one id hex to see digit width
    sample_id = next(iter(ids))
    print("no hit; sample id:", hex(sample_id))
    # try: maybe ids are just the filename stem decimal?
    stem = samples[0].split('\\')[-1].split('.')[0]
    print("stem:", stem)
