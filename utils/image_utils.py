"""
Image and mask helpers for ComfyUI_to_webui V2.

Handles extraction of image/mask data from Gradio ImageEditor payloads and
persists them into ComfyUI's input directory so workflow nodes can consume
them without relying on legacy Hua APIs.
"""

import uuid
from PIL import ImageChops
from pathlib import Path
from typing import Tuple, Optional, Any

from PIL import Image


def extract_image_and_mask(image_data: Any) -> Tuple[Optional[Image.Image], Optional[Image.Image]]:
    """
    Extract base image and mask from Gradio ImageEditor output.

    Expected formats:
    - dict with keys "image" and "mask" (Gradio ImageEditor with layers)
    - raw PIL.Image (no mask)
    - None (no upload)
    """
    if image_data is None:
        return None, None

    # Gradio ImageEditor returns a dict when layers=True
    if isinstance(image_data, dict):
        # Prefer the base image; fall back to background, then composite
        base_image = (
            image_data.get("image")
            or image_data.get("background")
            or image_data.get("composite")
        )
        mask = _normalize_mask(image_data.get("mask"))

        # Derive mask if not explicitly provided
        if mask is None:
            composite = image_data.get("composite")
            if composite and base_image:
                try:
                    # Use RGB difference to detect painted regions
                    comp_rgb = composite.convert("RGB")
                    base_rgb = base_image.convert("RGB")
                    if comp_rgb.size == base_rgb.size:
                        diff = ImageChops.difference(comp_rgb, base_rgb).convert("L")
                        mask = diff.point(lambda p: 0 if p > 0 else 255)  # invert: painted areas -> 0, background -> 255
                except Exception:
                    mask = None

            # Last resort: if composite has alpha, use it
            if mask is None and composite and "A" in composite.getbands():
                alpha = composite.getchannel("A")
                mask = alpha.point(lambda p: 0 if p < 255 else 255)  # invert so paint -> 0
                mask = _normalize_mask(mask)

        return base_image, mask

    # Plain PIL image (no mask)
    if isinstance(image_data, Image.Image):
        return image_data, None

    # Unknown format
    return None, None


def _normalize_mask(mask: Any) -> Optional[Image.Image]:
    """
    Convert masks to a binary single-channel image suitable for ComfyUI.

    - If mask is RGBA/LA, use alpha channel.
    - Otherwise convert to L and threshold >0 to 255.
    - Do not auto-invert; keep polarity as drawn.
    """
    if mask is None or not isinstance(mask, Image.Image):
        return None

    # Extract alpha if available
    if mask.mode in {"RGBA", "LA"}:
        mask = mask.getchannel("A")
    elif mask.mode != "L":
        mask = mask.convert("L")

    # Binarize (any painted pixel becomes 255)
    mask = mask.point(lambda p: 255 if p > 0 else 0)
    return mask


def save_pil_image_to_input(image: Image.Image, prefix: str = "upload") -> Optional[str]:
    """
    Save a PIL image into ComfyUI's input directory and return the relative filename.

    Args:
        image: PIL image to save
        prefix: filename prefix for clarity (e.g., "mask")

    Returns:
        Relative filename usable by ComfyUI nodes, or None on failure.
    """
    try:
        import folder_paths  # Provided by ComfyUI runtime
    except Exception:
        return None

    try:
        input_dir = Path(folder_paths.get_input_directory())
        input_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{prefix}_{uuid.uuid4().hex}.png"
        filepath = input_dir / filename
        image.save(filepath, format="PNG")

        # ComfyUI loaders expect a path relative to the input directory
        return filename
    except Exception:
        return None
