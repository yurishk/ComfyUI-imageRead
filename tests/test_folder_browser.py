from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from folder_browser import DirectoryIndexCache, ThumbnailCache, resolve_image_path


class DirectoryIndexCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        for name in ("image10.png", "image2.png", "image1.png"):
            Image.new("RGB", (8, 8), "red").save(self.root / name)
        (self.root / "notes.txt").write_text("not an image", encoding="utf-8")
        self.cache = DirectoryIndexCache(ttl_seconds=600)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_natural_sort_and_pagination(self):
        first = self.cache.list_page(str(self.root), page=0, page_size=2)
        second = self.cache.list_page(str(self.root), page=1, page_size=2)

        self.assertEqual([item["name"] for item in first["items"]], ["image1.png", "image2.png"])
        self.assertEqual([item["name"] for item in second["items"]], ["image10.png"])
        self.assertEqual(first["total"], 3)
        self.assertEqual(first["page_count"], 2)

    def test_search_uses_cached_index(self):
        self.cache.list_page(str(self.root))
        Image.new("RGB", (8, 8), "blue").save(self.root / "new.png")
        cached = self.cache.list_page(str(self.root), query="new")
        refreshed = self.cache.list_page(str(self.root), query="new", refresh=True)

        self.assertEqual(cached["total"], 0)
        self.assertEqual(refreshed["total"], 1)

    def test_rejects_path_outside_selected_folder(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "outside.png"
            Image.new("RGB", (8, 8), "green").save(outside)
            with self.assertRaisesRegex(ValueError, "outside"):
                resolve_image_path(str(outside), str(self.root))


class ThumbnailCacheTests(unittest.TestCase):
    def test_thumbnail_preserves_alpha_and_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "alpha.png"
            Image.new("RGBA", (512, 256), (255, 0, 0, 128)).save(image_path)
            cache = ThumbnailCache(max_bytes=1024 * 1024)

            first = cache.get(str(image_path), 128)
            second = cache.get(str(image_path), 128)

            self.assertEqual(first[1], "image/png")
            self.assertEqual(first[0], second[0])
            self.assertEqual(first[2], second[2])
            self.assertGreater(len(first[0]), 0)


if __name__ == "__main__":
    unittest.main()
