from __future__ import annotations

import unittest

from services.protocol.conversation import (
    FORCE_IMAGE_GENERATION_INSTRUCTION,
    force_image_generation_prompt,
    image_stream_error_message,
)


EMPTY_CONVERSATION_500 = "/backend-api/f/conversation failed: status=500, body="


class ImageErrorMessageTests(unittest.TestCase):
    def test_force_image_generation_prompt_appends_instruction_once(self):
        prompt = "A castle at sunset"

        self.assertEqual(
            force_image_generation_prompt(prompt),
            prompt + FORCE_IMAGE_GENERATION_INSTRUCTION,
        )

    def test_long_prompt_empty_upstream_500_suggests_shortening_prompt(self):
        message = image_stream_error_message(EMPTY_CONVERSATION_500, "a" * 20_001)

        self.assertEqual(message, "The image prompt may be too long. Please shorten it and try again.")

    def test_short_prompt_empty_upstream_500_keeps_upstream_error(self):
        self.assertEqual(image_stream_error_message(EMPTY_CONVERSATION_500, "a" * 20_000), EMPTY_CONVERSATION_500)

    def test_long_prompt_other_upstream_error_is_not_misattributed(self):
        message = image_stream_error_message("/backend-api/f/conversation failed: status=500, body=temporary failure", "a" * 20_001)

        self.assertEqual(message, "/backend-api/f/conversation failed: status=500, body=temporary failure")


if __name__ == "__main__":
    unittest.main()
