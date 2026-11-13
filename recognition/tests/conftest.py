import io
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def make_image(size=(640, 480), mode="RGB", color=(200, 60, 60), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def photo() -> bytes:
    return make_image()
