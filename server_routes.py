from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import shutil
import threading
from pathlib import Path

from aiohttp import web

import folder_paths
from server import PromptServer

try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    tk = None
    filedialog = None

TK_ERRORS = (tk.TclError,) if tk is not None else ()

from .folder_access import FOLDER_GRANTS, FolderAccessDenied, FolderGrantStore
from .folder_browser import (
    DirectoryIndexCache,
    ThumbnailCache,
    normalize_folder,
    resolve_image_path,
)


ROUTE_PREFIX = "/advanced-image-loader"
DIRECTORY_CACHE = DirectoryIndexCache()
THUMBNAIL_CACHE = ThumbnailCache()
PICKER_LOCK = threading.Lock()


def _require_local_request(request: web.Request) -> None:
    transport = request.transport
    peer = transport.get_extra_info("peername") if transport else None
    host = peer[0] if isinstance(peer, (tuple, list)) and peer else ""
    try:
        address = ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError as error:
        raise FolderAccessDenied(
            "External folder access is available only from this computer."
        ) from error
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_loopback:
        raise FolderAccessDenied(
            "External folder access is available only from this computer."
        )


def _pick_folder(initial_path: str = "") -> str:
    initial_path = initial_path if os.path.isdir(initial_path) else str(Path.home())
    if not PICKER_LOCK.acquire(blocking=False):
        raise RuntimeError("A folder picker is already open.")

    root = None
    try:
        if tk is None or filedialog is None:
            raise RuntimeError(
                "The Python Tk folder picker is unavailable on this installation."
            )

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        selected = filedialog.askdirectory(
            parent=root,
            title="Select an image folder",
            initialdir=initial_path,
            mustexist=True,
        )
        return normalize_folder(selected) if selected else ""
    except TK_ERRORS as error:
        raise RuntimeError(f"Unable to open the folder picker: {error}") from error
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        PICKER_LOCK.release()


def _import_to_input(source_path: str, root: str) -> dict[str, str]:
    source = resolve_image_path(source_path, root)
    input_directory = os.path.abspath(folder_paths.get_input_directory())
    try:
        common = os.path.commonpath(
            [os.path.normcase(input_directory), os.path.normcase(source)]
        )
    except ValueError:
        common = ""

    if common == os.path.normcase(input_directory):
        relative_path = Path(os.path.relpath(source, input_directory)).as_posix()
        relative_folder = Path(relative_path).parent.as_posix()
        return {
            "image": relative_path,
            "name": Path(relative_path).name,
            "subfolder": "" if relative_folder == "." else relative_folder,
            "type": "input",
        }

    stat = os.stat(source)
    digest = hashlib.sha256(
        f"{os.path.normcase(source)}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
    ).hexdigest()[:12]
    source_name = Path(source).name
    destination_name = f"{Path(source_name).stem}-{digest}{Path(source_name).suffix.lower()}"
    subfolder = "advanced-image-loader"
    destination_dir = os.path.join(input_directory, subfolder)
    os.makedirs(destination_dir, exist_ok=True)
    destination = os.path.join(destination_dir, destination_name)
    if not os.path.isfile(destination):
        shutil.copy2(source, destination)

    return {
        "image": f"{subfolder}/{destination_name}",
        "name": destination_name,
        "subfolder": subfolder,
        "type": "input",
    }


def register_routes() -> None:
    FOLDER_GRANTS.configure_storage(
        Path(folder_paths.get_user_directory())
        / "advanced-image-loader"
        / "folder-grants.json"
    )
    routes = PromptServer.instance.routes

    @routes.post(f"{ROUTE_PREFIX}/folder/list")
    async def list_folder(request: web.Request) -> web.Response:
        try:
            _require_local_request(request)
            payload = await request.json()
            grant = str(payload.get("grant", ""))
            root, folder = FOLDER_GRANTS.resolve_folder(
                grant, str(payload.get("path", ""))
            )
            result = await asyncio.to_thread(
                DIRECTORY_CACHE.list_page,
                folder,
                payload.get("page", 0),
                payload.get("page_size", 48),
                payload.get("query", ""),
                bool(payload.get("recursive", False)),
                payload.get("max_depth", 8),
                payload.get("sort_by", "name_asc"),
                bool(payload.get("refresh", False)),
                root,
            )
            for item in result["items"]:
                item["file_id"] = FOLDER_GRANTS.issue_file(grant, item["path"])
            selected_path = str(payload.get("selected_path", ""))
            if selected_path:
                result["selected_file_id"] = FOLDER_GRANTS.issue_file(
                    grant, selected_path
                )
            return web.json_response(result)
        except FolderAccessDenied as error:
            return web.json_response({"error": str(error)}, status=403)
        except (OSError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)

    @routes.get(f"{ROUTE_PREFIX}/folder/preview")
    async def preview_folder_image(request: web.Request) -> web.Response:
        try:
            _require_local_request(request)
            path, root = FOLDER_GRANTS.resolve_file(
                request.query.get("id", "")
            )
            data, content_type, etag = await asyncio.to_thread(
                THUMBNAIL_CACHE.get,
                path,
                root,
                request.query.get("size", 256),
            )
            if request.headers.get("If-None-Match") == etag:
                return web.Response(status=304)
            return web.Response(
                body=data,
                content_type=content_type,
                headers={
                    "ETag": etag,
                    "Cache-Control": "private, max-age=3600",
                },
            )
        except FolderAccessDenied as error:
            return web.json_response({"error": str(error)}, status=403)
        except (OSError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=404)

    @routes.post(f"{ROUTE_PREFIX}/folder/pick")
    async def pick_folder(request: web.Request) -> web.Response:
        try:
            _require_local_request(request)
            payload = await request.json()
            selected = await asyncio.to_thread(
                _pick_folder, str(payload.get("initial_path", ""))
            )
            if not selected:
                return web.json_response({"path": "", "grant": ""})
            grant, selected = FOLDER_GRANTS.authorize(selected)
            return web.json_response({"path": selected, "grant": grant})
        except FolderAccessDenied as error:
            return web.json_response({"error": str(error)}, status=403)
        except (OSError, RuntimeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=500)

    @routes.post(f"{ROUTE_PREFIX}/folder/import")
    async def import_folder_image(request: web.Request) -> web.Response:
        try:
            _require_local_request(request)
            payload = await request.json()
            path, root = FOLDER_GRANTS.resolve_file(
                str(payload.get("file_id", ""))
            )
            result = await asyncio.to_thread(
                _import_to_input, path, root
            )
            return web.json_response(result)
        except FolderAccessDenied as error:
            return web.json_response({"error": str(error)}, status=403)
        except (OSError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)
