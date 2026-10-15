from __future__ import annotations

import struct
from pathlib import Path


def main() -> None:
    size = 32
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            inside = 4 <= x < 28 and 4 <= y < 28
            b, g, r, a = (30, 255, 216, 255) if inside else (0, 0, 0, 0)
            if 10 <= x < 22 and 10 <= y < 14:
                b, g, r, a = (17, 17, 17, 255)
            if 10 <= x < 14 and 10 <= y < 24:
                b, g, r, a = (17, 17, 17, 255)
            if 18 <= x < 24 and 16 <= y < 24:
                b, g, r, a = (17, 17, 17, 255)
            pixels += bytes([b, g, r, a])

    rows = bytearray()
    for row in range(size - 1, -1, -1):
        rows += pixels[row * size * 4 : (row + 1) * size * 4]

    mask_stride = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * size)
    dib = (
        struct.pack("<IIIHHIIIIII", 40, size, size * 2, 1, 32, 0, len(rows), 0, 0, 0, 0)
        + rows
        + mask
    )
    ico = struct.pack("<HHH", 0, 1, 1)
    ico += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(dib), 6 + 16)
    ico += dib

    icon_path = Path("apps/studio-web/src-tauri/icons/icon.ico")
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    icon_path.write_bytes(ico)


if __name__ == "__main__":
    main()
