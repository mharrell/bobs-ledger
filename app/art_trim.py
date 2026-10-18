#!/usr/bin/env python3
"""Trim the white padding baked into card portraits, and nothing else.

WHY THIS EXISTS. The 256x256 portraits served by art.hearthstonejson.com are a
square canvas with the artwork letterboxed onto white (the client-extracted art
`hearth_art_extract.py` writes is the same square kind). The card frame is
88:116 with `object-fit:cover` (`coach_ui` `.tavern .tile .thumb`), which crops
the BOX, not the picture: a square source in a portrait frame is scaled to the
frame height and cropped left/right, so a top/bottom white band always survives,
and a side band wider than the ~31 source px the crop removes leaves a sliver.
Measured on the 915 cached 256x256 portraits (2026-10-18): 549 carry at least
one uniform white edge band, and 432 still show white inside the 88:116 frame.

THE FIX. Decode the PNG, find contiguous edge rows/columns that are at least
98% near-white, crop them (plus a 2 px inset on the sides that had a band, to
remove the antialiased fringe), and re-encode the same colour type. The existing
`object-fit:cover` then fills the frame with art. Trimming removes canvas, not
artwork.

STDLIB ONLY, ON PURPOSE. The overlay's runtime dependency is requests; adding
Pillow for one crop is not worth it. The art CDN and the client extractor write
8-bit RGB/RGBA, non-interlaced PNGs (measured: 809 RGBA + 165 RGB of the 974
cache files), which is all this decoder accepts. Anything else is returned
unchanged, never raised: art is optional, and a decoder edge case must not take
the overlay down.

Usage:
  python art_trim.py               # trim img_cache/, print what changed
  python art_trim.py --dry-run     # report without writing
  python art_trim.py --dir PATH    # another cache root
"""
import argparse
import os
import struct
import sys
import tempfile
import zlib

#: A pixel counts as white when every colour channel is at least this. 244
#: tolerates the PNG encoder's rounding while still rejecting the pale blues
#: and creams that make up actual card art.
WHITE = 244

#: A row/column counts as a band when at least this share of it is white. 0.98
#: rather than 1.0 because the rounded corners leave a few non-white pixels at
#: the ends of an otherwise white row.
BAND = 0.98

#: Pixels cropped inside a detected band, to remove the antialiased fringe that
#: would otherwise read as a 1 px white border. Applied only on sides with a
#: band, so an image that is already edge-to-edge is not cropped for nothing.
INSET = 2

#: Never crop more than this share of a dimension. The worst real band measured
#: is 39/256 (15%); a bigger "band" is a mostly-white picture, not padding.
MAX_BAND = 0.25


def _chunks(data):
    """Yield (type, payload) for a PNG's chunks, or raise ValueError."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("truncated chunk")
        yield kind, data[pos + 8:pos + 8 + length]
        pos = end


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw, width, height, bpp):
    """Undo PNG scanline filters. `raw` includes the per-row filter byte."""
    stride = width * bpp
    if len(raw) != height * (stride + 1):
        raise ValueError("unexpected decompressed size")
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if kind == 0:                       # None
            pass
        elif kind == 1:                     # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif kind == 2:                     # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif kind == 3:                     # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif kind == 4:                     # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        else:
            raise ValueError("unknown filter")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def _chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def _encode(width, height, color_type, rows):
    """Encode 8-bit RGB/RGBA rows as a PNG.

    Paeth filters every row. Filter 0 (none) was tried first and made the
    re-encoded files ~40% BIGGER than the sources (a photo compresses badly
    unfiltered); Paeth lands within a few percent of the originals. There are
    no ancillary chunks to preserve: the art CDN writes only IHDR/IDAT/IEND.
    """
    bpp = {2: 3, 6: 4}[color_type]
    stride = width * bpp
    raw = bytearray()
    prev = bytearray(stride)
    for row in rows:
        line = bytes(row)
        filtered = bytearray(stride)
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            filtered[i] = (line[i] - _paeth(a, b, c)) & 0xFF
        raw.append(4)
        raw += filtered
        prev = line
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _chunk(b"IEND", b""))


def _white_counts(pixels, width, height, bpp):
    """(per-row, per-column) counts of near-white pixels."""
    alpha = bpp == 4
    rows = [0] * height
    cols = [0] * width
    for y in range(height):
        base = y * width * bpp
        for x in range(width):
            o = base + x * bpp
            if (pixels[o] >= WHITE and pixels[o + 1] >= WHITE
                    and pixels[o + 2] >= WHITE
                    and (not alpha or pixels[o + 3] >= 250)):
                rows[y] += 1
                cols[x] += 1
    return rows, cols


def _edge(counts, limit, need):
    n = 0
    while n < limit and counts[n] >= need:
        n += 1
    return n


def trim_png_bytes(data):
    """`data` with uniform white edge bands cropped, or `data` unchanged.

    Only 8-bit, non-interlaced RGB/RGBA PNGs are considered; every other shape
    (and any decoding error) is returned byte-for-byte. The caller can compare
    identity to know whether anything changed.
    """
    try:
        header = None
        idat = []
        for kind, payload in _chunks(data):
            if kind == b"IHDR":
                header = payload
            elif kind == b"IDAT":
                idat.append(payload)
            elif kind == b"IEND":
                break
        if header is None or not idat or len(header) != 13:
            return data
        width, height, depth, color_type, _comp, _filt, interlace = (
            struct.unpack(">IIBBBBB", header))
        bpp = {2: 3, 6: 4}.get(color_type)
        if depth != 8 or bpp is None or interlace != 0:
            return data
        if not width or not height or width > 4096 or height > 4096:
            return data
        expected = height * (width * bpp + 1)
        if expected > 64 * 1024 * 1024:
            return data
        # decompress with a ceiling: a malformed header must not turn a cache
        # read into a zip bomb. `unconsumed_tail` means the IDAT held MORE
        # than the header promised, which is not a shape this decoder trusts.
        inflater = zlib.decompressobj()
        raw = inflater.decompress(b"".join(idat), expected)
        if inflater.unconsumed_tail or len(raw) != expected:
            return data
        pixels = _unfilter(raw, width, height, bpp)
    except (ValueError, zlib.error, struct.error):
        return data

    rows, cols = _white_counts(pixels, width, height, bpp)
    limit_h = max(1, int(height * MAX_BAND))
    limit_w = max(1, int(width * MAX_BAND))
    top = _edge(rows, limit_h, BAND * width)
    bottom = _edge(rows[::-1], limit_h, BAND * width)
    left = _edge(cols, limit_w, BAND * height)
    right = _edge(cols[::-1], limit_w, BAND * height)
    if not (top or bottom or left or right):
        return data

    x0 = left + (INSET if left else 0)
    y0 = top + (INSET if top else 0)
    x1 = width - right - (INSET if right else 0)
    y1 = height - bottom - (INSET if bottom else 0)
    # A band that would leave less than half the picture is not padding.
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
        return data
    if x1 - x0 < width // 2 or y1 - y0 < height // 2:
        return data

    stride = width * bpp
    cropped = [pixels[y * stride + x0 * bpp:
                      y * stride + x1 * bpp]
               for y in range(y0, y1)]
    try:
        return _encode(x1 - x0, y1 - y0, color_type, cropped)
    except (ValueError, zlib.error):
        return data


def trim_file(path, dry_run=False):
    """Trim one cache file in place. True when it changed (or would change)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    out = trim_png_bytes(data)
    if out is data or out == data:
        return False
    if dry_run:
        return True
    directory = os.path.dirname(path) or "."
    tmp = None
    try:
        mode = os.stat(path).st_mode
        fd, tmp = tempfile.mkstemp(prefix=".trim-", suffix=".png",
                                   dir=directory)
        with os.fdopen(fd, "wb") as f:
            f.write(out)
        os.chmod(tmp, mode)         # mkstemp is 0600; keep the cache's mode
        os.replace(tmp, path)       # atomic: /img may be reading the old file
    except OSError:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False
    return True


def trim_cache(root, dry_run=False, progress=None):
    """Trim every `*.png` directly under `root` (NOT the card/ renders)."""
    changed = 0
    seen = 0
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return 0
    for name in names:
        if not name.lower().endswith(".png"):
            continue
        seen += 1
        if trim_file(os.path.join(root, name), dry_run=dry_run):
            changed += 1
        if progress:
            progress(seen, changed, name)
    return changed


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=os.path.join(here, "img_cache"),
                    help="cache root (default: img_cache/ beside this file)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report how many would change, write nothing")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.dir):
        print(f"no such cache directory: {args.dir}")
        return 2

    def progress(seen, changed, name):
        if seen % 100 == 0:
            print(f"  {seen} checked, {changed} trimmed", flush=True)

    changed = trim_cache(args.dir, dry_run=args.dry_run, progress=progress)
    verb = "would trim" if args.dry_run else "trimmed"
    print(f"{verb} {changed} portrait(s) in {args.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
