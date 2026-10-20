"""Stream-extract files from a Unity macOS target-support .pkg: a xar archive whose "Payload" is a
gzip-compressed odc cpio archive.

Only the requested files are written, so the ~500 MB package never has to be stored.
"""
import struct
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

CHUNK = 1 << 20


class Reader:
    """Sequential reader that can skip forward."""

    def __init__(self, f: BinaryIO):
        self.f = f
        self.pos = 0

    def read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.f.read(min(CHUNK, n - len(data)))
            if not chunk:
                break
            data += chunk
        self.pos += len(data)
        return data

    def skip_to(self, pos: int) -> None:
        if pos < self.pos:
            raise ValueError("cannot seek backwards in stream")
        while self.pos < pos:
            if not self.read(min(CHUNK, pos - self.pos)):
                raise EOFError("unexpected end of xar archive")


def _find_payload(toc_xml: bytes) -> tuple[int, int, str]:
    """Offset (in the heap), length and encoding of the Payload entry."""
    for f in ET.fromstring(toc_xml).iter("file"):
        if f.findtext("name") in ("Payload", "Payload~"):
            offset, length = f.findtext("data/offset"), f.findtext("data/length")
            encoding = f.find("data/encoding")
            if offset is None or length is None or encoding is None:
                raise ValueError("incomplete Payload entry in pkg")
            return int(offset), int(length), encoding.get("style", "")
    raise ValueError("no Payload in pkg")


def _cpio_members(stream: Iterator[bytes]):
    """Yield (name, mode, data chunks) for each member of an odc cpio stream."""
    buf = b""

    def need(n: int) -> None:
        nonlocal buf
        while len(buf) < n:
            chunk = next(stream, None)
            if chunk is None:
                raise EOFError("truncated cpio archive")
            buf += chunk

    while True:
        need(76)
        header = buf[:76]
        if header[:6] != b"070707":
            raise ValueError(f"bad cpio magic {header[:6]!r}")
        mode = int(header[18:24], 8)
        namesize = int(header[59:65], 8)
        filesize = int(header[65:76], 8)
        need(76 + namesize)
        name = buf[76:76 + namesize - 1].decode("utf-8", "replace")
        buf = buf[76 + namesize:]
        if name == "TRAILER!!!":
            return
        remaining = filesize

        def data_chunks():
            nonlocal buf, remaining
            while remaining:
                if not buf:
                    need(1)
                take = buf[:remaining]
                buf = buf[len(take):]
                remaining -= len(take)
                yield take

        yield name, mode, data_chunks
        for _ in data_chunks():  # drain what the caller didn't read
            pass


def extract(source: BinaryIO, out_dir: Path, paths: list[str],
            progress: Callable[[int, int], None] | None = None) -> list[str]:
    """Write the regular files whose path (without "./") starts with one of paths into out_dir.
    Returns the extracted paths; progress(bytes read, total) is called as the payload streams."""
    reader = Reader(source)
    magic, header_size, _version, toc_len, _toc_len_raw, _cksum = struct.unpack(">4sHHQQI", reader.read(28))
    if magic != b"xar!":
        raise ValueError("not a xar archive")
    reader.read(header_size - 28)
    toc = zlib.decompress(reader.read(toc_len))
    offset, length, encoding = _find_payload(toc)
    reader.skip_to(header_size + toc_len + offset)
    # The xar entry is either compressed by xar itself or stored raw; Unity stores a
    # gzip-compressed cpio raw ("application/octet-stream"). Both inflate the same way.
    first = reader.read(2)
    if "gzip" not in encoding and "zlib" not in encoding and first != b"\x1f\x8b":
        raise ValueError(f"unsupported payload encoding {encoding}")
    inflater = zlib.decompressobj(47)  # zlib or gzip header

    def payload() -> Iterator[bytes]:
        yield inflater.decompress(first)
        left = length - len(first)
        while left:
            chunk = reader.read(min(CHUNK, left))
            if not chunk:
                raise EOFError("truncated payload")
            left -= len(chunk)
            if progress:
                progress(length - left, length)
            data = inflater.decompress(chunk)
            if data:
                yield data
        tail = inflater.flush()
        if tail:
            yield tail

    extracted = []
    for name, mode, data_chunks in _cpio_members(payload()):
        rel = name.removeprefix("./")
        if not any(rel.startswith(p) for p in paths) or (mode & 0o170000) != 0o100000:
            continue
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("wb") as f:
            for chunk in data_chunks():
                f.write(chunk)
        extracted.append(rel)
    return extracted
