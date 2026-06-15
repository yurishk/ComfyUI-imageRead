import hashlib
import os

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

import folder_paths
import node_helpers


class ReferenceImageManager:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = []
        if os.path.isdir(input_dir):
            files = [
                f
                for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f))
            ]
            files = folder_paths.filter_files_content_types(files, ["image"])

        return {
            "required": {
                "image": ([""] + sorted(files), {"image_upload": True}),
                "managed_images": ("STRING", {"default": "[]", "multiline": True}),
            }
        }

    CATEGORY = "image/reference"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load_image"
    SEARCH_ALIASES = [
        "reference image",
        "image manager",
        "image switcher",
        "load image",
        "managed image",
    ]

    def load_image(self, image, managed_images="[]"):
        if not image:
            raise ValueError("参考图管理器未选择图片。")

        image_path = folder_paths.get_annotated_filepath(image)
        img = node_helpers.pillow(Image.open, image_path)

        output_images = []
        width, height = None, None

        for frame in ImageSequence.Iterator(img):
            frame = node_helpers.pillow(ImageOps.exif_transpose, frame)

            if frame.mode == "I":
                frame = frame.point(lambda i: i * (1 / 255))

            image_rgb = frame.convert("RGB")

            if not output_images:
                width, height = image_rgb.size

            if image_rgb.size != (width, height):
                continue

            image_np = np.array(image_rgb).astype(np.float32) / 255.0
            output_images.append(torch.from_numpy(image_np)[None,])

            if img.format == "MPO":
                break

        if len(output_images) > 1:
            return (torch.cat(output_images, dim=0),)

        return (output_images[0],)

    @classmethod
    def IS_CHANGED(cls, image, managed_images="[]"):
        if not image:
            return ""

        image_path = folder_paths.get_annotated_filepath(image)
        hasher = hashlib.sha256()
        with open(image_path, "rb") as image_file:
            hasher.update(image_file.read())
        return hasher.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(cls, image, managed_images="[]"):
        if not image:
            return "参考图管理器未选择图片。"

        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)
        return True
