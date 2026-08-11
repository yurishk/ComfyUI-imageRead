"""Advanced Image Loader for ComfyUI."""

from .nodes import AdvancedImageLoader
from .server_routes import register_routes


# The legacy internal ID is intentionally retained so existing workflows keep loading.
NODE_CLASS_MAPPINGS = {
    "Reference Image Manager": AdvancedImageLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Reference Image Manager": "Advanced Load Image",
}

WEB_DIRECTORY = "./web"

register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
