#!/usr/bin/env python3
"""Draw the images of the eval suites (evals/images/*.png) with the Python standard library only.

  python3 evals/images/make_images.py           write every image next to this file
  python3 evals/images/make_images.py --check   exit 1 when a committed image's pixels differ

Each image is one line of capital letters and digits from a 5x7 pixel font, scaled up, black on
white, written as an 8-bit RGB PNG. tools/tests/test_eval.py compares the pixels of the committed
files with these drawings, so the binary files hold nothing but what this script draws. The
compressed bytes may differ between zlib builds; the pixels do not.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

# File name -> the text drawn. The format suite's image case asks the model to read it back.
IMAGES = {"maple-74.png": "MAPLE 74"}

WIDTH, HEIGHT = 640, 160  # multiples of 32, the patch grid of the Qwen3.x vision projectors
SCALE = 12  # screen pixels per font pixel
INK, PAPER = (0, 0, 0), (255, 255, 255)
SIGNATURE = b"\x89PNG\r\n\x1a\n"

# 5x7 glyphs, "#" is ink. Only the characters IMAGES uses, chosen so none can be read as another
# (no O/0, I/1, S/5, B/8).
FONT = {
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
}


def render(text: str) -> list[bytes]:
    """The RGB rows of one image: text centred on a WIDTH x HEIGHT canvas."""
    cells_wide = len(text) * 6 - 1  # 5 columns per glyph and 1 between glyphs
    left = (WIDTH - cells_wide * SCALE) // 2
    top = (HEIGHT - 7 * SCALE) // 2
    if left < 0 or top < 0:
        raise ValueError(f"{text!r} does not fit on {WIDTH}x{HEIGHT} at scale {SCALE}")
    ink = set()
    for index, char in enumerate(text):
        for row, line in enumerate(FONT[char]):
            for column, mark in enumerate(line):
                if mark == "#":
                    ink.add((row, index * 6 + column))
    rows = []
    for y in range(HEIGHT):
        cell_row = (y - top) // SCALE if y >= top else -1
        pixels = bytearray()
        for x in range(WIDTH):
            cell_column = (x - left) // SCALE if x >= left else -1
            pixels += bytes(INK if (cell_row, cell_column) in ink else PAPER)
        rows.append(bytes(pixels))
    return rows


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(rows: list[bytes]) -> bytes:
    """An 8-bit RGB PNG of the rows (filter type 0 on every row)."""
    header = struct.pack(">IIBBBBB", len(rows[0]) // 3, len(rows), 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def decode_png(data: bytes) -> list[bytes]:
    """The RGB rows of a PNG written by png_bytes (8-bit RGB, no interlace, filter type 0)."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG file")
    position, header, idat = len(SIGNATURE), None, b""
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        (crc,) = struct.unpack(">I", data[position + 8 + length : position + 12 + length])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise ValueError(f"bad CRC in chunk {kind!r}")
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        position += 12 + length
    if header is None or header[2:] != (8, 2, 0, 0, 0):
        raise ValueError("not an 8-bit RGB PNG without interlace")
    width, height = header[:2]
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    if len(raw) != stride * height:
        raise ValueError("the image data does not match the header")
    rows = []
    for y in range(height):
        line = raw[y * stride : (y + 1) * stride]
        if line[0] != 0:
            raise ValueError(f"row {y} uses PNG filter {line[0]}, not 0")
        rows.append(line[1:])
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="compare the committed images instead of writing")
    args = parser.parse_args(argv)
    status = 0
    for name, text in IMAGES.items():
        path = HERE / name
        rows = render(text)
        if args.check:
            try:
                same = decode_png(path.read_bytes()) == rows
            except (OSError, ValueError) as error:
                print(f"{name}: {error}", file=sys.stderr)
                same = False
            print(f"{'ok' if same else 'DIFFERS'} {name}")
            status |= 0 if same else 1
        else:
            path.write_bytes(png_bytes(rows))
            print(f"wrote {name} ({path.stat().st_size} bytes, {WIDTH}x{HEIGHT}, {text!r})")
    return status


if __name__ == "__main__":
    sys.exit(main())
