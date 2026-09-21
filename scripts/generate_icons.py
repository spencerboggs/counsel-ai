"""Generate minimal Tauri icons."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def write_png(size: int, rgb: tuple[int, int, int] = (15, 92, 76)) -> bytes:
    width = height = size
    r, g, b = rgb
    raw = b"".join(b"\x00" + bytes([r, g, b]) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_ico(path: Path, sizes: list[int]) -> None:
    images = [(size, write_png(size)) for size in sizes]
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    blobs = b""
    for size, blob in images:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + entries + blobs)


def main() -> None:
    icons = Path(__file__).resolve().parents[1] / "src-tauri" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    (icons / "32x32.png").write_bytes(write_png(32))
    (icons / "128x128.png").write_bytes(write_png(128))
    (icons / "128x128@2x.png").write_bytes(write_png(256))
    (icons / "icon.png").write_bytes(write_png(512))
    write_ico(icons / "icon.ico", [16, 32, 48, 256])
    # Placeholder icns (macOS packaging can regenerate later)
    (icons / "icon.icns").write_bytes(write_png(512))
    print(f"Wrote icons to {icons}")


if __name__ == "__main__":
    main()
