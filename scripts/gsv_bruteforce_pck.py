#!/usr/bin/env python3
"""Brute-force the AKPK index layout of Genshin Chinese/NNNN.pck.
Hypothesis to test: header + N entries with fixed stride; entries contain
file data offsets that must be ascending and bounded by file size; one u64
field should match Wwise-style ids; sizes should be plausible (KB..MB)."""
import struct, sys

P = "/mnt/windows_ro/Program Files/miHoYo Launcher/games/Genshin Impact Game/YuanShen_Data/StreamingAssets/AudioAssets/Chinese/1001.pck"
data = open(P, 'rb').read(0x2200)
FSIZE = 18369985

def try_layout(idx_start, stride, id_off, off_off, size_off, use64off=False, size_fmt='<I'):
    entries = []
    p = idx_start
    while p + stride <= 0x21cc:
        idv = struct.unpack_from('<Q', data, p + id_off)[0] if True else None
        off = struct.unpack_from('<Q' if use64off else '<I', data, p + off_off)[0]
        size = struct.unpack_from(size_fmt, data, p + size_off)[0]
        if size == 0 or size > FSIZE or off >= FSIZE:
            return None
        entries.append((idv, off, size))
        p += stride
    if len(entries) < 10:
        return None
    offs = [e[1] for e in entries]
    if offs != sorted(offs):
        return None
    return entries

best = None
for idx_start in (0x30, 0x34, 0x38, 0x3c, 0x40, 0x44, 0x48, 0x4c):
    for stride in (16, 20, 24, 28, 32, 36, 40):
        for off_off in range(0, stride - 3):
            for size_off in range(off_off + 4, stride - 3):
                for use64 in (False, True):
                    r = try_layout(idx_start, stride, 0, off_off, size_off, use64)
                    if r:
                        # plausibility: max(offset+size) should approach typical data usage
                        mx = max(e[1] + e[2] for e in r)
                        if 0.5 * FSIZE <= mx <= FSIZE:
                            cand = (idx_start, stride, 0, off_off, size_off, use64, len(r), mx)
                            if best is None or len(r) > best[6]:
                                best = cand
                            print("CAND", cand)
if best:
    print("BEST:", best)
    idx_start, stride, id_off, off_off, size_off, use64, n, mx = best
    # dump a few ids
    for p in range(idx_start, idx_start + 5 * stride, stride):
        print("id=%016x off=%d size=%d" % (struct.unpack_from('<Q', data, p + id_off)[0],
              struct.unpack_from('<Q' if use64 else '<I', data, p + off_off)[0],
              struct.unpack_from('<I', data, p + size_off)[0]))
else:
    print("NO LAYOUT FOUND — manual analysis needed")
