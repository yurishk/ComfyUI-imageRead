from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path

from aiohttp import web

import folder_paths
from server import PromptServer

from .folder_browser import DirectoryIndexCache, ThumbnailCache, resolve_image_path


ROUTE_PREFIX = "/advanced-image-loader"
DIRECTORY_CACHE = DirectoryIndexCache()
THUMBNAIL_CACHE = ThumbnailCache()


def _pick_folder(initial_path: str = "") -> str:
    initial_path = initial_path if os.path.isdir(initial_path) else str(Path.home())
    system = platform.system()

    if system == "Windows":
        script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select an image folder'
$dialog.ShowNewFolderButton = $false
if (Test-Path -LiteralPath $env:AIL_INITIAL_DIR) {
    $dialog.SelectedPath = $env:AIL_INITIAL_DIR
}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $dialog.SelectedPath
}
"""
        env = os.environ.copy()
        env["AIL_INITIAL_DIR"] = initial_path
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creation_flags,
            timeout=300,
            check=False,
        )
    elif system == "Darwin":
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Select an image folder")',
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    else:
        picker = shutil.which("zenity") or shutil.which("kdialog")
        if not picker:
            raise RuntimeError("No native folder picker is available. Enter the path manually.")
        args = [picker, "--file-selection", "--directory", f"--filename={initial_path}/"]
        if Path(picker).name == "kdialog":
            args = [picker, "--getexistingdirectory", initial_path]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    if result.returncode != 0:
        return ""
    selected = result.stdout.strip()
    return os.path.abspath(selected) if selected else ""


def _import_to_input(source_path: str) -> dict[str, str]:
    source = resolve_image_path(source_path)
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
    routes = PromptServer.instance.routes

    @routes.post(f"{ROUTE_PREFIX}/folder/list")
    async def list_folder(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            result = await asyncio.to_thread(
                DIRECTORY_CACHE.list_page,
                payload.get("path", ""),
                payload.get("page", 0),
                payload.get("page_size", 48),
                payload.get("query", ""),
                bool(payload.get("refresh", False)),
            )
            return web.json_response(result)
        except (OSError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)

    @routes.get(f"{ROUTE_PREFIX}/folder/preview")
    async def preview_folder_image(request: web.Request) -> web.Response:
        try:
            data, content_type, etag = await asyncio.to_thread(
                THUMBNAIL_CACHE.get,
                request.query.get("path", ""),
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
        except (OSError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=404)

    @routes.post(f"{ROUTE_PREFIX}/folder/pick")
    async def pick_folder(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            selected = await asyncio.to_thread(
                _pick_folder, str(payload.get("initial_path", ""))
            )
            return web.json_response({"path": selected})
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            return web.json_response({"error": str(error)}, status=500)

    @routes.post(f"{ROUTE_PREFIX}/folder/import")
    async def import_folder_image(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            result = await asyncio.to_thread(
                _import_to_input, str(payload.get("path", ""))
            )
            return web.json_response(result)
        except (OSError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)
