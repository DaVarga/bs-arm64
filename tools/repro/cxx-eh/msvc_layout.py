#!/usr/bin/env python3
"""Shorten a function's ARM64 unwind range by one instruction, so that it ends right after its last
call, like MSVC lays out functions that end with a call to a noreturn function (clang adds a brk).

    msvc_layout.py <dll> <function RVA hex>
"""
import struct, sys

path, rva = sys.argv[1], int(sys.argv[2], 16)
b = bytearray(open(path, 'rb').read())
pe = struct.unpack_from('<I', b, 0x3c)[0]
nsec = struct.unpack_from('<H', b, pe + 6)[0]
opt = pe + 24
optsize = struct.unpack_from('<H', b, pe + 20)[0]
exc_rva, exc_size = struct.unpack_from('<II', b, opt + 112 + 3 * 8)  # data directory 3: exception
secs = []
for i in range(nsec):
    s = pe + 24 + optsize + i * 40
    vsize, va, rawsize, raw = struct.unpack_from('<IIII', b, s + 8)
    secs.append((va, max(vsize, rawsize), raw))

def off(r):
    for va, size, raw in secs:
        if va <= r < va + size:
            return raw + r - va
    raise SystemExit(f'RVA {r:#x} not in any section')

for i in range(exc_size // 8):
    begin, unwind = struct.unpack_from('<II', b, off(exc_rva) + i * 8)
    if begin != rva:
        continue
    if unwind & 3:
        raise SystemExit('packed unwind data, not handled')
    x = off(unwind)
    word = struct.unpack_from('<I', b, x)[0]
    length = word & 0x3ffff
    struct.pack_into('<I', b, x, (word & ~0x3ffff) | (length - 1))
    open(path, 'wb').write(b)
    print(f'function {rva:#x}: length {length * 4} -> {(length - 1) * 4} bytes')
    break
else:
    raise SystemExit(f'no .pdata entry for {rva:#x}')
