"""Image preparation: phone photo in, small deterministic JPEG data URL out.

Why this exists: campus photos are large and rotated by EXIF, and API payloads
are billed by size and limited in bytes. Every call therefore goes through the
same crop-free, aspect-preserving normalisation, which also makes runs
comparable between the baseline and the improved pipeline.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

#: Providers reject very large payloads; 4 MB base64 is a safe practical ceiling.
MAX_RAW_BYTES = 4_000_000


class ImageError(Exception):
    """The file could not be read as an image we can send."""


@dataclass(frozen=True)
class PreparedImage:
    data_url: str
    sha256: str
    width: int
    height: int
    nbytes: int
    source: str

    @property
    def size_label(self) -> str:
        return f"{self.width}x{self.height}, {self.nbytes // 1024} KB"


def _read_bytes(source: str | Path | bytes) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        return source, "<bytes>"
    path = Path(source)
    if not path.exists():
        raise ImageError(f"image not found: {path}")
    data = path.read_bytes()
    if not data:
        raise ImageError(f"image file is empty: {path}")
    if len(data) > MAX_RAW_BYTES * 4:
        raise ImageError(f"image file too large ({len(data) // 1024} KB): {path}")
    return data, str(path)


def prepare_image(
    source: str | Path | bytes,
    max_edge: int = 1280,
    quality: int = 85,
) -> PreparedImage:
    """Normalise to sRGB JPEG, longest edge <= max_edge, then base64 data URL."""
    raw, label = _read_bytes(source)
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError(f"cannot decode image {label}: {exc}") from exc

    # Phone cameras store rotation in EXIF; without this the model sees it sideways.
    img = ImageOps.exif_transpose(img)

    if img.mode in {"RGBA", "LA", "P"}:
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        img = canvas
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    payload = buf.getvalue()

    digest = hashlib.sha256(raw).hexdigest()
    encoded = base64.b64encode(payload).decode("ascii")
    return PreparedImage(
        data_url=f"data:image/jpeg;base64,{encoded}",
        sha256=digest,
        width=img.width,
        height=img.height,
        nbytes=len(payload),
        source=label,
    )


def image_sha256(source: str | Path | bytes) -> str:
    raw, _ = _read_bytes(source)
    return hashlib.sha256(raw).hexdigest()
