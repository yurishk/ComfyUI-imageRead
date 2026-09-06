from __future__ import annotations

import hashlib
import io
import os
import re
import threading
import time
from collections import OrderedDict, deque
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
MAX_SCANNED_DIRECTORIES = 5_000
MAX_CHILD_FOLDERS = 500
MAX_SCAN_SECONDS = 3.0
DEFAULT_RECURSIVE_DEPTH = 8
MAX_RECURSIVE_DEPTH = 32
SORT_OPTIONS = frozenset(
    {
        "name_asc",
        "name_desc",
        "path_asc",
        "path_desc",
        "modified_desc",
        "modified_asc",
        "size_desc",
        "size_asc",
        "type_asc",
    }
)


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
class ImageEntry:
    name: str
    relative_path: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class ChildFolder:
    name: str
    path: str


@dataclass(frozen=True)
class DirectoryIndex:
    created_at: float
    items: tuple[ImageEntry, ...]
    folders: tuple[ChildFolder, ...]
    folders_truncated: bool
    scanned_directories: int
    scan_seconds: float
    limit_reasons: tuple[str, ...]


class DirectoryIndexCache:
    """Caches bounded directory scans so paging and sorting stay memory-only."""

    def __init__(
        self,
        ttl_seconds: float = 120.0,
        max_directories: int = 12,
        max_items: int = MAX_INDEX_ITEMS,
        max_scanned_directories: int = MAX_SCANNED_DIRECTORIES,
        max_child_folders: int = MAX_CHILD_FOLDERS,
        max_scan_seconds: float = MAX_SCAN_SECONDS,
        max_views: int = 32,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_directories = max_directories
        self.max_items = max_items
        self.max_scanned_directories = max_scanned_directories
        self.max_child_folders = max_child_folders
        self.max_scan_seconds = max_scan_seconds
        self.max_views = max_views
        self._entries: OrderedDict[tuple[str, bool, int], DirectoryIndex] = (
            OrderedDict()
        )
        self._views: OrderedDict[
            tuple[str, bool, int, float, str, str], tuple[ImageEntry, ...]
        ] = OrderedDict()
        self._lock = threading.RLock()

    def clear(self, folder: str | None = None) -> None:
        with self._lock:
            if folder is None:
                self._entries.clear()
                self._views.clear()
                return
            normalized = os.path.normcase(os.path.abspath(folder))
            for key in tuple(self._entries):
                if key[0] == normalized:
                    self._entries.pop(key, None)
            for key in tuple(self._views):
                if key[0] == normalized:
                    self._views.pop(key, None)

    def _scan(self, folder: str, recursive: bool, max_depth: int) -> DirectoryIndex:
        started_at = time.monotonic()
        images: list[ImageEntry] = []
        child_folders: list[ChildFolder] = []
        folders_truncated = False
        scanned_directories = 0
        reasons: set[str] = set()
        pending: deque[tuple[str, str, int]] = deque([(folder, "", 0)])
        stop = False

        while pending and not stop:
            if time.monotonic() - started_at >= self.max_scan_seconds:
                reasons.add("time_limit")
                break
            if scanned_directories >= self.max_scanned_directories:
                reasons.add("directory_limit")
                break

            current, relative_folder, depth = pending.popleft()
            scanned_directories += 1
            try:
                entries = os.scandir(current)
            except OSError:
                if depth == 0:
                    raise
                reasons.add("unreadable_folders")
                continue

            with entries:
                for position, entry in enumerate(entries):
                    if position % 64 == 0 and time.monotonic() - started_at >= self.max_scan_seconds:
                        reasons.add("time_limit")
                        stop = True
                        break

                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth == 0:
                                if len(child_folders) < self.max_child_folders:
                                    child_folders.append(ChildFolder(entry.name, entry.path))
                                else:
                                    folders_truncated = True
                            if recursive:
                                if depth < max_depth:
                                    if len(pending) + scanned_directories < self.max_scanned_directories:
                                        child_relative = os.path.join(relative_folder, entry.name)
                                        pending.append((entry.path, child_relative, depth + 1))
                                    else:
                                        reasons.add("directory_limit")
                                else:
                                    reasons.add("depth_limit")
                            continue
                        if not is_supported_image(entry.name) or not entry.is_file(
                            follow_symlinks=False
                        ):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue

                    if len(images) >= self.max_items:
                        reasons.add("image_limit")
                        stop = True
                        break
                    images.append(
                        ImageEntry(
                            name=entry.name,
                            relative_path=os.path.join(relative_folder, entry.name),
                            size=stat.st_size,
                            modified_ns=stat.st_mtime_ns,
                        )
                    )

        child_folders.sort(key=lambda item: _natural_key(item.name))
        return DirectoryIndex(
            created_at=time.monotonic(),
            items=tuple(images),
            folders=tuple(child_folders),
            folders_truncated=folders_truncated,
            scanned_directories=scanned_directories,
            scan_seconds=round(time.monotonic() - started_at, 3),
            limit_reasons=tuple(sorted(reasons)),
        )

    def get_index(
        self,
        folder: str,
        recursive: bool = False,
        max_depth: int = DEFAULT_RECURSIVE_DEPTH,
        refresh: bool = False,
    ) -> tuple[str, DirectoryIndex, bool]:
        normalized = normalize_folder(folder)
        max_depth = max(1, min(int(max_depth), MAX_RECURSIVE_DEPTH))
        cache_key = (os.path.normcase(normalized), bool(recursive), max_depth)
        now = time.monotonic()

        with self._lock:
            cached = self._entries.get(cache_key)
            if (
                not refresh
                and cached is not None
                and now - cached.created_at <= self.ttl_seconds
            ):
                self._entries.move_to_end(cache_key)
                return normalized, cached, True

        scanned = self._scan(normalized, bool(recursive), max_depth)
        with self._lock:
            for view_key in tuple(self._views):
                if view_key[:3] == cache_key:
                    self._views.pop(view_key, None)
            self._entries[cache_key] = scanned
            self._entries.move_to_end(cache_key)
            while len(self._entries) > self.max_directories:
                self._entries.popitem(last=False)
        return normalized, scanned, False

    @staticmethod
    def _sort_items(items: tuple[ImageEntry, ...], sort_by: str) -> list[ImageEntry]:
        sort_by = sort_by if sort_by in SORT_OPTIONS else "name_asc"
        if sort_by == "name_desc":
            return sorted(items, key=lambda item: _natural_key(item.name), reverse=True)
        if sort_by == "path_asc":
            return sorted(items, key=lambda item: _natural_key(item.relative_path))
        if sort_by == "path_desc":
            return sorted(items, key=lambda item: _natural_key(item.relative_path), reverse=True)
        if sort_by == "modified_desc":
            return sorted(items, key=lambda item: (item.modified_ns, _natural_key(item.relative_path)), reverse=True)
        if sort_by == "modified_asc":
            return sorted(items, key=lambda item: (item.modified_ns, _natural_key(item.relative_path)))
        if sort_by == "size_desc":
            return sorted(items, key=lambda item: (item.size, _natural_key(item.relative_path)), reverse=True)
        if sort_by == "size_asc":
            return sorted(items, key=lambda item: (item.size, _natural_key(item.relative_path)))
        if sort_by == "type_asc":
            return sorted(
                items,
                key=lambda item: (Path(item.name).suffix.casefold(), _natural_key(item.relative_path)),
            )
        return sorted(items, key=lambda item: _natural_key(item.name))

    def list_page(
        self,
        folder: str,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str = "",
        recursive: bool = False,
        max_depth: int = DEFAULT_RECURSIVE_DEPTH,
        sort_by: str = "name_asc",
        refresh: bool = False,
    ) -> dict[str, object]:
        normalized, index, cached = self.get_index(
            folder,
            recursive=recursive,
            max_depth=max_depth,
            refresh=refresh,
        )
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        query_folded = str(query or "").strip().casefold()
        sort_by = sort_by if sort_by in SORT_OPTIONS else "name_asc"

        max_depth = max(1, min(int(max_depth), MAX_RECURSIVE_DEPTH))
        view_key = (
            os.path.normcase(normalized),
            bool(recursive),
            max_depth,
            index.created_at,
            query_folded,
            sort_by,
        )
        with self._lock:
            sorted_entries = self._views.get(view_key)
            if sorted_entries is not None:
                self._views.move_to_end(view_key)

        if sorted_entries is None:
            if query_folded:
                entries = tuple(
                    item
                    for item in index.items
                    if query_folded in item.relative_path.casefold()
                )
            else:
                entries = index.items
            sorted_entries = tuple(self._sort_items(entries, sort_by))
            with self._lock:
                self._views[view_key] = sorted_entries
                self._views.move_to_end(view_key)
                while len(self._views) > self.max_views:
                    self._views.popitem(last=False)

        total = len(sorted_entries)
        page_count = max(1, (total + page_size - 1) // page_size)
        page = max(0, min(int(page), page_count - 1))
        start = page * page_size
        selected_entries = sorted_entries[start : start + page_size]
        items = [
            {
                "name": item.name,
                "path": os.path.join(normalized, item.relative_path),
                "relative_path": item.relative_path,
                "size": item.size,
                "modified": item.modified_ns // 1_000_000,
            }
            for item in selected_entries
        ]

        return {
            "folder": normalized,
            "parent_folder": os.path.dirname(normalized),
            "folders": [
                {"name": item.name, "path": item.path} for item in index.folders
            ],
            "folders_truncated": index.folders_truncated,
            "items": items,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "total": total,
            "recursive": bool(recursive),
            "max_depth": max_depth,
            "sort_by": sort_by,
            "truncated": bool(index.limit_reasons),
            "limit_reasons": list(index.limit_reasons),
            "scanned_directories": index.scanned_directories,
            "scan_seconds": index.scan_seconds,
            "cached": cached,
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
