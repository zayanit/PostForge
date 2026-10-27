import asyncio
import base64
import io
import json

import httpx
import pytest
from backend.app.presets import PRESETS, provider_size
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
