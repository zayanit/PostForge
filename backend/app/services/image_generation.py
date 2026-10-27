from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import warnings

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..presets import composition_guidance, provider_size

MAX_RESPONSE_BYTES = 70 * 1024 * 1024
MAX_IMAGE_BYTES = 50 * 1024 * 1024


class GenerationFailure(Exception):
    def __init__(self, code: str):
        self.code = code


def process_image(data: bytes, width: int, height: int) -> bytes:
    if len(data) > MAX_IMAGE_BYTES:
        raise GenerationFailure("INVALID_PROVIDER_IMAGE")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > 20_000_000:
                    raise GenerationFailure("INVALID_PROVIDER_IMAGE")
                source.load()
                result = ImageOps.fit(
                    source.convert("RGB"),
                    (width, height),
                    method=Image.Resampling.LANCZOS,
                )
                output = io.BytesIO()
                result.save(output, format="PNG")
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise GenerationFailure("INVALID_PROVIDER_IMAGE") from exc


async def generate_openai(job, key: str, transport=None) -> tuple[bytes, str | None]:
    try:
        async with asyncio.timeout(180):
            async with httpx.AsyncClient(
                timeout=180,
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": "gpt-image-2",
                        "n": 1,
                        "quality": "medium",
                        "output_format": "png",
                        "size": provider_size(job["width"], job["height"]),
                        "prompt": (
                            f"Brand context:\n{job['context_snapshot']}"
                            f"\n\nImage request:\n{job['prompt']}"
                            "\n\nComposition:\n"
                            f"{composition_guidance(job['width'], job['height'])}"
                        ),
                    },
                ) as response:
                    if response.status_code in (401, 403):
                        raise GenerationFailure("OPENAI_KEY_REJECTED")
                    if response.status_code == 429:
                        raise GenerationFailure("PROVIDER_RATE_LIMITED")
                    if response.status_code in (400, 422):
                        raise GenerationFailure("PROVIDER_REJECTED")
                    if not response.is_success:
                        raise GenerationFailure("PROVIDER_UNAVAILABLE")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise GenerationFailure("INVALID_PROVIDER_IMAGE")
                    request_id = response.headers.get("x-request-id")
                    if request_id and (key in request_id or len(request_id) > 200):
                        request_id = None
        body = json.loads(data)
        image = base64.b64decode(body["data"][0]["b64_json"], validate=True)
        return (
            await asyncio.to_thread(process_image, image, job["width"], job["height"]),
            request_id,
        )
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise GenerationFailure("PROVIDER_TIMEOUT") from exc
    except httpx.RequestError as exc:
        raise GenerationFailure("PROVIDER_UNAVAILABLE") from exc
    except (ValueError, KeyError, IndexError, TypeError, binascii.Error) as exc:
        raise GenerationFailure("INVALID_PROVIDER_IMAGE") from exc
