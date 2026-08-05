"""
Reference Image Manager for ComfyUI.
"""

from .nodes import ReferenceImageManager

NODE_CLASS_MAPPINGS = {
    "Reference Image Manager": ReferenceImageManager,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Reference Image Manager": "Reference Image Manager",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
