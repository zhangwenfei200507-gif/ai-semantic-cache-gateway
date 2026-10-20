from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from app.clients.qwen_image_client import QwenImageClient
from app.gateway import AIGateway
from app.providers.qwen_image_provider import QwenImageProvider
from app.routing.modality_router import ModalityRouter
from app.routing.model_router import ModelRouter
from app.routing.capability_registry import CapabilityRegistry
from test_model_routing import FakeEmbeddingService


def messages(text):
    return [{"role": "user", "content": text}]


class ImageGenerationTests(unittest.TestCase):
    def setUp(self):
        self.client = QwenImageClient("test-only-key")
        self.data = {
            "request_id": "image-test",
            "output": {"choices": [{"message": {"content": [
                {"image": "https://example.test/image.png", "type": "image"}
            ]}}]},
        }
        self.http = Mock(ok=True, status_code=200)
        self.http.json.return_value = self.data

    def test_sync_response_reaches_unified_contract(self):
        with patch("app.clients.qwen_image_client.requests.post", return_value=self.http) as post:
            response = QwenImageProvider(self.client).chat(messages("Draw a cat image"))
        self.assertEqual(response.images, ["https://example.test/image.png"])
        self.assertEqual(response.to_dict()["images"], response.images)
        self.assertEqual(response.provider, "qwen_image")
        self.assertEqual(post.call_args.kwargs["json"]["input"]["messages"][0]["content"],
                         [{"text": "Draw a cat image"}])
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 180))

    def test_legacy_results_remain_supported(self):
        self.assertEqual(self.client._extract_image_urls(
            {"output": {"results": [{"url": "https://example.test/legacy.png"}]}}),
            ["https://example.test/legacy.png"])

    def test_missing_image_is_error_not_success(self):
        self.http.json.return_value = {"request_id": "empty", "output": {}}
        with patch("app.clients.qwen_image_client.requests.post", return_value=self.http):
            with self.assertRaisesRegex(RuntimeError, "no images"):
                self.client.generate(messages("Generate a cat image"))

    def test_api_error_includes_actionable_details(self):
        self.http.ok = False
        self.http.status_code = 401
        self.http.json.return_value = {"code": "InvalidApiKey", "message": "Invalid key", "request_id": "rejected"}
        with patch("app.clients.qwen_image_client.requests.post", return_value=self.http):
            with self.assertRaisesRegex(RuntimeError, "InvalidApiKey.*Invalid key"):
                self.client.generate(messages("Generate a cat image"))

    def test_timeout_is_not_empty_success(self):
        with patch("app.clients.qwen_image_client.requests.post", side_effect=requests.Timeout):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                self.client.generate(messages("Generate an image"))

    def test_endpoint_normalization(self):
        expected = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        for suffix in ("", "/v1", "/api/v1", "/compatible-mode/v1",
                       "/api/v1/services/aigc/multimodal-generation/generation"):
            with self.subTest(suffix=suffix):
                self.assertEqual(QwenImageClient("test", "https://dashscope.aliyuncs.com" + suffix).endpoint, expected)

    def test_image_intent_variations(self):
        classifier = Mock()
        router = ModalityRouter(classifier_client=classifier)
        for text in ("帮我生成一张小猫的图片", "请生成一张赛博朋克风格的橘猫图片",
                     "画一只猫", "制作一个未来城市的海报", "Generate a watercolor cat image"):
            with self.subTest(text=text):
                self.assertEqual(router.route(messages(text)).modality, "image")
        classifier.classify.assert_not_called()

    def test_explanations_and_negation_not_generation(self):
        for text in ("如何生成图片？", "解释图片生成原理", "不要生成图片，只回答文字",
                     "How to generate an image?", "Redis是什么？"):
            with self.subTest(text=text):
                self.assertFalse(ModalityRouter._looks_like_image_generation(messages(text)))

    def test_prior_turn_does_not_force_new_request_to_image(self):
        conversation = messages("生成一张图片") + [{"role": "assistant", "content": "Done"}] + messages("Redis是什么？")
        self.assertFalse(ModalityRouter._looks_like_image_generation(conversation))
        self.assertEqual(self.client._extract_prompt(
            messages("A cat") + [{"role": "assistant", "content": "Old answer"}]), "A cat")

    def test_auto_and_manual_images_bypass_text_cache(self):
        cache = Mock()
        cache.embedding_service = FakeEmbeddingService()
        gateway = AIGateway(cache=cache)
        gateway.model_router = ModelRouter(embedding_service=cache.embedding_service,
                                          registry=CapabilityRegistry(settings=None))
        gateway._lookup_cache = Mock(return_value={"hit": True, "answer": "Old DeepSeek answer"})
        gateway._save_history = Mock()
        provider = QwenImageProvider(self.client)
        gateway._get_provider = Mock(return_value=provider)
        with patch("app.clients.qwen_image_client.requests.post", return_value=self.http):
            for model in ("auto", "qwen-image-3.0"):
                with self.subTest(model=model):
                    response = gateway.chat(messages("帮我生成一张小猫的图片"), model=model)
                    self.assertEqual(response.llm.provider, "qwen_image")
                    self.assertEqual(len(response.llm.images), 1)
                    self.assertFalse(response.cache_hit)
                    self.assertEqual(response.routing["selected_model"], "qwen-image-3.0")
                    self.assertEqual(response.context.request_id,
                                     gateway._save_history.call_args.args[0]["request_id"])
        gateway._lookup_cache.assert_not_called()
        cache.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
