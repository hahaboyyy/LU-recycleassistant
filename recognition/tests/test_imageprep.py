import io

import pytest
from PIL import Image

from conftest import make_image
from reco.imageprep import ImageError, image_sha256, prepare_image


def test_png_rgba_becomes_jpeg_data_url():
    raw = make_image(size=(320, 240), mode="RGBA", color=(10, 200, 10, 128))
    prepared = prepare_image(raw, max_edge=1280)
    assert prepared.data_url.startswith("data:image/jpeg;base64,")
    assert (prepared.width, prepared.height) == (320, 240)
    assert prepared.nbytes > 0
    # the encoded payload really is a JPEG
    import base64

    payload = base64.b64decode(prepared.data_url.split(",", 1)[1])
    assert payload[:2] == b"\xff\xd8"


def test_large_image_is_downscaled_preserving_aspect():
    raw = make_image(size=(3000, 2000), fmt="JPEG")
    prepared = prepare_image(raw, max_edge=1280)
    assert max(prepared.width, prepared.height) == 1280
    assert abs(prepared.width / prepared.height - 1.5) < 0.02


def test_exif_rotation_is_applied():
    img = Image.new("RGB", (120, 60), (30, 30, 30))
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 degrees
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    prepared = prepare_image(buf.getvalue())
    assert (prepared.width, prepared.height) == (60, 120)


def test_missing_file_raises_image_error(tmp_path):
    with pytest.raises(ImageError):
        prepare_image(tmp_path / "nope.jpg")


def test_garbage_bytes_raise_image_error():
    with pytest.raises(ImageError):
        prepare_image(b"not an image at all")


def test_sha_is_stable_and_content_based():
    raw = make_image()
    assert image_sha256(raw) == image_sha256(raw)
    assert image_sha256(raw) != image_sha256(make_image(color=(0, 0, 0)))
