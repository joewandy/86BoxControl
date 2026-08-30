#!/usr/bin/env python3
"""Reject guest executables that do not have the intended Win98 PE boundary."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ALLOWED_IMPORTS = {
    "GDI32.DLL",
    "KERNEL32.DLL",
    "MSVCRT.DLL",
    "SHELL32.DLL",
    "USER32.DLL",
    "WSOCK32.DLL",
}


class InvalidPE(ValueError):
    pass


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def inspect(path: Path) -> set[str]:
    data = path.read_bytes()
    if data[:2] != b"MZ" or len(data) < 0x40:
        raise InvalidPE("missing DOS header")
    pe = _u32(data, 0x3C)
    if data[pe : pe + 4] != b"PE\0\0":
        raise InvalidPE("missing PE signature")
    coff = pe + 4
    machine = _u16(data, coff)
    section_count = _u16(data, coff + 2)
    optional_size = _u16(data, coff + 16)
    optional = coff + 20
    if machine != 0x14C:
        raise InvalidPE(f"machine is 0x{machine:04x}, expected Intel 386")
    if _u16(data, optional) != 0x10B:
        raise InvalidPE("not a PE32 image")
    subsystem_major = _u16(data, optional + 48)
    subsystem = _u16(data, optional + 68)
    if subsystem != 2 or subsystem_major > 4:
        raise InvalidPE(
            f"subsystem is {subsystem} version {subsystem_major}, expected Windows GUI <= 4"
        )
    import_rva = _u32(data, optional + 104)
    sections_offset = optional + optional_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        section = sections_offset + index * 40
        virtual_size = _u32(data, section + 8)
        virtual_address = _u32(data, section + 12)
        raw_size = _u32(data, section + 16)
        raw_offset = _u32(data, section + 20)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset, raw_size))

    def rva_offset(rva: int) -> int:
        for virtual_address, size, raw_offset, raw_size in sections:
            if virtual_address <= rva < virtual_address + size:
                delta = rva - virtual_address
                if delta >= raw_size:
                    break
                return raw_offset + delta
        raise InvalidPE(f"RVA 0x{rva:x} is outside file-backed sections")

    imports: set[str] = set()
    if import_rva:
        descriptor = rva_offset(import_rva)
        while any(data[descriptor : descriptor + 20]):
            name_rva = _u32(data, descriptor + 12)
            name_offset = rva_offset(name_rva)
            end = data.find(b"\0", name_offset)
            if end < 0:
                raise InvalidPE("unterminated import name")
            imports.add(data[name_offset:end].decode("ascii").upper())
            descriptor += 20
    unexpected = imports - ALLOWED_IMPORTS
    if unexpected:
        raise InvalidPE(f"imports unsupported DLLs: {', '.join(sorted(unexpected))}")
    return imports


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: check-win98-pe.py EXECUTABLE...", file=sys.stderr)
        return 2
    failed = False
    for name in argv:
        path = Path(name)
        try:
            imports = inspect(path)
        except (InvalidPE, OSError, struct.error, UnicodeDecodeError) as exc:
            failed = True
            print(f"FAIL {path}: {exc}", file=sys.stderr)
        else:
            print(f"PASS {path}: {', '.join(sorted(imports))}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
