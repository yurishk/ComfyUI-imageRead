from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


PLUGIN_ROOT = Path(__file__).resolve().parents[1]

folder_paths_stub = types.ModuleType("folder_paths")
folder_paths_stub.exists_annotated_filepath = lambda _value: False
folder_paths_stub.get_annotated_filepath = lambda value: value
sys.modules["folder_paths"] = folder_paths_stub

node_helpers_stub = types.ModuleType("node_helpers")
node_helpers_stub.pillow = lambda function, *args, **kwargs: function(*args, **kwargs)
sys.modules["node_helpers"] = node_helpers_stub

PACKAGE_NAME = "advanced_image_loader_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PLUGIN_ROOT)]
sys.modules[PACKAGE_NAME] = package

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.nodes", PLUGIN_ROOT / "nodes.py"
)
nodes = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = nodes
assert spec.loader is not None
spec.loader.exec_module(nodes)


class ImageLoaderTests(unittest.TestCase):
    def test_alpha_channel_becomes_inverted_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alpha.png"
            rgba = np.array(
                [
                    [[255, 0, 0, 255], [0, 255, 0, 0]],
                    [[0, 0, 255, 128], [255, 255, 255, 64]],
                ],
                dtype=np.uint8,
            )
            Image.fromarray(rgba, "RGBA").save(path)

            image, mask = nodes._load_image_and_mask(str(path))

            self.assertEqual(tuple(image.shape), (1, 2, 2, 3))
            self.assertEqual(tuple(mask.shape), (1, 2, 2))
            self.assertAlmostEqual(float(mask[0, 0, 0]), 0.0, places=5)
            self.assertAlmostEqual(float(mask[0, 0, 1]), 1.0, places=5)
            self.assertAlmostEqual(float(mask[0, 1, 0]), 1.0 - 128 / 255, places=5)

    def test_folder_mode_resolves_selected_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected.png"
            Image.new("RGB", (4, 4), "white").save(path)
            selected = nodes._resolve_selected_path(
                "", "folder", directory, str(path), "{}"
            )
            self.assertEqual(selected, str(path))


if __name__ == "__main__":
    unittest.main()
