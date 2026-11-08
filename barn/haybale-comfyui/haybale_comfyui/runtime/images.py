"""ImageValue ↔ PNG, for images sent to and received from ComfyUI."""

from __future__ import annotations

import base64
import io

import numpy as np
from haybale_image.value import ImageValue
from PIL import Image


def encode_png(image: ImageValue) -> str:
    """The image as a base64 PNG, 8 bits per channel; gray, RGB and RGBA keep their channels."""
    pixels = np.ascontiguousarray(image.array(np.uint8))
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_png(data: bytes) -> ImageValue:
    """A PNG (or any image Pillow reads) as an ImageValue; palette and other modes become RGB(A)."""
    with Image.open(io.BytesIO(data)) as img:
        if img.mode not in ("L", "RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
        pixels = np.array(img)
    return ImageValue.from_array(pixels)
