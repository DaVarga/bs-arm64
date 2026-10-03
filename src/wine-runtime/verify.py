#!/usr/bin/env python3
"""Check the three game-local CRT DLLs before packaging them."""
import struct
import sys
from pathlib import Path


class PE:
    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        pe = struct.unpack_from('<I', self.data, 0x3c)[0]
        if self.data[pe:pe + 4] != b'PE\0\0':
            raise ValueError(f'{path.name}: not a PE image')
        machine, count = struct.unpack_from('<HH', self.data, pe + 4)
        opt = pe + 24
        if machine != 0xaa64 or struct.unpack_from('<H', self.data, opt)[0] != 0x20b:
            raise ValueError(f'{path.name}: not pure ARM64 PE32+')
        if self.data[64:81] == b'Wine builtin DLL\0':
            raise ValueError(f'{path.name}: builtin marker would bypass the local DLL')
        size = struct.unpack_from('<H', self.data, pe + 20)[0]
        self.sections = [struct.unpack_from('<IIII', self.data, opt + size + i * 40 + 8)
                         for i in range(count)]
        self.export_rva, self.export_size = struct.unpack_from('<II', self.data, opt + 112)
        self.import_rva = struct.unpack_from('<I', self.data, opt + 120)[0]

    def offset(self, rva):
        for vsize, va, rawsize, raw in self.sections:
            if va <= rva < va + max(vsize, rawsize):
                return raw + rva - va
        raise ValueError(f'{self.path.name}: invalid RVA {rva:#x}')

    def string(self, rva):
        off = self.offset(rva)
        return self.data[off:self.data.index(b'\0', off)].decode('ascii')

    def imports(self):
        result = set()
        if self.import_rva:
            off = self.offset(self.import_rva)
            while True:
                name = struct.unpack_from('<I', self.data, off + 12)[0]
                if not name:
                    break
                result.add(self.string(name).lower())
                off += 20
        return result

    def forwarders(self):
        off = self.offset(self.export_rva)
        count, functions, names, ordinals = struct.unpack_from('<IIII', self.data, off + 24)
        result = {}
        for i in range(count):
            name = self.string(struct.unpack_from('<I', self.data, self.offset(names) + i * 4)[0])
            ordinal = struct.unpack_from('<H', self.data, self.offset(ordinals) + i * 2)[0]
            target = struct.unpack_from('<I', self.data, self.offset(functions) + ordinal * 4)[0]
            if self.export_rva <= target < self.export_rva + self.export_size:
                result[name] = self.string(target)
        return result


def verify(directory):
    for name in ('ucrtbs64.dll', 'vcruntime140.dll', 'msvcp140.dll'):
        pe = PE(directory / name)
        imports = pe.imports()
        if 'ucrtbase.dll' in imports:
            raise ValueError(f'{name}: imports the shared UCRT')
        if b'ucrtbase.dll\0' in pe.data.lower():
            raise ValueError(f'{name}: contains a shared UCRT lookup name')
        if name != 'ucrtbs64.dll' and 'ucrtbs64.dll' not in imports:
            raise ValueError(f'{name}: missing private UCRT import')
        forwarders = pe.forwarders()
        if any(value.lower().startswith('ucrtbase.') for value in forwarders.values()):
            raise ValueError(f'{name}: forwards to the shared UCRT')
        if name == 'vcruntime140.dll':
            for symbol in ('_CxxThrowException', '__CxxFrameHandler3', '__DestructExceptionObject'):
                if forwarders.get(symbol) != f'ucrtbs64.{symbol}':
                    raise ValueError(f'{name}: {symbol} does not use the private exception handler')
        print(f'{name}: pure ARM64, application-local runtime verified')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]))
    except (ValueError, OSError, IndexError, struct.error) as exc:
        sys.exit(str(exc))
