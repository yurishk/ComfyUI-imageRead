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

            result = server_routes._import_to_input(
                str(image_path), str(input_directory)
            )

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

            first = server_routes._import_to_input(
                str(selected), str(external_directory)
            )
            second = server_routes._import_to_input(
                str(selected), str(external_directory)
            )

            copied = list((input_directory / "advanced-image-loader").glob("*.png"))
            self.assertEqual(first, second)
            self.assertEqual(len(copied), 1)
            self.assertTrue(copied[0].name.startswith("selected-"))


class FolderGrantStoreTests(unittest.TestCase):
    def test_grant_confines_folder_and_image_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            child = root / "child"
            outside = Path(directory) / "outside"
            child.mkdir(parents=True)
            outside.mkdir()
            allowed_image = child / "allowed.png"
            outside_image = outside / "outside.png"
            Image.new("RGB", (4, 4), "green").save(allowed_image)
            Image.new("RGB", (4, 4), "red").save(outside_image)
            grants = server_routes.FolderGrantStore()

            grant, authorized_root = grants.authorize(str(root))
            resolved_root, resolved_child = grants.resolve_folder(grant, str(child))
            file_id = grants.issue_file(grant, str(allowed_image))
            resolved_image, image_root = grants.resolve_file(file_id)

            self.assertEqual(authorized_root, str(root.resolve()))
            self.assertEqual(resolved_root, authorized_root)
            self.assertEqual(resolved_child, str(child.resolve()))
            self.assertEqual(resolved_image, str(allowed_image.resolve()))
            self.assertEqual(image_root, authorized_root)
            with self.assertRaisesRegex(ValueError, "outside"):
                grants.resolve_folder(grant, str(outside))
            with self.assertRaisesRegex(ValueError, "outside"):
                grants.issue_file(grant, str(outside_image))

    def test_unknown_capabilities_are_rejected(self):
        grants = server_routes.FolderGrantStore()

        with self.assertRaises(server_routes.FolderAccessDenied):
            grants.root_for("not-a-grant")
        with self.assertRaises(server_routes.FolderAccessDenied):
            grants.resolve_file("not-a-file")

    def test_folder_grants_survive_a_store_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            storage = Path(directory) / "state" / "folder-grants.json"
            first_store = server_routes.FolderGrantStore(storage_path=storage)
            grant, authorized_root = first_store.authorize(str(root))
            duplicate_grant, _ = first_store.authorize(str(root))

            reloaded_store = server_routes.FolderGrantStore(storage_path=storage)

            self.assertEqual(duplicate_grant, grant)
            self.assertEqual(reloaded_store.root_for(grant), authorized_root)
            self.assertEqual(reloaded_store.resolve_folder(grant, str(root))[1], authorized_root)


class LocalRequestTests(unittest.TestCase):
    class Transport:
        def __init__(self, host):
            self.host = host

        def get_extra_info(self, name):
            return (self.host, 8188) if name == "peername" else None

    class Request:
        def __init__(self, host):
            self.transport = LocalRequestTests.Transport(host)

    def test_loopback_clients_are_allowed(self):
        server_routes._require_local_request(self.Request("127.0.0.1"))
        server_routes._require_local_request(self.Request("::1"))
        server_routes._require_local_request(self.Request("::ffff:127.0.0.1"))

    def test_network_clients_are_rejected(self):
        with self.assertRaises(server_routes.FolderAccessDenied):
            server_routes._require_local_request(self.Request("192.168.1.50"))


if __name__ == "__main__":
    unittest.main()
