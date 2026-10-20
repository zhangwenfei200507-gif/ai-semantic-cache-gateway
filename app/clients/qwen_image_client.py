from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


class QwenImageClient:
    """Native DashScope image generation, separate from chat completions."""

    DEFAULT_MODEL = "qwen-image-3.0"
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

    def __init__(self, api_key: str | None, base_url: str | None = None,
                 model: str | None = None, timeout: float = 180.0) -> None:
        if not api_key:
            raise ValueError("Qwen image API key is not configured")
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _extract_prompt(messages: list[dict[str, Any]]) -> str:
        message = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        content = message.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(p.get("text", "")) for p in content
                                if isinstance(p, dict) and p.get("type") == "text")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Image generation requires a non-empty user prompt")
        return content.strip()

    @property
    def endpoint(self) -> str:
        parts = urlsplit(self.base_url)
        path = parts.path.rstrip("/")
        suffix = "/services/aigc/multimodal-generation/generation"
        if path.endswith(suffix):
            return self.base_url
        # Chat-compatible URLs are not native image API roots.
        for ending in ("/compatible-mode/v1", "/api/v1", "/v1"):
            if path.endswith(ending):
                path = path[:-len(ending)]
                break
        return urlunsplit((parts.scheme, parts.netloc, path + "/api/v1" + suffix, "", ""))

    @staticmethod
    def _extract_image_urls(data: dict[str, Any]) -> list[str]:
        output = data.get("output") or {}
        urls = []
        for choice in output.get("choices") or []:
            for part in (choice.get("message") or {}).get("content") or []:
                if isinstance(part, dict) and part.get("image"):
                    urls.append(part["image"])
        for item in output.get("results") or []:
            if isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])
        return list(dict.fromkeys(url for url in urls
                                  if isinstance(url, str) and url.startswith(("https://", "http://"))))

    @staticmethod
    def _extract_request_id(data: dict[str, Any]) -> str | None:
        return data.get("request_id") or (data.get("output") or {}).get("task_id")

    def generate(self, messages: list[dict[str, Any]], size: str | None = None,
                 n: int = 1, timeout: float | None = None) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": [{"text": self._extract_prompt(messages)}]}]},
            "parameters": {"n": max(1, min(4, int(n)))},
        }
        if size:
            payload["parameters"]["size"] = size
        start = time.perf_counter()
        try:
            response = requests.post(self.endpoint, headers=self.headers, json=payload,
                                     timeout=(10, max(self.timeout, float(timeout or 0))))
        except requests.exceptions.Timeout as exc:
            raise RuntimeError("Qwen image generation timed out; no image was returned") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Qwen image API returned invalid JSON (HTTP {response.status_code})") from exc
        if not response.ok or data.get("code"):
            raise RuntimeError(
                f"Qwen image API failed (HTTP {response.status_code}, "
                f"{data.get('code', 'unknown')}): {data.get('message', 'Request rejected')} "
                f"[request_id={self._extract_request_id(data)}]"
            )
        urls = self._extract_image_urls(data)
        if not urls:
            raise RuntimeError(
                "Qwen image API returned no images "
                f"[request_id={self._extract_request_id(data)}]"
            )
        return {
            "model": self.model, "provider": "qwen_image", "images": urls,
            "request_id": self._extract_request_id(data),
            "latency_ms": round((time.perf_counter() - start) * 1000, 2), "raw": data,
        }


__all__ = ["QwenImageClient"]
