import asyncio
import base64
import io
import json

import httpx
import pytest
import re

from backend.app.presets import PRESETS, composition_guidance, provider_size
from backend.app.services.image_generation import (
    GenerationFailure,
    generate_openai,
    process_image,
)
from PIL import Image


def image_bytes():
    image = Image.new("RGB", (40, 20), "red")
    for x in range(10, 30):
        for y in range(20):
            image.putpixel((x, y), (0, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("preset", PRESETS)
def test_all_presets_are_exact_png_dimensions(preset):
    width, height, _ = PRESETS[preset]
    result = process_image(image_bytes(), width, height)
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "PNG"
        assert image.size == (width, height)
        assert image.getpixel((width // 2, height // 2)) == (0, 255, 0)


def test_square_crop_keeps_center_not_edges():
    with Image.open(io.BytesIO(process_image(image_bytes(), 20, 20))) as image:
        assert image.getpixel((1, 10)) == (0, 255, 0)
        assert image.getpixel((18, 10)) == (0, 255, 0)


@pytest.mark.parametrize("preset", PRESETS)
def test_composition_guidance_matches_the_actual_crop(preset):
    """Content inside the band the prompt describes must survive the crop, and
    the band must not be much smaller than what is actually kept."""
    width, height, _ = PRESETS[preset]
    guidance = composition_guidance(width, height)
    canvas_width, canvas_height = map(int, provider_size(width, height).split("x"))
    canvas = Image.new("RGB", (canvas_width, canvas_height), (255, 0, 0))
    match = re.search(r"middle (\d+)% of the image (width|height)", guidance)
    if match is None:
        assert "whole image is used" in guidance
        band = (0, 0, canvas_width, canvas_height)
    else:
        share, axis = int(match[1]) / 100, match[2]
        if axis == "height":
            margin = round(canvas_height * (1 - share) / 2)
            band = (0, margin, canvas_width, canvas_height - margin)
        else:
            margin = round(canvas_width * (1 - share) / 2)
            band = (margin, 0, canvas_width - margin, canvas_height)
    canvas.paste((0, 255, 0), band)
    # Blue markers just inside both band edges must survive (band not overstated).
    left, top, right, bottom = band
    if match is not None and match[2] == "height":
        markers = [(left, top, right, top + 6), (left, bottom - 6, right, bottom)]
    else:
        markers = [(left, top, left + 6, bottom), (right - 6, top, right, bottom)]
    for marker in markers:
        canvas.paste((0, 0, 255), marker)
    buffer = io.BytesIO()
    canvas.save(buffer, "PNG")
    with Image.open(io.BytesIO(process_image(buffer.getvalue(), width, height))) as out:
        # Little red survives (band not understated)...
        red = sum(1 for r, g, b in out.getdata() if r > max(g, b))
        assert red / (width * height) < 0.02
        # ...and both edge markers are still present.
        edge = 0.05
        if match is not None and match[2] == "height":
            first = out.crop((0, 0, width, int(height * edge)))
            last = out.crop((0, int(height * (1 - edge)), width, height))
        else:
            first = out.crop((0, 0, int(width * edge), height))
            last = out.crop((int(width * (1 - edge)), 0, width, height))
        for region in (first, last):
            assert any(b > max(r, g) for r, g, b in region.getdata())


def test_provider_prompt_includes_composition_guidance():
    def handler(request):
        prompt = json.loads(request.content)["prompt"]
        assert composition_guidance(1584, 396) in prompt
        assert "middle 37% of the image height" in prompt
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]},
        )

    banner = {**job(), "width": 1584, "height": 396}
    asyncio.run(generate_openai(banner, "secret", httpx.MockTransport(handler)))


@pytest.mark.parametrize("data", [b"not an image", b"", b"\x89PNG\r\n"])
def test_malformed_image_is_safe_failure(data):
    with pytest.raises(GenerationFailure, match="INVALID_PROVIDER_IMAGE"):
        process_image(data, 1080, 1080)


def job():
    return {
        "width": 1080,
        "height": 1080,
        "context_snapshot": "Brand: Green",
        "prompt": "Green product launch",
    }


def test_provider_uses_fixed_model_png_and_snapshot_without_legacy_parameters():
    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/images/generations"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-image-2"
        assert payload["quality"] == "medium"
        assert payload["n"] == 1
        assert payload["output_format"] == "png"
        assert payload["size"] == "1024x1024"
        assert "Brand: Green" in payload["prompt"]
        assert "response_format" not in payload
        return httpx.Response(
            200,
            headers={"x-request-id": "safe-id"},
            json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]},
        )

    image, request_id = asyncio.run(
        generate_openai(job(), "secret", httpx.MockTransport(handler))
    )
    assert image.startswith(b"\x89PNG")
    assert request_id == "safe-id"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "OPENAI_KEY_REJECTED"),
        (403, "OPENAI_KEY_REJECTED"),
        (429, "PROVIDER_RATE_LIMITED"),
        (400, "PROVIDER_REJECTED"),
        (500, "PROVIDER_UNAVAILABLE"),
    ],
)
def test_provider_failure_never_exposes_or_retries_remote_body(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "raw-secret-and-user-content"})

    with pytest.raises(GenerationFailure) as error:
        asyncio.run(generate_openai(job(), "raw-secret", httpx.MockTransport(handler)))
    assert error.value.code == code
    assert "raw-secret" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body", [{}, {"data": []}, {"data": [{"b64_json": "invalid%"}]}]
)
def test_invalid_provider_payload(body):
    with pytest.raises(GenerationFailure, match="INVALID_PROVIDER_IMAGE"):
        asyncio.run(
            generate_openai(
                job(),
                "secret",
                httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
            )
        )


def test_timeout_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("raw-secret")

    with pytest.raises(GenerationFailure, match="PROVIDER_TIMEOUT"):
        asyncio.run(generate_openai(job(), "secret", httpx.MockTransport(handler)))
    assert len(calls) == 1


def test_provider_request_sizes_are_supported():
    assert provider_size(1080, 1080) == "1024x1024"
    assert provider_size(820, 312) == "1536x1024"
    assert provider_size(1080, 1920) == "1024x1536"
