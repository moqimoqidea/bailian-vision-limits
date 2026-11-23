import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from limits.protocols import (  # noqa: E402
    AnthropicCompat,
    ImageAsset,
    OpenAICompat,
    OpenAIResponses,
)
from limits.transport import HttpResult  # noqa: E402
from limits.wire import encode, image_payload, text_payload  # noqa: E402

PNG = ImageAsset("image/png", b"\x89PNG\r\n\x1a\nfake")


class OpenAIPayloadTests(unittest.TestCase):
    def setUp(self):
        self.protocol = OpenAICompat()

    def test_plain_text_uses_string_content(self):
        payload = self.protocol.body("m", "hi", [], 8)
        self.assertEqual(payload["messages"][0]["content"], "hi")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["enable_thinking"])

    def test_image_uses_data_uri_part(self):
        payload = self.protocol.body("m", "hi", [PNG], 8)
        parts = payload["messages"][0]["content"]
        self.assertEqual(parts[0]["type"], "text")
        self.assertEqual(parts[1]["type"], "image_url")
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_usage_and_reply(self):
        body = {
            "choices": [{"message": {"content": "blue"}}],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 8},
            },
        }
        usage = self.protocol.usage(body)
        self.assertEqual(usage["input_tokens"], 12, "prompt_tokens 已是总输入")
        self.assertEqual(usage["output_tokens"], 3)
        self.assertEqual(usage["cache_read_tokens"], 8)
        self.assertEqual(usage["uncached_input_tokens"], 4)
        self.assertEqual(self.protocol.reply(body), "blue")


class AnthropicPayloadTests(unittest.TestCase):
    def setUp(self):
        self.protocol = AnthropicCompat()

    def test_image_uses_base64_source(self):
        payload = self.protocol.body("m", "hi", [PNG], 8)
        parts = payload["messages"][0]["content"]
        self.assertEqual(parts[1]["type"], "image")
        self.assertEqual(parts[1]["source"]["media_type"], "image/png")
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_usage_and_reply_ignore_thinking_blocks(self):
        body = {
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "blue"},
            ],
            "usage": {"input_tokens": 9, "output_tokens": 2},
        }
        usage = self.protocol.usage(body)
        self.assertEqual(usage["input_tokens"], 9)
        self.assertEqual(usage["output_tokens"], 2)
        self.assertEqual(self.protocol.reply(body), "blue")

    def test_usage_sums_cache_fields(self):
        """回归用例：input_tokens 只是非缓存部分，必须加上缓存读写才是总输入。"""
        body = {
            "usage": {
                "input_tokens": 103,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 232_960,
                "output_tokens": 9,
            }
        }
        usage = self.protocol.usage(body)
        self.assertEqual(usage["input_tokens"], 233_063)
        self.assertEqual(usage["uncached_input_tokens"], 103)
        self.assertEqual(usage["cache_read_tokens"], 232_960)


class ResponsesPayloadTests(unittest.TestCase):
    def setUp(self):
        self.protocol = OpenAIResponses()

    def test_text_uses_plain_input(self):
        payload = self.protocol.body("m", "hi", [], 8)
        self.assertEqual(payload["input"], "hi")
        self.assertEqual(payload["max_output_tokens"], 16, "该路径要求 ≥16，应被钳制")
        self.assertNotIn("messages", payload)
        self.assertFalse(payload["stream"])

    def test_chat_does_not_clamp(self):
        payload = OpenAICompat().body("m", "hi", [], 8)
        self.assertEqual(payload["max_tokens"], 8)

    def test_image_uses_input_image_parts(self):
        payload = self.protocol.body("m", "hi", [PNG], 8)
        parts = payload["input"][0]["content"]
        self.assertEqual(parts[0]["type"], "input_text")
        self.assertEqual(parts[1]["type"], "input_image")
        self.assertTrue(parts[1]["image_url"].startswith("data:image/png;base64,"))

    def test_usage_reports_total_with_cached_subset(self):
        body = {
            "usage": {
                "input_tokens": 233_063,
                "input_tokens_details": {"cached_tokens": 232_960},
                "output_tokens": 9,
            }
        }
        usage = self.protocol.usage(body)
        self.assertEqual(usage["input_tokens"], 233_063)
        self.assertEqual(usage["cache_read_tokens"], 232_960)
        self.assertEqual(usage["uncached_input_tokens"], 103)

    def test_reply_skips_reasoning_items(self):
        body = {
            "output": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "思考"}]},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "蓝色"}],
                },
            ]
        }
        self.assertEqual(self.protocol.reply(body), "蓝色")


class ErrorEnvelopeTests(unittest.TestCase):
    def test_openai_style(self):
        result = HttpResult(
            status=400,
            elapsed_s=0,
            payload={"error": {"code": "InvalidParameter", "type": "invalid_request_error", "message": "bad"}},
        )
        self.assertEqual(result.error_fields(), ("InvalidParameter", "invalid_request_error", "bad"))

    def test_dashscope_style(self):
        result = HttpResult(
            status=400, elapsed_s=0, payload={"code": "Throttling", "message": "slow down"}
        )
        self.assertEqual(result.error_fields()[0], "Throttling")

    def test_plain_text_fallback(self):
        result = HttpResult(status=413, elapsed_s=0, text="Request Entity Too Large")
        self.assertIn("413", str(result.status))
        self.assertIn("Too Large", result.error_fields()[2])

    def test_timeout_in_400_is_transient(self):
        """400 也可能是抖动：下载超时不应被当作容量限制。"""
        result = HttpResult(
            status=400,
            elapsed_s=80,
            payload={"code": "InvalidParameter", "message": "Download multimodal file timed out"},
        )
        self.assertEqual(result.kind, "transient")

    def test_capacity_rejection_stays_rejected(self):
        result = HttpResult(
            status=400,
            elapsed_s=0,
            payload={"code": "InvalidParameter", "message": "Range of input length should be [1, 991808]"},
        )
        self.assertEqual(result.kind, "rejected")


class WireTests(unittest.TestCase):
    def test_chinese_not_ascii_escaped(self):
        body = encode({"text": "你好"})
        self.assertIn("你好".encode("utf-8"), body)
        self.assertEqual(len(body), len('{"text":"你好"}'.encode("utf-8")))

    def test_metrics(self):
        built = image_payload(OpenAICompat(), "m", "hi", [PNG, PNG], 8)
        self.assertEqual(built.meta["image_count"], 2)
        self.assertEqual(built.meta["raw_asset_bytes"], len(PNG.raw) * 2)
        self.assertEqual(built.meta["base64_chars"], len(PNG.b64) * 2)

    def test_text_metrics(self):
        built = text_payload(OpenAICompat(), "m", "你好", 8)
        self.assertEqual(built.meta["image_count"], 0)
        self.assertEqual(built.meta["text_chars"], 2)
        self.assertGreater(len(built.body), 0)


if __name__ == "__main__":
    unittest.main()
