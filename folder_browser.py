from __future__ import annotations

import hashlib
import io
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


IMAGE_EXTENSIONS = frozenset(
    {
        ".avif",
        ".bmp",
        ".gif",
        ".heic",
        ".heif",
        ".ico",
        ".jfif",
        ".jpeg",
        ".jpg",
        ".jxl",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)
DEFAULT_PAGE_SIZE = 48
MAX_PAGE_SIZE = 96
MAX_INDEX_ITEMS = 100_000


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


def normalize_folder(folder: str) -> str:
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("Folder path is empty.")

    path = os.path.abspath(os.path.expanduser(folder.strip()))
    if not os.path.isdir(path):
        raise ValueError(f"Folder does not exist: {path}")
    return path


def is_supported_image(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.casefold() in IMAGE_EXTENSIONS


def resolve_image_path(path: str, root: str | None = None) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Image path is empty.")

    resolved = os.path.abspath(os.path.expanduser(path.strip()))
    if root:
        resolved_root = normalize_folder(root)
        try:
            common = os.path.commonpath(
                [os.path.normcase(resolved_root), os.path.normcase(resolved)]
            )
        except ValueError as error:
            raise ValueError("The image is outside the selected folder.") from error
        if common != os.path.normcase(resolved_root):
            raise ValueError("The image is outside the selected folder.")

    if not os.path.isfile(resolved):
        raise ValueError(f"Image does not exist: {resolved}")
    if not is_supported_image(resolved):
        raise ValueError(f"Unsupported image type: {Path(resolved).suffix}")
    return resolved


@dataclass(frozen=True)
class DirectoryIndex:
    created_at: float
    items: tuple[str, ...]
    truncated: bool


class DirectoryIndexCache:
    """Caches filename-only directory scans so page changes never touch the disk."""

    def __init__(self, ttl_seconds: float = 120.0, max_directories: int = 12):
        self.ttl_seconds = ttl_seconds
        self.max_directories = max_directories
        self._entries: OrderedDict[str, DirectoryIndex] = OrderedDict()
        self._lock = threading.RLock()

    def clear(self, folder: str | None = None) -> None:
        with self._lock:
            if folder is None:
                self._entries.clear()
                return
            self._entries.pop(os.path.normcase(os.path.abspath(folder)), None)

    def _scan(self, folder: str) -> DirectoryIndex:
        names: list[str] = []
        truncated = False
        with os.scandir(folder) as entries:
            for entry in entries:
                if len(names) >= MAX_INDEX_ITEMS:
                    truncated = True
                    break
                if not is_supported_image(entry.name):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                names.append(entry.name)

        names.sort(key=_natural_key)
        return DirectoryIndex(time.monotonic(), tuple(names), truncated)

    def get_index(self, folder: str, refresh: bool = False) -> tuple[str, DirectoryIndex]:
        normalized = normalize_folder(folder)
        cache_key = os.path.normcase(normalized)
        now = time.monotonic()

        with self._lock:
            cached = self._entries.get(cache_key)
            if (
                not refresh
                and cached is not None
                and now - cached.created_at <= self.ttl_seconds
            ):
                self._entries.move_to_end(cache_key)
                return normalized, cached

        scanned = self._scan(normalized)
        with self._lock:
            self._entries[cache_key] = scanned
            self._entries.move_to_end(cache_key)
            while len(self._entries) > self.max_directories:
                self._entries.popitem(last=False)
        return normalized, scanned

    def list_page(
        self,
        folder: str,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str = "",
        refresh: bool = False,
    ) -> dict[str, object]:
        normalized, index = self.get_index(folder, refresh=refresh)
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        query_folded = str(query or "").strip().casefold()

        if query_folded:
            names = tuple(name for name in index.items if query_folded in name.casefold())
        else:
            names = index.items

        total = len(names)
        page_count = max(1, (total + page_size - 1) // page_size)
        page = max(0, min(int(page), page_count - 1))
        start = page * page_size
        selected_names = names[start : start + page_size]
        items = [
            {
                "name": name,
                "path": os.path.join(normalized, name),
                "relative_path": name,
            }
            for name in selected_names
        ]

        return {
            "folder": normalized,
            "items": items,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "total": total,
            "truncated": index.truncated,
            "cached": not refresh,
        }


class ThumbnailCache:
    def __init__(self, max_bytes: int = 96 * 1024 * 1024):
        self.max_bytes = max_bytes
        self._bytes = 0
        self._entries: OrderedDict[
            tuple[str, int, int, int], tuple[bytes, str, str]
        ] = OrderedDict()
        self._lock = threading.RLock()

    def _render(self, path: str, size: int) -> tuple[bytes, str]:
        with Image.open(path) as source:
            try:
                source.seek(0)
            except EOFError:
                pass
            image = ImageOps.exif_transpose(source)
            has_alpha = "A" in image.getbands() or (
                image.mode == "P" and "transparency" in image.info
            )
            image = image.convert("RGBA" if has_alpha else "RGB")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image.thumbnail((size, size), resampling)

            output = io.BytesIO()
            if has_alpha:
                image.save(output, format="PNG", compress_level=3)
                content_type = "image/png"
            else:
                image.save(output, format="JPEG", quality=85, optimize=False)
                content_type = "image/jpeg"
            return output.getvalue(), content_type

    def get(self, path: str, size: int = 256) -> tuple[bytes, str, str]:
        resolved = resolve_image_path(path)
        size = max(96, min(int(size), 1400))
        stat = os.stat(resolved)
        key = (os.path.normcase(resolved), size, stat.st_mtime_ns, stat.st_size)

        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached

        data, content_type = self._render(resolved, size)
        etag = hashlib.sha256(
            f"{key[0]}|{key[1]}|{key[2]}|{key[3]}".encode("utf-8")
        ).hexdigest()[:24]
        value = (data, content_type, etag)

        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            self._bytes += len(data)
            while self._bytes > self.max_bytes and self._entries:
                _, removed = self._entries.popitem(last=False)
                self._bytes -= len(removed[0])
        return value

