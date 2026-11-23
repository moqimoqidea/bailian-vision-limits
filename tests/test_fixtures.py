import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402
import io  # noqa: E402

from limits.fixtures import (  # noqa: E402
    chinese_text,
    english_text,
    image_bytes,
    noise_png_of_size,
    png_of_size,
)

MAGIC = {
    "PNG": b"\x89PNG\r\n\x1a\n",
    "JPEG": b"\xff\xd8",
    "BMP": b"BM",
    "WEBP": b"RIFF",
}


class FixtureSizeTests(unittest.TestCase):
    def test_png_size_is_exact(self):
        for target in (600, 1024 * 1024, 5 * 1024 * 1024):
            data = png_of_size(target)
            self.assertEqual(len(data), target)

    def test_png_stays_small_bitmap(self):
        data = png_of_size(3 * 1024 * 1024)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (64, 64))

    def test_png_rejects_impossible_target(self):
        with self.assertRaises(ValueError):
            png_of_size(16)


class NoiseFixtureTests(unittest.TestCase):
    def test_noise_size_is_exact(self):
        data = noise_png_of_size(2 * 1024 * 1024)
        self.assertEqual(len(data), 2 * 1024 * 1024)

    def test_noise_is_real_bitmap(self):
        data = noise_png_of_size(1024 * 1024)
        with Image.open(io.BytesIO(data)) as image:
            self.assertGreater(image.size[0], 100)
            self.assertGreater(image.size[1], 100)

    def test_noise_is_incompressible(self):
        target = 1024 * 1024
        data = noise_png_of_size(target)
        with Image.open(io.BytesIO(data)) as image:
            raw_pixels = image.size[0] * image.size[1] * 3
        # 像素数据应占文件体积的绝大部分，而不是靠元数据凑数
        self.assertGreater(raw_pixels, target * 0.9)


class FixtureFormatTests(unittest.TestCase):
    def test_magic_bytes(self):
        for fmt, magic in MAGIC.items():
            self.assertTrue(
                image_bytes(fmt, 64, 64).startswith(magic), f"{fmt} magic mismatch"
            )

    def test_tiff_is_decodable(self):
        with Image.open(io.BytesIO(image_bytes("TIFF", 64, 64))) as image:
            self.assertEqual(image.size, (64, 64))

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            image_bytes("HEIC", 64, 64)


class FixtureTextTests(unittest.TestCase):
    def test_english_length_within_target(self):
        text = english_text(4096)
        self.assertLessEqual(len(text.encode("utf-8")), 4096)

    def test_english_can_embed_needle(self):
        self.assertIn("BLUE-OTTER-7742", english_text(2048, needle=True))

    def test_chinese_is_valid_utf8_and_sized(self):
        text = chinese_text(8192)
        encoded = text.encode("utf-8")
        self.assertLessEqual(len(encoded), 8192)
        self.assertNotIn("\ufffd", text)


if __name__ == "__main__":
    unittest.main()
