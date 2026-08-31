from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any, Iterable, Iterator

from services.protocol.conversation import (
    ConversationRequest,
    ImageGenerationError,
    ImageOutput,
    collect_image_outputs,
    count_text_tokens,
    save_image_bytes,
    stream_image_chunks,
    stream_image_outputs_with_pool,
)
from utils.image_format import encode_image_bytes, normalize_output_format, output_format_from_bytes, parse_output_compression
from utils.image_tokens import count_image_output_items_tokens, image_size_from_bytes, image_usage, parse_image_size

EXTREME_ASPECT_RATIO_THRESHOLD = 2
POOL_RETRY_ATTEMPTS = 3
CONCURRENT_POOL_WORKERS = 2
ASPECT_RATIO_TOLERANCE = 0.015
DIMENSION_TOLERANCE = 5


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    quality = str(body.get("quality") or "auto")
    response_format = str(body.get("response_format") or "b64_json")
    output_format = _request_output_format(body)
    output_compression = _request_output_compression(body)
    base_url = str(body.get("base_url") or "") or None
    progress_callback = body.get("progress_callback")
    stream = bool(body.get("stream"))
    request = ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        size=size,
        quality=quality,
        response_format="b64_json" if response_format == "url" else response_format,
        output_format=output_format,
        output_compression=output_compression,
        base_url=base_url,
        message_as_error=True,
        progress_callback=progress_callback,
    )
    outputs = finalize_image_outputs(
        limit_image_outputs(resolve_stream_image_outputs(request), n),
        size,
        response_format,
        base_url,
        output_format=output_format,
    )
    if stream:
        return stream_image_chunks(outputs)
    result = collect_image_outputs(outputs)
    result["usage"] = image_usage(
        input_text_tokens=count_text_tokens(prompt, model),
        output_tokens=count_image_output_items_tokens(result.get("data"), size, quality),
    )
    return limit_collected_image_data(result, n)


def _request_output_format(body: dict[str, Any]) -> str:
    try:
        return normalize_output_format(body.get("output_format"))
    except ValueError as exc:
        raise ImageGenerationError(str(exc), status_code=400, error_type="invalid_request_error", code="invalid_value", param="output_format") from exc


def _request_output_compression(body: dict[str, Any]) -> int | None:
    try:
        return parse_output_compression(body.get("output_compression"))
    except ValueError as exc:
        raise ImageGenerationError(str(exc), status_code=400, error_type="invalid_request_error", code="invalid_value", param="output_compression") from exc


def requested_image_count(n: object) -> int:
    try:
        count = int(n or 1)
    except (TypeError, ValueError):
        return 1
    return max(count, 1)


def limit_image_outputs(outputs: Iterable[ImageOutput], n: object) -> Iterator[ImageOutput]:
    remaining = requested_image_count(n)
    for output in outputs:
        if output.kind != "result":
            yield output
            continue
        if remaining <= 0:
            continue
        data = list(output.data or [])
        if len(data) <= remaining:
            remaining -= len(data)
            yield output
            continue
        yield replace(output, data=data[:remaining])
        remaining = 0


def limit_collected_image_data(result: dict[str, Any], n: object) -> dict[str, Any]:
    data = result.get("data")
    limit = requested_image_count(n)
    if isinstance(data, list) and len(data) > limit:
        result["data"] = data[:limit]
    return result


def is_auto_image_size(size: object) -> bool:
    return str(size or "").strip().lower() in {"", "auto"}


def resolve_stream_image_outputs(request: ConversationRequest) -> Iterator[ImageOutput]:
    if is_auto_image_size(request.size):
        return stream_image_outputs_with_pool(request)
    if is_extreme_aspect_ratio(request.size):
        return stream_image_outputs_with_pools(request)
    return stream_image_outputs_with_ratio_retry(request)


def is_extreme_aspect_ratio(size: object) -> bool:
    if is_auto_image_size(size):
        return False
    width, height = parse_image_size(size)
    if width <= 0 or height <= 0:
        return False
    return max(width / height, height / width) > EXTREME_ASPECT_RATIO_THRESHOLD


def stream_image_outputs_with_ratio_retry(request: ConversationRequest) -> Iterator[ImageOutput]:
    target_size = parse_image_size(request.size)
    first_outputs = list(stream_image_outputs_with_pool(request))
    if first_outputs and outputs_have_close_aspect_ratio(first_outputs, target_size):
        yield from first_outputs
        return
    yield from stream_image_outputs_with_pools(request, seed_outputs=first_outputs or None)


def stream_image_outputs_with_pools(
    request: ConversationRequest,
    seed_outputs: list[ImageOutput] | None = None,
) -> Iterator[ImageOutput]:
    target_size = parse_image_size(request.size)
    best_outputs = seed_outputs if seed_outputs else None
    best_score = outputs_aspect_ratio_score(seed_outputs, target_size) if seed_outputs else float("inf")

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


def finalize_image_outputs(
    outputs: Iterable[ImageOutput],
    size: object,
    response_format: str,
    base_url: str | None = None,
    output_format: str = "png",
) -> Iterator[ImageOutput]:
    for output in outputs:
        if output.kind != "result":
            yield output
            continue
        result = normalize_collected_image_sizes(
            {"data": list(output.data or [])},
            size,
            "b64_json",
            base_url,
            output_format=output_format,
        )
        if response_format == "url":
            apply_url_response_format(result.get("data"), base_url)
        yield replace(output, data=result.get("data") or [])


def normalize_collected_image_sizes(
    result: dict[str, Any],
    size: object,
    response_format: str,
    base_url: str | None = None,
    output_format: str = "png",
) -> dict[str, Any]:
    target_size = None if is_auto_image_size(size) else parse_image_size(size)
    data = result.get("data")
    if not isinstance(data, list):
        return result
    target_format = normalize_output_format(output_format)

    for item in data:
        if not isinstance(item, dict):
            continue
        image_bytes = image_bytes_from_result_item(item)
        if image_bytes is None:
            continue
        actual_size = image_size_from_bytes(image_bytes)
        same_format = output_format_from_bytes(image_bytes) == target_format
        if target_size is None:
            if same_format:
                continue
            encoded_bytes = encode_image_bytes(image_bytes, output_format=target_format)
        else:
            if actual_size == target_size and same_format:
                continue
            encoded_bytes = encode_image_bytes(
                image_bytes,
                output_format=target_format,
                width=target_size[0],
                height=target_size[1],
            )
        if encoded_bytes == image_bytes:
            continue
        apply_resized_image_to_result_item(item, encoded_bytes, response_format, base_url)

    return result


def apply_url_response_format(data: object, base_url: str | None = None) -> None:
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        image_bytes = image_bytes_from_result_item(item)
        if image_bytes is None:
            continue
        item.pop("b64_json", None)
        item["url"] = save_image_bytes(image_bytes, base_url, force=True)


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


def resize_image_bytes(image_bytes: bytes, width: int, height: int, output_format: str | None = None) -> bytes:
    return encode_image_bytes(
        image_bytes,
        output_format=output_format or output_format_from_bytes(image_bytes),
        width=width,
        height=height,
    )
