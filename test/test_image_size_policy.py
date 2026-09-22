from __future__ import annotations

import base64
import threading
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image

from services.protocol.conversation import ConversationRequest, ImageOutput
from services.protocol.openai_v1_image_edit import handle as handle_image_edit
from services.protocol.openai_v1_image_generations import resolve_stream_image_outputs


def _png_b64(width: int, height: int) -> str:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _result(width: int, height: int) -> list[ImageOutput]:
    return [
        ImageOutput(
            kind="result",
            model="gpt-image-2",
            index=1,
            total=1,
            data=[{"b64_json": _png_b64(width, height), "revised_prompt": "cat"}],
        ),
    ]


def _sequenced_pool(results: list[list[ImageOutput]]):
    lock = threading.Lock()
    state = {"index": 0}

    def fake_pool(*_args, **_kwargs):
        with lock:
            index = state["index"]
            state["index"] += 1
        return results[min(index, len(results) - 1)]

    return fake_pool, state


class ImageSizePolicyTests(unittest.TestCase):
    def test_auto_size_does_not_retry_ratio(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool",
            return_value=_result(1024, 1024),
        ) as pool:
            list(resolve_stream_image_outputs(ConversationRequest(prompt="cat", size="auto")))
        self.assertEqual(pool.call_count, 1)

    def test_explicit_size_keeps_first_when_ratio_matches(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool",
            return_value=_result(1024, 1536),
        ) as pool:
            outputs = list(resolve_stream_image_outputs(ConversationRequest(prompt="cat", size="1024x1536")))
        self.assertEqual(pool.call_count, 1)
        self.assertEqual(
            Image.open(BytesIO(base64.b64decode(outputs[0].data[0]["b64_json"]))).size,
            (1024, 1536),
        )

    def test_explicit_size_runs_two_concurrent_when_first_ratio_mismatches(self) -> None:
        fake_pool, state = _sequenced_pool([
            _result(1024, 1024),
            _result(1024, 1536),
            _result(1024, 1024),
        ])
        with mock.patch(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool",
            side_effect=fake_pool,
        ):
            outputs = list(resolve_stream_image_outputs(ConversationRequest(prompt="cat", size="1024x1536")))
        self.assertEqual(state["index"], 3)
        self.assertEqual(
            Image.open(BytesIO(base64.b64decode(outputs[0].data[0]["b64_json"]))).size,
            (1024, 1536),
        )

    def test_explicit_size_picks_best_of_three_after_one_round(self) -> None:
        fake_pool, state = _sequenced_pool([
            _result(1024, 1024),
            _result(1024, 1024),
            _result(1024, 1400),
        ])
        with mock.patch(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool",
            side_effect=fake_pool,
        ):
            outputs = list(resolve_stream_image_outputs(ConversationRequest(prompt="cat", size="1024x1536")))
        self.assertEqual(state["index"], 3)
        self.assertEqual(
            Image.open(BytesIO(base64.b64decode(outputs[0].data[0]["b64_json"]))).size,
            (1024, 1400),
        )

    def test_edit_auto_size_is_not_inferred_from_input_pixels(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (461, 819), color=(255, 0, 0)).save(buffer, format="PNG")
        captured: dict[str, object] = {}

        def fake_resolve(request: ConversationRequest):
            captured["size"] = request.size
            return _result(1024, 1536)

        with mock.patch(
            "services.protocol.openai_v1_image_edit.resolve_stream_image_outputs",
            fake_resolve,
        ):
            handle_image_edit({
                "prompt": "edit",
                "images": [(buffer.getvalue(), "one.png", "image/png")],
                "size": "auto",
            })
        self.assertEqual(captured["size"], "auto")


if __name__ == "__main__":
    unittest.main()
