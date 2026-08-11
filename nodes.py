from __future__ import annotations

import json
import os

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

import folder_paths
import node_helpers

from .folder_browser import resolve_image_path


MODE_LIBRARY = "library"
MODE_FOLDER = "folder"


def _parse_folder_state(value: str) -> dict[str, object]:
    try:
        state = json.loads(value or "{}")
        return state if isinstance(state, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _resolve_selected_path(
    image: str,
    source_mode: str,
    folder_path: str,
    folder_image: str,
    folder_state: str,
) -> str:
    if source_mode == MODE_FOLDER:
        state = _parse_folder_state(folder_state)
        edits = state.get("edits", {})
        edited_image = edits.get(folder_image, "") if isinstance(edits, dict) else ""
        if isinstance(edited_image, str) and edited_image:
            try:
                if folder_paths.exists_annotated_filepath(edited_image):
                    return folder_paths.get_annotated_filepath(edited_image)
            except (OSError, ValueError):
                pass
        return resolve_image_path(folder_image, folder_path)

    if not image:
        raise ValueError("No image is selected / 未选择图片。")
    if not folder_paths.exists_annotated_filepath(image):
        raise ValueError(f"Invalid image file: {image}")
    return folder_paths.get_annotated_filepath(image)


def _load_image_and_mask(image_path: str) -> tuple[torch.Tensor, torch.Tensor]:
    source = node_helpers.pillow(Image.open, image_path)
    output_images: list[torch.Tensor] = []
    output_masks: list[torch.Tensor] = []
    width: int | None = None
    height: int | None = None

    try:
        for frame in ImageSequence.Iterator(source):
            frame = node_helpers.pillow(ImageOps.exif_transpose, frame)
            if frame.mode == "I":
                frame = frame.point(lambda value: value * (1 / 255))

            image_rgb = frame.convert("RGB")
            if width is None or height is None:
                width, height = image_rgb.size
            if image_rgb.size != (width, height):
                continue

            image_np = np.array(image_rgb).astype(np.float32) / 255.0
            output_images.append(torch.from_numpy(image_np)[None,])

            if "A" in frame.getbands():
                alpha = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
                mask = 1.0 - torch.from_numpy(alpha)
            elif frame.mode == "P" and "transparency" in frame.info:
                alpha = (
                    np.array(frame.convert("RGBA").getchannel("A")).astype(np.float32)
                    / 255.0
                )
                mask = 1.0 - torch.from_numpy(alpha)
            else:
                mask = torch.zeros((height, width), dtype=torch.float32, device="cpu")
            output_masks.append(mask.unsqueeze(0))

            if source.format == "MPO":
                break
    finally:
        source.close()

    if not output_images:
        raise ValueError(f"The image contains no readable frames: {image_path}")
    if len(output_images) == 1:
        return output_images[0], output_masks[0]
    return torch.cat(output_images, dim=0), torch.cat(output_masks, dim=0)


class AdvancedImageLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("STRING", {"default": ""}),
                "managed_images": ("STRING", {"default": "[]", "multiline": True}),
                "source_mode": ("STRING", {"default": MODE_LIBRARY}),
                "folder_path": ("STRING", {"default": ""}),
                "folder_image": ("STRING", {"default": ""}),
                "folder_state": ("STRING", {"default": "{}", "multiline": True}),
            }
        }

    CATEGORY = "image/loaders"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "load_image"
    SEARCH_ALIASES = [
        "advanced load image",
        "advanced image loader",
        "load image",
        "image loader",
        "image manager",
        "image switcher",
        "reference image",
        "folder image loader",
        "mask image loader",
        "高级加载图像",
        "加载图片",
        "文件夹图片",
    ]
    DESCRIPTION = (
        "Load and switch managed images or browse a folder efficiently, with IMAGE and MASK outputs."
    )

    def load_image(
        self,
        image: str,
        managed_images: str = "[]",
        source_mode: str = MODE_LIBRARY,
        folder_path: str = "",
        folder_image: str = "",
        folder_state: str = "{}",
    ):
        del managed_images
        image_path = _resolve_selected_path(
            image, source_mode, folder_path, folder_image, folder_state
        )
        return _load_image_and_mask(image_path)

    @classmethod
    def IS_CHANGED(
        cls,
        image: str,
        managed_images: str = "[]",
        source_mode: str = MODE_LIBRARY,
        folder_path: str = "",
        folder_image: str = "",
        folder_state: str = "{}",
    ):
        del managed_images
        try:
            image_path = _resolve_selected_path(
                image, source_mode, folder_path, folder_image, folder_state
            )
            stat = os.stat(image_path)
            return f"{os.path.normcase(image_path)}|{stat.st_mtime_ns}|{stat.st_size}"
        except (OSError, ValueError):
            return ""

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        image: str,
        managed_images: str = "[]",
        source_mode: str = MODE_LIBRARY,
        folder_path: str = "",
        folder_image: str = "",
        folder_state: str = "{}",
    ):
        del managed_images
        try:
            _resolve_selected_path(
                image, source_mode, folder_path, folder_image, folder_state
            )
        except (OSError, ValueError) as error:
            return str(error)
        return True


# Kept for third-party imports and existing workflows.
ReferenceImageManager = AdvancedImageLoader
