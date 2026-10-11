"""LLM JSON 层单测：extract_json 围栏剥离 + chat_json 解析/降级（mock 后端，无网络）。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.llm import extract_json, llm_client


class TestExtractJson(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_code_fence(self):
        raw = '```json\n{"rewritten": "卧推目标肌群"}\n```'
        self.assertEqual(extract_json(raw), {"rewritten": "卧推目标肌群"})

    def test_fence_without_language_tag(self):
        raw = '```\n{"a": true}\n```'
        self.assertEqual(extract_json(raw), {"a": True})

    def test_prose_wrapped(self):
        raw = '好的，结果是 {"x": 2} 请查收'
        self.assertEqual(extract_json(raw), {"x": 2})

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            extract_json("这里没有 JSON")


class TestChatJson(unittest.TestCase):
    def test_parses_valid_response(self):
        with mock.patch.object(llm_client, "chat_fast", return_value='{"rewritten": "问句"}'):
            out = llm_client.chat_json([{"role": "user", "content": "x"}])
        self.assertEqual(out, {"rewritten": "问句"})

    def test_parses_fenced_response(self):
        with mock.patch.object(llm_client, "chat_fast", return_value='```json\n{"scores": [5]}\n```'):
            out = llm_client.chat_json([{"role": "user", "content": "x"}])
        self.assertEqual(out, {"scores": [5]})

    def test_invalid_json_raises_to_caller(self):
        # 解析失败向上抛——降级策略由调用方决定（如 quizgen 低温重试、quality 兜底 3.5）
        with mock.patch.object(llm_client, "chat_fast", return_value="模型胡言乱语"):
            with self.assertRaises(ValueError):
                llm_client.chat_json([{"role": "user", "content": "x"}])

    def test_gen_model_routed_to_chat_gen(self):
        with mock.patch.object(llm_client, "chat_gen", return_value='{"stem": "题干"}') as cg, \
             mock.patch.object(llm_client, "chat_fast") as cf:
            out = llm_client.chat_json([{"role": "user", "content": "x"}], model_tier="gen")
        self.assertEqual(out, {"stem": "题干"})
        cg.assert_called_once()
        cf.assert_not_called()

    def test_kwargs_forwarded(self):
        with mock.patch.object(llm_client, "chat_fast", return_value='{"ok": 1}') as cf:
            llm_client.chat_json([{"role": "user", "content": "x"}],
                          temperature=0.7, max_tokens=99)
        self.assertEqual(cf.call_args.kwargs["temperature"], 0.7)
        self.assertEqual(cf.call_args.kwargs["max_tokens"], 99)


if __name__ == "__main__":
    unittest.main()
