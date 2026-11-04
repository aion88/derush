#!/usr/bin/env python3
"""Regenerates app/icon.icns (stdlib + sips + iconutil, no new dependency).
Glyph: a rounded dark square, a play triangle cut by a vertical gap (a jump cut).
Usage: <venv python> app/make-icon.py   (writes app/icon.icns next to this file)"""
import os, struct, subprocess, sys, tempfile, zlib

N = 1024
BG0, BG1, FG, ACC = (24, 28, 40), (52, 60, 86), (245, 240, 230), (255, 107, 74)


def inside_round_rect(x, y, m, r):
    cx = min(max(x, m + r), N - m - r)
    cy = min(max(y, m + r), N - m - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def in_triangle(x, y):
    # play triangle, apex on the right
    x0, x1, yc, h = 330, 760, 512, 230
    if not (x0 <= x <= x1):
        return False
    return abs(y - yc) <= h * (x1 - x) / (x1 - x0)


def pixel(x, y):
    if not inside_round_rect(x, y, 56, 210):
        return (0, 0, 0, 0)
    t = y / N
    bg = tuple(int(BG0[i] + (BG1[i] - BG0[i]) * t) for i in range(3))
    if in_triangle(x, y):
        return (*(ACC if 505 <= x <= 545 else FG), 255)  # accent gap = the cut
    return (*bg, 255)


def png(path):
    rows = []
    for y in range(N):
        row = bytearray([0])
        for x in range(N):
            # 2x2 supersampling for smooth edges
            acc = [0, 0, 0, 0]
            for dy in (0.25, 0.75):
                for dx in (0.25, 0.75):
                    p = pixel(x + dx, y + dy)
                    for i in range(3):
                        acc[i] += p[i] * p[3]
                    acc[3] += p[3]
            a = acc[3]
            row += bytes([acc[i] // a if a else 0 for i in range(3)] + [a // 4])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


here = os.path.dirname(os.path.abspath(__file__))
with tempfile.TemporaryDirectory() as t:
    base = os.path.join(t, "base.png")
    png(base)
    iset = os.path.join(t, "icon.iconset")
    os.mkdir(iset)
    for s in (16, 32, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = s * scale
            subprocess.run(["sips", "-z", str(px), str(px), base, "--out",
                            os.path.join(iset, f"icon_{s}x{s}{suffix}.png")],
                           check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["iconutil", "-c", "icns", iset, "-o", os.path.join(here, "icon.icns")], check=True)
print("wrote", os.path.join(here, "icon.icns"))
