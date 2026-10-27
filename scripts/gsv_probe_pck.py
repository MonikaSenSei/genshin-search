#!/usr/bin/env python3
"""Probe Genshin Chinese .pck (AKPK) index format and test Wwise FNV mapping.

Goal: confirm we can map GDS BinOutput/Voice sourceFileName paths to media ids
inside Chinese/NNNN.pck, so we can extract per-character voice lines.
"""
import json, struct, sys, os, glob

PCK_DIR = "/mnt/windows_ro/Program Files/miHoYo Launcher/games/Genshin Impact Game/YuanShen_Data/StreamingAssets/AudioAssets/Chinese"

def fnv1a64(s: str) -> int:
    h = 0xcbf29ce484222325
    for b in s.encode("utf-16-le"):  # Wwise often hashes utf16? try both
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def fnv1a64_u8(s: str) -> int:
    h = 0xcbf29ce484222325
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def parse_pck_header(path, maxlen=4096):
    with open(path, 'rb') as f:
        head = f.read(maxlen)
    print("magic:", head[:8])
    # dump u32/u64 fields
    for off in range(8, 40, 4):
        print(f"u32@{off}: {struct.unpack_from('<I', head, off)[0]}")
    # The earlier xxd of Banks0.pck: magic 'AKPK04', then 01 00 01 00 00 00 | 7c000000 idx_off=124? | count...
    # Try: u32@12 = index offset; u32@16 = index size?
    idx_off = struct.unpack_from('<I', head, 12)[0]
    v16 = struct.unpack_from('<I', head, 16)[0]
    v20 = struct.unpack_from('<I', head, 20)[0]
    print("guessed idx_off:", idx_off, "v16:", v16, "v20:", v20)
    return idx_off

def try_index(path):
    with open(path, 'rb') as f:
        head = f.read(1 << 20)
    idx_off = struct.unpack_from('<I', head, 12)[0]
    # entry guesses: (u64 id, u64 offset, u32 size) = 20B, or (u32 id...), or u16 id...
    # from Banks0 xxd: after header region there were (u32,u32) pairs starting ~0x2C: 2c 00,02 00 | 3c 00,01 00 ... looks like (u32 offset, u32 next?) pairs...
    # But that's Banks0 (a bank pkg). Chinese/1001.pck may differ; dump its header.
    with open(path, 'rb') as f:
        h = f.read(0x100)
    print("head hex:")
    for i in range(0, 0x60, 16):
        row = h[i:i+16]
        print(f"{i:04x} " + " ".join(f"{b:02x}" for b in row))

def main():
    pcks = sorted(glob.glob(os.path.join(PCK_DIR, "*.pck")))
    print("pck count:", len(pcks))
    p = pcks[0]
    print("probe:", p, os.path.getsize(p))
    try_index(p)
    # collect known sample sourceFileName from GDS
    vdir = os.path.expanduser("~/projects/genshin-search/data/repo/BinOutput/Voice")
    sample = None
    with open(os.path.join(vdir, "003f9067.json")) as f:
        d = json.load(f)
    sample = list(d.values())[0]["sourceNames"][0]["sourceFileName"]
    print("sample src:", sample)
    cands = []
    for variant in [
        "Chinese\\" + sample,
        "Chinese/" + sample,
        sample,
        ("Chinese\\" + sample).lower(),
    ]:
        cands.append((variant, fnv1a64_u8(variant), fnv1a64(variant)))
    for v, a, b in cands:
        print(f"u8fnv :{a:#018x} utf16fnv:{b:#018x}  {v}")

if __name__ == "__main__":
    main()
