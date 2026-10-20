from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROVIDERS_FILE = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "providers.json"
)


class CustomProviderConfig:
    """Load user-defined OpenAI-compatible provider/model settings."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path:
            self.path = Path(path)
        else:
            try:
                from app.config.settings import settings
                configured = getattr(settings, "custom_providers_file", "")
                self.path = Path(configured) if configured else DEFAULT_PROVIDERS_FILE
            except Exception:
                self.path = DEFAULT_PROVIDERS_FILE
        self._providers: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._providers = {}

        if not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(
                f"Invalid provider configuration file: {self.path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError("providers.json must contain a JSON object")

        providers = data.get("providers", [])
        if not isinstance(providers, list):
            raise ValueError("providers must be a list")

        for raw in providers:
            self._register(raw)

    def _register(self, raw: Any) -> None:
        if not isinstance(raw, dict):
            raise ValueError("Each custom provider must be an object")

        name = str(raw.get("name", "")).strip().lower()
        base_url = str(raw.get("base_url", "")).strip()
        api_key_env = str(raw.get("api_key_env", "")).strip()

        if not name:
            raise ValueError("Custom provider name cannot be empty")
        if name in {"deepseek", "openai", "qwen_classifier", "qwen_image", "qwen_document"}:
            raise ValueError(
                f"Custom provider name '{name}' is reserved by the gateway"
            )
        if not base_url:
            raise ValueError(f"Custom provider '{name}' requires base_url")
        if not api_key_env:
            raise ValueError(f"Custom provider '{name}' requires api_key_env")

        models = raw.get("models")
        if models is None:
            single_model = str(raw.get("model", "")).strip()
            models = [single_model] if single_model else []

        if not isinstance(models, list) or not models:
            raise ValueError(
                f"Custom provider '{name}' requires model or models"
            )

        normalized_models: list[dict[str, Any]] = []
        for item in models:
            if isinstance(item, str):
                normalized_models.append({"name": item.strip()})
            elif isinstance(item, dict):
                model_name = str(item.get("name", item.get("model", ""))).strip()
                if not model_name:
                    raise ValueError(
                        f"Custom provider '{name}' contains an empty model"
                    )
                normalized_models.append({**item, "name": model_name})
            else:
                raise ValueError(
                    f"Custom provider '{name}' model entry must be string or object"
                )

        config = {
            **raw,
            "name": name,
            "base_url": base_url.rstrip("/"),
            "api_key_env": api_key_env,
            "models": normalized_models,
            "enabled": bool(raw.get("enabled", True)),
        }
        self._providers[name] = config

    def all(self) -> list[dict[str, Any]]:
        return list(self._providers.values())

    def get(self, provider: str) -> dict[str, Any] | None:
        return self._providers.get(str(provider or "").strip().lower())

    def get_model(self, provider: str, model: str) -> dict[str, Any] | None:
        config = self.get(provider)
        if config is None:
            return None

        normalized = str(model or "").strip().lower()
        for item in config["models"]:
            if str(item["name"]).strip().lower() == normalized:
                return item
        return None

    def upsert(self, config: dict[str, Any]) -> dict[str, Any]:
        """Persist one non-secret custom provider configuration."""
        self._register(config)
        current = list(self._providers.values())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"providers": current}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        self.reload()
        return self.get(str(config.get("name", ""))) or {}

    def remove(self, provider: str) -> bool:
        name = str(provider or "").strip().lower()
        if name not in self._providers:
            return False
        self._providers.pop(name, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"providers": list(self._providers.values())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        self.reload()
        return True


custom_provider_config = CustomProviderConfig()


__all__ = [
    "CustomProviderConfig",
    "custom_provider_config",
    "DEFAULT_PROVIDERS_FILE",
]
