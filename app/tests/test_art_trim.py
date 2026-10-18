"""The portrait white-band trim, decoded and re-encoded without Pillow.

The feature it protects: the 256x256 portraits are a square canvas with the art
letterboxed on white, and the 88:116 card frame's `object-fit:cover` crops the
box rather than the picture — so top/bottom white survives. `art_trim` crops the
bands (plus a 2px inset on each banded side) and re-encodes the same colour
type. These cases build their own PNGs so the test does not depend on the art
cache or the network.
"""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import art_trim  # noqa: E402


def _banded(size=64, band=8, color_type=6, sides=True):
    """A size x size portrait: `band` px of white on the requested edges."""
    bpp = {2: 3, 6: 4}[color_type]
    white = bytes((255, 255, 255, 255))[:bpp]
    art = bytes((10, 20, 30, 255))[:bpp]
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            edge = y < band or y >= size - band
            if sides:
                edge = edge or x < band or x >= size - band
            row += white if edge else art
        rows.append(row)
    return art_trim._encode(size, size, color_type, rows)


def _shape(png):
    return struct.unpack(">II", png[16:24])


class TestTrimPngBytes(unittest.TestCase):
    def test_a_white_band_is_cropped_from_every_side(self):
        out = art_trim.trim_png_bytes(_banded())
        self.assertEqual(_shape(out), (44, 44),
                         "8px bands + the 2px inset should leave 64-20")

    def test_only_banded_sides_get_the_inset(self):
        """A top/bottom-only portrait keeps its full width: the inset is there
        to remove the antialiased fringe of a band, not to shave clean art."""
        self.assertEqual(_shape(art_trim.trim_png_bytes(
            _banded(sides=False))), (64, 44))

    def test_rgb_and_rgba_both_decode(self):
        for color_type in (2, 6):
            with self.subTest(color_type=color_type):
                self.assertEqual(_shape(art_trim.trim_png_bytes(
                    _banded(color_type=color_type))), (44, 44))

    def test_an_image_with_no_band_is_returned_unchanged(self):
        png = _banded(band=0)
        self.assertIs(art_trim.trim_png_bytes(png), png,
                      "an already edge-to-edge portrait was re-encoded")

    def test_a_non_png_is_returned_unchanged(self):
        data = b"PNGDATA"
        self.assertIs(art_trim.trim_png_bytes(data), data)

    def test_trimming_twice_is_a_no_op(self):
        once = art_trim.trim_png_bytes(_banded())
        self.assertIs(art_trim.trim_png_bytes(once), once)


class TestTrimFile(unittest.TestCase):
    def test_it_rewrites_the_file_once(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "CARD.png")
            with open(path, "wb") as f:
                f.write(_banded())
            self.assertTrue(art_trim.trim_file(path))
            with open(path, "rb") as f:
                self.assertEqual(_shape(f.read()), (44, 44))
            self.assertFalse(art_trim.trim_file(path),
                             "a trimmed file was trimmed again")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "CARD.png")
            png = _banded()
            with open(path, "wb") as f:
                f.write(png)
            self.assertTrue(art_trim.trim_file(path, dry_run=True))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), png)


if __name__ == "__main__":
    unittest.main()
