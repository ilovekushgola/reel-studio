"""
make_icon.py - generates icon.ico (256x256 PNG-in-ICO) with stdlib only.

Design: graphite rounded tile, amber signal ring (a reel), amber centre pin.
Pure zlib + struct, no Pillow.
"""
import math
import os
import struct
import zlib

SIZE = 256
BG = (20, 22, 26, 255)        # graphite tile
RING = (240, 164, 55, 255)    # signal amber
PIN = (240, 164, 55, 255)
SS = 3                         # supersampling factor


def _rounded_rect_cover(x, y, w, h, r):
    """coverage 0..1 of a rounded rect centred in the tile"""
    cx, cy = x - w / 2.0, y - h / 2.0
    dx, dy = abs(cx) - (w / 2.0 - r), abs(cy) - (h / 2.0 - r)
    dx, dy = max(dx, 0.0), max(dy, 0.0)
    d = math.hypot(dx, dy) - r
    return min(1.0, max(0.0, 0.5 - d))


def render():
    w = h = SIZE
    px = bytearray(w * h * 4)
    pad = 10
    tw, th = w - 2 * pad, h - 2 * pad
    r_out = 52
    cxc = cyc = SIZE / 2.0
    ring_r = 78.0
    ring_t = 20.0
    for y in range(h):
        for x in range(w):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    fx = x + (sx + 0.5) / SS
                    fy = y + (sy + 0.5) / SS
                    tile = _rounded_rect_cover(fx - pad, fy - pad, tw, th, r_out)
                    col = (0.0, 0.0, 0.0, 0.0)
                    if tile > 0:
                        col = (BG[0], BG[1], BG[2], 255 * tile)
                    d = math.hypot(fx - cxc, fy - cyc)
                    # ring
                    if abs(d - ring_r) <= ring_t / 2.0:
                        # a gap at the lower right, like a reel/film opening
                        ang = math.degrees(math.atan2(fy - cyc, fx - cxc)) % 360
                        if not (ang > 340 or ang < 20 or 300 < ang < 305):
                            col = (RING[0], RING[1], RING[2], 255)
                    # centre pin
                    if d <= 22.0:
                        col = (PIN[0], PIN[1], PIN[2], 255)
                    acc[0] += col[0] * col[3] / 255.0
                    acc[1] += col[1] * col[3] / 255.0
                    acc[2] += col[2] * col[3] / 255.0
                    acc[3] += col[3]
            n = SS * SS
            a = acc[3] / n
            if a > 0:
                rr = acc[0] / (acc[3] / 255.0) if acc[3] else 0
                gg = acc[1] / (acc[3] / 255.0) if acc[3] else 0
                bb = acc[2] / (acc[3] / 255.0) if acc[3] else 0
            else:
                rr = gg = bb = 0
            i = (y * w + x) * 4
            px[i], px[i + 1], px[i + 2], px[i + 3] = int(rr), int(gg), int(bb), int(a)
    return bytes(px)


def png_bytes(w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def write_ico(path):
    png = png_bytes(SIZE, SIZE, render())
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    with open(path, "wb") as f:
        f.write(header + entry + png)
    return path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    p = write_ico(os.path.join(here, "icon.ico"))
    print("wrote", p, os.path.getsize(p), "bytes")
