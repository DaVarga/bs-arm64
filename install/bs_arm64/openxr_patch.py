"""Make Unity's UWP ARM64 UnityOpenXR.dll loadable in a desktop (Wine) process.

Unity ships UnityOpenXR.dll for ARM64 only as a UWP (Windows Store app) build. It's the same code
as a desktop build, but it imports three things a desktop process doesn't have:

- MSVCP140_APP.dll, VCRUNTIME140_APP.dll: the Store versions of the C++ runtime. The desktop
  msvcp140.dll / vcruntime140.dll have the same functions.
- LoadPackagedLibrary: loads a DLL from the app's package. Wine only has a stub (there is no
  package). LoadLibraryW does the same for us; its signature lacks the second, "reserved" argument,
  which is harmless on ARM64 (arguments are passed in registers, the extra one is ignored).

How a DLL names its imports (PE format, "import directory"):

  import directory: one 20-byte descriptor per imported DLL, ending with an all-zero one
    descriptor: OriginalFirstThunk | TimeDateStamp | ForwarderChain | Name | FirstThunk
      Name -> "MSVCP140_APP.dll\\0"                          (the DLL to load)
      OriginalFirstThunk -> list of 8-byte entries, ending with 0, one per imported function
        entry -> hint/name: 2-byte hint, then "FunctionName\\0"
               (if the top bit is set, the entry is an ordinal number instead; we skip those)

All of these are RVAs (addresses once loaded), which offset() turns into file positions.

The patch only overwrites strings in place, with a shorter or equally long name padded with NUL
bytes, so nothing in the file moves:
  "MSVCP140_APP.dll"     -> "msvcp140.dll"
  "VCRUNTIME140_APP.dll" -> "vcruntime140.dll"
  the DLL that provides LoadPackagedLibrary (an api-ms-win-... set) -> "kernel32.dll",
  and its function name "LoadPackagedLibrary" -> "LoadLibraryW"
"""
import struct

IMAGE_FILE_MACHINE_ARM64 = 0xAA64
IMPORT_DIRECTORY = 1            # index of the import table in the optional header's data directories
ORDINAL_FLAG64 = 1 << 63        # import by number, not by name


class PE:
    """Just enough of a PE32+ (64-bit) image to walk its imports."""

    def __init__(self, data: bytearray):
        self.data = data
        # The DOS header at 0x3C points at the "PE\0\0" signature; the COFF header follows it.
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a PE file")
        self.machine, nsections = struct.unpack_from("<HH", data, pe + 4)
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24                                   # optional header
        if struct.unpack_from("<H", data, opt)[0] != 0x20B:
            raise ValueError("not a PE32+ image")
        # The data directories start 112 bytes into a PE32+ optional header, 8 bytes (RVA, size) each.
        self.import_rva = struct.unpack_from("<I", data, opt + 112 + IMPORT_DIRECTORY * 8)[0]
        # Section table, right after the optional header: where each section's bytes are in the file
        self.sections = []
        for i in range(nsections):
            s = opt + opt_size + i * 40
            vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", data, s + 8)
            self.sections.append((va, max(vsize, rawsize), rawptr))

    def offset(self, rva: int) -> int:
        """File position of an RVA: find the section that contains it."""
        for va, size, raw in self.sections:
            if va <= rva < va + size:
                return rva - va + raw
        raise ValueError(f"RVA {rva:#x} outside all sections")

    def cstr(self, rva: int) -> bytes:
        """The NUL-terminated string at an RVA."""
        off = self.offset(rva)
        return bytes(self.data[off:self.data.index(b"\0", off)])

    def imports(self):
        """Yield (RVA of the DLL name, DLL name, [(RVA of the hint/name entry, function name)])
        for every imported DLL."""
        off = self.offset(self.import_rva)
        while True:
            original_first_thunk, _timestamp, _forwarder, name_rva, first_thunk = \
                struct.unpack_from("<IIIII", self.data, off)
            if not name_rva:                            # the all-zero descriptor ends the list
                return
            thunk = self.offset(original_first_thunk or first_thunk)
            funcs = []
            while True:
                entry = struct.unpack_from("<Q", self.data, thunk)[0]
                if not entry:
                    break
                if not entry & ORDINAL_FLAG64:
                    funcs.append((entry, self.cstr(entry + 2)))     # skip the 2-byte hint
                thunk += 8
            yield name_rva, self.cstr(name_rva), funcs
            off += 20


def patch(dll: bytes) -> bytes:
    """The patched DLL. Raises ValueError if the import layout isn't the one we know, rather than
    writing a DLL that would fail at load time."""
    data = bytearray(dll)
    pe = PE(data)
    if pe.machine != IMAGE_FILE_MACHINE_ARM64:
        raise ValueError(f"expected an ARM64 image, got machine {pe.machine:#x}")

    def overwrite(rva: int, old: bytes, new: bytes) -> None:
        """Replace the string old at rva with new, padded with NUL bytes to the same length."""
        off = pe.offset(rva)
        if data[off:off + len(old)] != old or len(new) > len(old):
            raise ValueError(f"cannot replace {old!r}")
        data[off:off + len(old)] = new.ljust(len(old), b"\0")

    renames = {b"MSVCP140_APP.dll": b"msvcp140.dll", b"VCRUNTIME140_APP.dll": b"vcruntime140.dll"}
    patched = set()
    for name_rva, dll_name, funcs in list(pe.imports()):
        if dll_name in renames:
            overwrite(name_rva, dll_name, renames[dll_name])
            patched.add(dll_name.decode())
        for hint_rva, func in funcs:
            if func == b"LoadPackagedLibrary":
                # We point the whole descriptor at kernel32.dll, so it must import nothing else
                # (another function of that api-ms-win DLL might not be in kernel32).
                if len(funcs) != 1:
                    raise ValueError("LoadPackagedLibrary shares its import descriptor; cannot redirect the DLL")
                overwrite(name_rva, dll_name, b"kernel32.dll")
                overwrite(hint_rva + 2, b"LoadPackagedLibrary", b"LoadLibraryW")
                patched.add("LoadPackagedLibrary")
    if patched != {"MSVCP140_APP.dll", "VCRUNTIME140_APP.dll", "LoadPackagedLibrary"}:
        raise ValueError(f"unexpected import layout; patched only {sorted(patched)}")
    return bytes(data)
