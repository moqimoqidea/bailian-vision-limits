"""安全边界：主机校验、重定向、脱敏与脚本注入。"""

from __future__ import annotations

import os
import unittest

from limits.config import Settings
from limits.curlgen import _EXPERIMENT_ID, _safe_text
from limits.redact import redact
from limits.transport import Transport, _NoRedirect


class SettingsValidationTests(unittest.TestCase):
    def test_rejects_host_injection(self):
        for bad in ("evil.com/x", "a@b", "a:b", "../etc", "", ".hidden"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                Settings(workspace_id=bad, api_key="k")

    def test_rejects_bad_region(self):
        with self.assertRaises(SystemExit):
            Settings(workspace_id="ws1", api_key="k", region="cn-beijing/../x")
        with self.assertRaises(SystemExit):
            Settings(workspace_id="ws1", api_key="k", region="cn_beijing")

    def test_accepts_normal_values(self):
        settings = Settings(workspace_id="ws-demo", api_key="k")
        self.assertEqual(settings.region, "cn-beijing")
        self.assertTrue(settings.host.startswith("https://ws-demo.cn-beijing."))
        self.assertTrue(settings.host.endswith(".maas.aliyuncs.com"))


class TransportGuardTests(unittest.TestCase):
    def test_rejects_non_https(self):
        with self.assertRaises(SystemExit):
            Transport("http://ws1.cn-beijing.maas.aliyuncs.com")

    def test_rejects_foreign_host(self):
        with self.assertRaises(SystemExit):
            Transport("https://evil.example.com")

    def test_accepts_workspace_host(self):
        transport = Transport("https://ws1.cn-beijing.maas.aliyuncs.com")
        self.assertIsNotNone(transport)

    def test_redirects_are_not_followed(self):
        handler = _NoRedirect()
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com")
        )


class RedactionTests(unittest.TestCase):
    def test_masks_exact_env_key(self):
        os.environ["DASHSCOPE_API_KEY"] = "sk-test-DUMMY0001"
        try:
            self.assertEqual(redact("echo sk-test-DUMMY0001"), "echo ***")
        finally:
            os.environ.pop("DASHSCOPE_API_KEY", None)

    def test_masks_common_header_forms(self):
        for text in (
            "Authorization: Bearer abcdef123456",
            "x-api-key: sk-abcdef123456",
            "prefix sk-abcdef123456 suffix",
        ):
            with self.subTest(text=text):
                self.assertNotIn("abcdef123456", redact(text))

    def test_keeps_plain_text(self):
        self.assertEqual(redact("Range of input length should be [1, 991808]"),
                         "Range of input length should be [1, 991808]")


class ScriptInjectionTests(unittest.TestCase):
    def test_newlines_are_flattened(self):
        self.assertEqual(_safe_text("a\nrm -rf /\nb"), "a rm -rf / b")
        self.assertEqual(_safe_text("a\r\nb"), "a b")

    def test_shell_metacharacters_do_not_break_id_validation(self):
        for bad in ("a'; rm -rf /", "a\nb", "a b", "../x", ""):
            with self.subTest(bad=bad):
                self.assertIsNone(_EXPERIMENT_ID.fullmatch(bad))

    def test_normal_ids_pass(self):
        for good in ("text_en_openai", "trunc_3_5_responses", "fmt_min_9px_anthropic"):
            with self.subTest(good=good):
                self.assertIsNotNone(_EXPERIMENT_ID.fullmatch(good))


if __name__ == "__main__":
    unittest.main()
