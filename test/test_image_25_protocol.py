from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.openai_backend_api import OpenAIBackendAPI
from utils.helper import is_image_25_model, is_supported_image_model, split_image_model


class Image25ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = OpenAIBackendAPI(access_token="token")

    def tearDown(self) -> None:
        self.backend.close()

    def test_image_25_is_a_supported_web_image_model(self) -> None:
        self.assertEqual(split_image_model("gpt-image-2.5-flare"), (None, "gpt-image-2.5-flare"))
        self.assertEqual(split_image_model("gpt-image-2.5"), (None, "gpt-image-2.5-flare"))
        self.assertEqual(split_image_model("gpt-image-2.5-sunburst"), (None, "gpt-image-2.5-flare"))
        self.assertTrue(is_supported_image_model("gpt-image-2.5-flare"))
        self.assertTrue(is_supported_image_model("gpt-image-2.5"))
        self.assertTrue(is_supported_image_model("gpt-image-2.5-sunburst"))
        self.assertTrue(is_image_25_model("gpt-image-2.5-flare"))
        self.assertTrue(is_image_25_model("gpt-image-2.5"))
        self.assertTrue(is_image_25_model("gpt-image-2.5-sunburst"))
        self.assertFalse(is_image_25_model("gpt-image-2"))

    def test_image_model_slug_keeps_image_2_on_gpt_5_3(self) -> None:
        self.assertEqual(self.backend._image_model_slug("gpt-image-2"), "gpt-5-3")
        self.assertEqual(self.backend._image_model_slug("gpt-image-2.5-flare"), "auto")

    def test_image_25_prepare_payload_uses_contracts_not_picture_v2(self) -> None:
        payload = self.backend._image_25_prepare_payload("画一只猫", "gpt-image-2.5-flare")
        self.assertEqual(payload["model"], "auto")
        self.assertEqual(payload["system_hints"], [])
        self.assertEqual(payload["client_prepare_state"], "success")
        self.assertNotIn("fork_from_shared_post", payload)
        self.assertEqual(
            payload["model_response_contracts"],
            [{
                "id": "photo_upload_action.v1",
                "protocol_version": 1,
                "presets": ["cap:image", "cap:file", "placement:end"],
            }],
        )
        self.assertNotIn("picture_v2", str(payload))

    def test_image_25_generate_conversation_matches_text_to_image_har(self) -> None:
        payload = self.backend._image_25_conversation_payload("以雪为题，帮我生成一张图片", "gpt-image-2.5-flare")
        message = payload["messages"][0]
        self.assertEqual(payload["model"], "auto")
        self.assertEqual(payload["client_prepare_state"], "success")
        self.assertEqual(payload["system_hints"], [])
        self.assertEqual(payload["paragen_cot_summary_display_override"], "allow")
        self.assertEqual(payload["force_parallel_switch"], "auto")
        self.assertEqual(message["content"]["content_type"], "text")
        self.assertEqual(message["metadata"]["submission_mode"], "manual_send")
        self.assertNotIn("dalle", message["metadata"])
        self.assertNotIn("picture_v2", str(payload))

    def test_image_25_edit_conversation_matches_attachment_har(self) -> None:
        payload = self.backend._image_25_conversation_payload(
            "把这张图改成夕阳西下的景象",
            "gpt-image-2.5-flare",
            [{
                "file_id": "file_000000000ac481fd989e0b64e1fe71d6",
                "file_name": "20260909_104840.png",
                "file_size": 11247501,
                "mime_type": "image/png",
                "width": 2048,
                "height": 1152,
                "library_file_id": "libfile_d2a9f6445c4c8191a47159432bab5623",
            }],
        )
        message = payload["messages"][0]
        self.assertEqual(payload["model"], "auto")
        self.assertEqual(payload["client_prepare_state"], "success")
        self.assertEqual(payload["system_hints"], [])
        self.assertEqual(message["content"]["content_type"], "multimodal_text")
        self.assertEqual(
            message["content"]["parts"][0]["asset_pointer"],
            "sediment://file_000000000ac481fd989e0b64e1fe71d6",
        )
        self.assertEqual(message["content"]["parts"][1], "把这张图改成夕阳西下的景象")
        self.assertEqual(message["metadata"]["attachments"][0]["source"], "local")
        self.assertEqual(message["metadata"]["attachments"][0]["id"], "file_000000000ac481fd989e0b64e1fe71d6")
        self.assertEqual(
            message["metadata"]["attachments"][0]["library_file_id"],
            "libfile_d2a9f6445c4c8191a47159432bab5623",
        )
        self.assertEqual(
            message["metadata"]["file_upload_slot_prefetch_attribution"]["reason"],
            "direct_library_multipart_preserved",
        )
        self.assertNotIn("dalle", message["metadata"])
        self.assertNotIn("picture_v2", str(payload))
        self.assertIn("photo_upload_action.v1", str(payload["model_response_contracts"]))

    def test_image_25_edit_excludes_uploaded_file_ids_from_results(self) -> None:
        self.backend._image_input_file_ids = {"file_00000000aaaaaaaaaaaaaaaaaaaaaaaa"}
        file_ids, sediment_ids = self.backend._exclude_input_image_ids(
            ["file_00000000aaaaaaaaaaaaaaaaaaaaaaaa", "file_00000000bbbbbbbbbbbbbbbbbbbbbbbb"],
            ["file_00000000aaaaaaaaaaaaaaaaaaaaaaaa"],
        )
        self.assertEqual(file_ids, ["file_00000000bbbbbbbbbbbbbbbbbbbbbbbb"])
        self.assertEqual(sediment_ids, [])
