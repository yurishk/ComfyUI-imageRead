from __future__ import annotations

import json
import os
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from .folder_browser import normalize_folder, resolve_folder_path, resolve_image_path


class FolderAccessDenied(PermissionError):
    """Raised when no live capability grants access to a local folder."""


class FolderGrantStore:
    """Keeps persistent folder grants and short-lived image capabilities."""

    def __init__(
        self,
        max_grants: int = 128,
        max_files: int = 4096,
        storage_path: str | os.PathLike[str] | None = None,
    ):
        self.max_grants = max(1, int(max_grants))
        self.max_files = max(1, int(max_files))
        self._grants: OrderedDict[str, str] = OrderedDict()
        self._files: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._file_ids: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._storage_path: Path | None = None
        if storage_path is not None:
            self.configure_storage(storage_path)

    def configure_storage(self, storage_path: str | os.PathLike[str]) -> None:
        path = Path(storage_path).expanduser().resolve()
        with self._lock:
            if self._storage_path == path:
                return
            self._storage_path = path
            self._grants.clear()
            self._files.clear()
            self._file_ids.clear()
            self._load_locked()

    def _load_locked(self) -> None:
        if self._storage_path is None or not self._storage_path.is_file():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return

        grants = payload.get("grants", []) if isinstance(payload, dict) else []
        if not isinstance(grants, list):
            return
        self._grants.clear()
        for item in grants[-self.max_grants :]:
            if not isinstance(item, dict):
                continue
            grant = item.get("id")
            root = item.get("root")
            if isinstance(grant, str) and grant and isinstance(root, str) and root:
                self._grants[grant] = root

    def _save_locked(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "grants": [
                {"id": grant, "root": root} for grant, root in self._grants.items()
            ],
        }
        temporary = self._storage_path.with_suffix(
            f"{self._storage_path.suffix}.tmp"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self._storage_path)

    def authorize(self, folder: str) -> tuple[str, str]:
        root = normalize_folder(folder)
        with self._lock:
            for existing_grant, existing_root in self._grants.items():
                if os.path.normcase(existing_root) == os.path.normcase(root):
                    self._grants.move_to_end(existing_grant)
                    return existing_grant, root

            grant = secrets.token_urlsafe(32)
            self._grants[grant] = root
            self._grants.move_to_end(grant)
            while len(self._grants) > self.max_grants:
                self._grants.popitem(last=False)
            self._save_locked()
        return grant, root

    def root_for(self, grant: str) -> str:
        if not isinstance(grant, str) or not grant.strip():
            raise FolderAccessDenied(
                "Folder permission is missing or expired. Choose the folder again."
            )
        with self._lock:
            root = self._grants.get(grant)
            if root is None:
                raise FolderAccessDenied(
                    "Folder permission is missing or expired. Choose the folder again."
                )
            self._grants.move_to_end(grant)
            return root

    def resolve_folder(self, grant: str, folder: str) -> tuple[str, str]:
        root = self.root_for(grant)
        return root, resolve_folder_path(folder or root, root)

    def issue_file(self, grant: str, path: str) -> str:
        root = self.root_for(grant)
        resolved = resolve_image_path(path, root)
        key = (grant, os.path.normcase(resolved))
        with self._lock:
            existing = self._file_ids.get(key)
            if existing in self._files:
                self._files.move_to_end(existing)
                return existing

            file_id = secrets.token_urlsafe(32)
            self._files[file_id] = (grant, resolved)
            self._file_ids[key] = file_id
            while len(self._files) > self.max_files:
                _, (expired_grant, expired_path) = self._files.popitem(last=False)
                self._file_ids.pop(
                    (expired_grant, os.path.normcase(expired_path)), None
                )
            return file_id

    def resolve_file(self, file_id: str) -> tuple[str, str]:
        if not isinstance(file_id, str) or not file_id.strip():
            raise FolderAccessDenied(
                "Image permission is missing or expired. Refresh the folder."
            )
        with self._lock:
            entry = self._files.get(file_id)
            if entry is None:
                raise FolderAccessDenied(
                    "Image permission is missing or expired. Refresh the folder."
                )
            self._files.move_to_end(file_id)
            grant, path = entry
        root = self.root_for(grant)
        return resolve_image_path(path, root), root


FOLDER_GRANTS = FolderGrantStore()
