from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TEST_INPUT_DIRECTORY = [""]

folder_paths_stub = sys.modules.get("folder_paths") or types.ModuleType("folder_paths")
folder_paths_stub.get_input_directory = lambda: TEST_INPUT_DIRECTORY[0]
sys.modules["folder_paths"] = folder_paths_stub

server_stub = types.ModuleType("server")
server_stub.PromptServer = type("PromptServer", (), {"instance": None})
sys.modules["server"] = server_stub

PACKAGE_NAME = "advanced_image_loader_server_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PLUGIN_ROOT)]
sys.modules[PACKAGE_NAME] = package

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.server_routes", PLUGIN_ROOT / "server_routes.py"
)
server_routes = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server_routes
assert spec.loader is not None
spec.loader.exec_module(server_routes)


class ImportToInputTests(unittest.TestCase):
    def test_reuses_an_image_that_is_already_in_input(self):
        with tempfile.TemporaryDirectory() as directory:
            input_directory = Path(directory) / "input"
            image_path = input_directory / "references" / "sample.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (4, 4), "red").save(image_path)
            TEST_INPUT_DIRECTORY[0] = str(input_directory)

            result = server_routes._import_to_input(str(image_path))

            self.assertEqual(result["image"], "references/sample.png")
            self.assertEqual(result["subfolder"], "references")
            self.assertEqual(len(list(input_directory.rglob("*.png"))), 1)

    def test_copies_only_the_selected_external_image_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_directory = root / "input"
            external_directory = root / "external"
            input_directory.mkdir()
            external_directory.mkdir()
            selected = external_directory / "selected.png"
            untouched = external_directory / "untouched.png"
            Image.new("RGB", (4, 4), "green").save(selected)
            Image.new("RGB", (4, 4), "blue").save(untouched)
            TEST_INPUT_DIRECTORY[0] = str(input_directory)

            first = server_routes._import_to_input(str(selected))
            second = server_routes._import_to_input(str(selected))

            copied = list((input_directory / "advanced-image-loader").glob("*.png"))
            self.assertEqual(first, second)
            self.assertEqual(len(copied), 1)
            self.assertTrue(copied[0].name.startswith("selected-"))


if __name__ == "__main__":
    unittest.main()
