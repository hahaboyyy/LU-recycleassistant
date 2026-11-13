"""Normalize uploaded and evaluation images before calling recognition."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError


def sanitize_photo(raw: bytes) -> bytes:
    if not raw or len(raw) > 12 * 1024 * 1024:
        raise ValueError("Choose a photo smaller than 12 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Use a JPEG, PNG or WebP photo.")
            if image.width * image.height > 20_000_000 or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Use one still image with at most 20 megapixels.")
            photo = ImageOps.exif_transpose(image).convert("RGB")
            photo.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            photo.save(output, format="JPEG", quality=88)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("This file could not be read as a photo. Please choose another one.") from exc
