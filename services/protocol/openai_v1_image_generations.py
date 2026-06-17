from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

from PIL import Image

from services.protocol.conversation import (
    ConversationRequest,
    ImageOutput,
    collect_image_outputs,
    count_text_tokens,
    save_image_bytes,
    stream_image_chunks,
    stream_image_outputs_with_pool,
)
from utils.image_tokens import count_image_output_items_tokens, image_size_from_bytes, image_usage, parse_image_size

EXTREME_ASPECT_RATIO_THRESHOLD = 2
POOL_RETRY_ATTEMPTS = 3
CONCURRENT_POOL_WORKERS = 2
ASPECT_RATIO_TOLERANCE = 0.01
DIMENSION_TOLERANCE = 2


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    quality = str(body.get("quality") or "auto")
    response_format = str(body.get("response_format") or "b64_json")
    base_url = str(body.get("base_url") or "") or None
    progress_callback = body.get("progress_callback")
    request = ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        size=size,
        quality=quality,
        response_format=response_format,
        base_url=base_url,
        message_as_error=True,
        progress_callback=progress_callback,
    )
    outputs = resolve_stream_image_outputs(request)
    if body.get("stream"):
        return stream_image_chunks(outputs)
    result = collect_image_outputs(outputs)
    result = normalize_collected_image_sizes(result, size, response_format, base_url)
    result["usage"] = image_usage(
        input_text_tokens=count_text_tokens(prompt, model),
        output_tokens=count_image_output_items_tokens(result.get("data"), size, quality),
    )
    return result


def resolve_stream_image_outputs(request: ConversationRequest) -> Iterator[ImageOutput]:
    if is_extreme_aspect_ratio(request.size):
        return stream_image_outputs_with_pools(request)
    return stream_image_outputs_with_pool(request)


def is_extreme_aspect_ratio(size: object) -> bool:
    width, height = parse_image_size(size)
    if width <= 0 or height <= 0:
        return False
    return max(width / height, height / width) > EXTREME_ASPECT_RATIO_THRESHOLD


def stream_image_outputs_with_pools(request: ConversationRequest) -> Iterator[ImageOutput]:
    target_size = parse_image_size(request.size)
    best_outputs: list[ImageOutput] | None = None
    best_score = float("inf")

    for _ in range(POOL_RETRY_ATTEMPTS):
        batch_results = _run_concurrent_image_pools(request)
        for outputs in batch_results:
            if outputs_have_close_aspect_ratio(outputs, target_size):
                yield from outputs
                return
            score = outputs_aspect_ratio_score(outputs, target_size)
            if score < best_score:
                best_score = score
                best_outputs = outputs

    if best_outputs:
        yield from best_outputs
        return

    yield from stream_image_outputs_with_pool(request)


def normalize_collected_image_sizes(
    result: dict[str, Any],
    size: object,
    response_format: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    target_size = parse_image_size(size)
    data = result.get("data")
    if not isinstance(data, list):
        return result

    for item in data:
        if not isinstance(item, dict):
            continue
        image_bytes = image_bytes_from_result_item(item)
        if image_bytes is None:
            continue
        actual_size = image_size_from_bytes(image_bytes)
        if actual_size == target_size:
            continue
        resized_bytes = resize_image_bytes(image_bytes, target_size[0], target_size[1])
        apply_resized_image_to_result_item(item, resized_bytes, response_format, base_url)
        # 简单测试：记录 resize 前后图片
        #ts = int(time.time() * 1000)
        #tmp_dir = Path("clients/tmp")
        #tmp_dir.mkdir(parents=True, exist_ok=True)
        #(tmp_dir / f"{ts}_orig.png").write_bytes(image_bytes)
        #(tmp_dir / f"{ts}_new.png").write_bytes(resized_bytes)

    return result


def _run_concurrent_image_pools(request: ConversationRequest) -> list[list[ImageOutput]]:
    results: list[list[ImageOutput]] = []
    with ThreadPoolExecutor(max_workers=CONCURRENT_POOL_WORKERS) as executor:
        futures = [executor.submit(_collect_image_outputs, request) for _ in range(CONCURRENT_POOL_WORKERS)]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                continue
    return results


def _collect_image_outputs(request: ConversationRequest) -> list[ImageOutput]:
    return list(stream_image_outputs_with_pool(request))


def outputs_have_close_aspect_ratio(outputs: list[ImageOutput], target_size: tuple[int, int]) -> bool:
    result_sizes = collect_result_image_sizes(outputs)
    if not result_sizes:
        return False
    return all(aspect_ratio_close(actual_size, target_size) for actual_size in result_sizes)


def outputs_aspect_ratio_score(outputs: list[ImageOutput], target_size: tuple[int, int]) -> float:
    result_sizes = collect_result_image_sizes(outputs)
    if not result_sizes:
        return float("inf")
    target_ratio = target_size[0] / target_size[1]
    return max(abs((size[0] / size[1]) - target_ratio) / target_ratio for size in result_sizes)


def collect_result_image_sizes(outputs: list[ImageOutput]) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for output in outputs:
        if output.kind != "result":
            continue
        for item in output.data:
            if not isinstance(item, dict):
                continue
            image_bytes = image_bytes_from_result_item(item)
            if image_bytes is None:
                continue
            actual_size = image_size_from_bytes(image_bytes)
            if actual_size:
                sizes.append(actual_size)
    return sizes


def aspect_ratio_close(actual_size: tuple[int, int], target_size: tuple[int, int]) -> bool:
    actual_width, actual_height = actual_size
    target_width, target_height = target_size
    if actual_width == target_width and actual_height == target_height:
        return True
    if abs(actual_width - target_width) <= DIMENSION_TOLERANCE and abs(actual_height - target_height) <= DIMENSION_TOLERANCE:
        return True
    target_ratio = target_width / target_height
    actual_ratio = actual_width / actual_height
    return abs(actual_ratio - target_ratio) / target_ratio <= ASPECT_RATIO_TOLERANCE


def image_bytes_from_result_item(item: dict[str, Any]) -> bytes | None:
    b64_json = str(item.get("b64_json") or "").strip()
    if b64_json:
        try:
            return base64.b64decode(b64_json)
        except Exception:
            return None
    return None


def apply_resized_image_to_result_item(
    item: dict[str, Any],
    image_bytes: bytes,
    response_format: str,
    base_url: str | None,
) -> None:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    image_url = save_image_bytes(image_bytes, base_url)
    if response_format == "b64_json":
        item["b64_json"] = encoded
        if image_url:
            item["url"] = image_url
        return
    item.pop("b64_json", None)
    item["url"] = image_url


def resize_image_bytes(image_bytes: bytes, width: int, height: int) -> bytes:
    with Image.open(BytesIO(image_bytes)) as image:
        if image.size == (width, height):
            return image_bytes
        resized = image.resize((width, height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        fmt = (image.format or "PNG").upper()
        save_kwargs: dict[str, Any] = {}
        if fmt == "JPEG":
            save_kwargs = {"quality": 95, "subsampling": 0, "optimize": True}
        elif fmt == "WEBP":
            save_kwargs = {"quality": 95, "method": 6}
        elif fmt == "PNG":
            save_kwargs = {"compress_level": 1}
        resized.save(buffer, format=fmt, **save_kwargs)
        return buffer.getvalue()
