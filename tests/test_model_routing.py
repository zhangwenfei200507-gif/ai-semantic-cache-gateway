from __future__ import annotations

import hashlib
import unittest
from unittest.mock import Mock

from app.routing.capability_registry import CapabilityRegistry
from app.routing.model_router import ModelRouter
from app.routing.modality_router import ModalityRouter


class FakeEmbeddingService:
    def encode(self, text: str) -> list[float]:
        vector = [0.0] * 64

        tokens = []
        lowered = text.lower()

        current = []
        for char in lowered:
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                current.append(char)
                continue

            if current:
                tokens.append("".join(current))
                current = []

        if current:
            tokens.append("".join(current))

        for token in tokens:
            digest = hashlib.sha256(
                token.encode("utf-8")
            ).digest()
            index = digest[0] % len(vector)
            vector[index] += 1.0

        if not any(vector):
            vector[0] = 1.0

        return vector


class ModelRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = ModelRouter(
            embedding_service=FakeEmbeddingService(),
            registry=CapabilityRegistry(settings=None),
        )
        self.router.modality_router = ModalityRouter(classifier_client=Mock(
            classify=Mock(return_value={"modality": "text", "confidence": 1.0})
        ))

    def route(self, content: str):
        return self.router.route(
            [
                {
                    "role": "user",
                    "content": content,
                }
            ]
        )

    def test_routes_core_benchmark_questions(self) -> None:
        cases = [
            (
                "中国新能源汽车未来几年的海外竞争力怎么样？",
                "deepseek",
            ),
            (
                "Redis是什么？",
                "deepseek",
            ),
            (
                "请分析下面这个 Python 多线程程序中的竞态条件，找出导致数据不一致的原因，并比较三种修复架构，说明它们的性能、复杂度和可维护性。```python\nimport threading\ncounter = 0\n```",
                "openai",
            ),
            (
                "设计一个高并发 Python API 服务，要求同时考虑线程安全、Redis 缓存、数据库连接池、限流、故障恢复和水平扩展。",
                "openai",
            ),
            (
                "分析中国消费者为什么越来越重视新能源汽车的智能驾驶和车机体验。",
                "deepseek",
            ),
            (
                "HTTP和HTTPS有什么区别？",
                "deepseek",
            ),
            (
                "请设计一个支持百万级并发的分布式任务队列，并详细分析一致性、重试、幂等性、消息丢失和故障转移方案。",
                "openai",
            ),
            (
                "中国的长江有多长？",
                "deepseek",
            ),
            (
                "比较两种 SaaS 商业模式，从客户获取成本、留存、现金流、扩张速度和长期利润率五个方面进行分析。",
                "openai",
            ),
            (
                "请分析 PostgreSQL 在高并发事务环境下的锁竞争问题，并设计索引、事务隔离和连接池优化方案。",
                "openai",
            ),
        ]

        for content, expected_provider in cases:
            with self.subTest(content=content):
                decision = self.route(content)
                self.assertEqual(
                    decision.provider,
                    expected_provider,
                )

    def test_routes_additional_question_types(self) -> None:
        cases = [
            (
                "帮我用中文解释一下什么是语义缓存。",
                "deepseek",
            ),
            (
                "国内 AI 应用公司未来两年的商业化机会在哪里？",
                "deepseek",
            ),
            (
                "写一个 Python 装饰器并解释它如何处理异常和重试。",
                "openai",
            ),
            (
                "推导一下为什么二叉搜索树中序遍历是有序的。",
                "openai",
            ),
            (
                "Give me a short definition of TLS.",
                "deepseek",
            ),
            (
                "Compare Kafka and Redis Streams for an event-driven payment system, including durability, ordering, replay, and failure recovery.",
                "openai",
            ),
            (
                "设计一个多租户 SaaS 的权限模型，要考虑 RBAC、审计、数据隔离和扩展性。",
                "openai",
            ),
            (
                "分析一家 B2B SaaS 公司从 PLG 转向销售驱动的风险和收益。",
                "openai",
            ),
        ]

        for content, expected_provider in cases:
            with self.subTest(content=content):
                decision = self.route(content)
                self.assertEqual(
                    decision.provider,
                    expected_provider,
                )

    def test_manual_route_keeps_requested_model_first(self) -> None:
        decision = self.router.route_manual(
            "gpt-5-nano",
            [
                {
                    "role": "user",
                    "content": "Redis是什么？",
                }
            ],
        )

        self.assertEqual(
            decision.mode,
            "manual",
        )
        self.assertEqual(
            decision.provider,
            "openai",
        )
        self.assertEqual(
            decision.candidates[0].provider,
            "openai",
        )
        self.assertEqual(
            decision.fallback_candidates[0].provider,
            "deepseek",
        )


if __name__ == "__main__":
    unittest.main()
