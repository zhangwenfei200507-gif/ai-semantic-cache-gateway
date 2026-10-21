from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from app.config.settings import settings
from app.db.postgres import get_postgres_connection
from app.routing.capability_registry import ModelCapability, CapabilityRegistry
from app.security.credentials import CredentialCipher
from app.security.guards import validate_provider_base_url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_name(value: str) -> str:
    name = str(value or "").strip().lower()
    return {"qwen_image": "qwen", "qwen_classifier": "qwen"}.get(name, name)


def _model_config(item: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, str):
        return {"model_id": item.strip()}
    model_id = str(item.get("model_id", item.get("name", item.get("model", "")))).strip()
    return {**item, "model_id": model_id}


def _runtime_provider(provider: str, model: dict[str, Any]) -> str:
    explicit = str(model.get("runtime_provider", "")).strip().lower()
    if explicit in {"qwen_image", "qwen_classifier"}:
        return explicit
    role = str(model.get("role", model.get("routing_role", ""))).strip().lower()
    modality = str(model.get("modality", "text")).strip().lower()
    if provider == "qwen" and modality == "image":
        return "qwen_image"
    if provider == "qwen" and role in {"classifier", "router"}:
        return "qwen_classifier"
    return provider


def _capability(spec: dict[str, Any]) -> ModelCapability:
    metadata = spec.get("metadata") or {}
    descriptions = metadata.get("capability_descriptions") or {
        "general": "general assistance and everyday questions",
        "reasoning": "logical reasoning and multi-step problem solving",
        "coding": "programming, software engineering and APIs",
        "analysis": "analysis, comparison, evaluation and strategy",
    }
    role = str(metadata.get("routing_role", "balanced")).lower()
    if role not in {"economy", "quality", "balanced"}:
        role = "quality" if spec.get("modality") == "image" else "balanced"
    return ModelCapability(
        provider=str(spec["runtime_provider"]),
        model=str(spec["model"]),
        reasoning_strength=float(metadata.get("reasoning_strength", 0.80)),
        coding_strength=float(metadata.get("coding_strength", 0.80)),
        analysis_strength=float(metadata.get("analysis_strength", 0.80)),
        factual_strength=float(metadata.get("factual_strength", 0.80)),
        creative_strength=float(metadata.get("creative_strength", 0.80)),
        data_strength=float(metadata.get("data_strength", 0.80)),
        chinese_strength=float(metadata.get("chinese_strength", 0.90)),
        multilingual_strength=float(metadata.get("multilingual_strength", 0.85)),
        long_context_strength=float(metadata.get("long_context_strength", 0.80)),
        text_capable=str(spec.get("modality", "text")) == "text",
        image_capable=str(spec.get("modality", "text")) == "image",
        capability_descriptions={str(k): str(v) for k, v in descriptions.items()},
        max_output_tokens=max(1, int(metadata.get("max_output_tokens", 8192))),
        enabled=bool(spec.get("enabled", True)),
        routing_role=role,
    )


class WorkspaceProviderStore:
    """Workspace-scoped provider metadata and encrypted credentials."""

    def __init__(self, workspace_id: int | str) -> None:
        if not settings.database_url:
            raise RuntimeError("Workspace Provider storage requires PostgreSQL")
        self.workspace_id = int(workspace_id)

    @staticmethod
    def _credential(conn, provider_id: int, model_id: int | None = None) -> dict[str, Any] | None:
        if model_id is None:
            row = conn.execute(
                "SELECT * FROM provider_credentials WHERE provider_id = ? AND provider_model_id IS NULL",
                (provider_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM provider_credentials WHERE provider_id = ? AND provider_model_id = ?",
                (provider_id, model_id),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _safe_model(row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata") or {}
        return {
            "model": row["model_id"],
            "model_id": row["model_id"],
            "modality": row.get("modality") or "text",
            "enabled": bool(row.get("enabled", True)),
            "context_window": row.get("context_window"),
            "supports_streaming": bool(row.get("supports_streaming", False)),
            "input_price_per_million": row.get("input_price_per_million"),
            "output_price_per_million": row.get("output_price_per_million"),
            "image_price": row.get("image_price"),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }

    def list(self) -> list[dict[str, Any]]:
        with get_postgres_connection() as conn:
            providers = conn.execute(
                "SELECT * FROM providers WHERE workspace_id = ? ORDER BY id",
                (self.workspace_id,),
            ).fetchall()
            result = []
            for raw in providers:
                provider = dict(raw)
                models = conn.execute(
                    "SELECT * FROM provider_models WHERE provider_id = ? ORDER BY id",
                    (provider["id"],),
                ).fetchall()
                safe_models = []
                credentials = []
                for model_row in models:
                    model = self._safe_model(dict(model_row))
                    model_credential = self._credential(conn, provider["id"], model_row["id"])
                    provider_credential = self._credential(conn, provider["id"])
                    credential = model_credential or provider_credential
                    model["credential_configured"] = bool(credential and credential.get("encrypted_api_key"))
                    model["credential_verified"] = bool(
                        credential
                        and credential.get("encrypted_api_key")
                        and credential.get("verified_at")
                    )
                    model["verified_at"] = credential.get("verified_at") if credential else None
                    safe_models.append(model)
                    if credential:
                        credentials.append(credential)
                provider_credential = self._credential(conn, provider["id"])
                has_credential = bool(provider_credential and provider_credential.get("encrypted_api_key")) or any(
                    item["credential_configured"] for item in safe_models
                )
                verified_credentials = [
                    item for item in credentials
                    if item.get("encrypted_api_key") and item.get("verified_at")
                ]
                result.append({
                    "id": provider["id"],
                    "name": provider["name"],
                    "display_name": provider["display_name"],
                    "provider_type": provider["provider_type"],
                    "base_url": provider["base_url"],
                    "role": provider["role"],
                    "status": "configured" if has_credential else "not_configured",
                    "configured": has_credential,
                    "verified": bool(verified_credentials),
                    "verified_at": max(
                        (item.get("verified_at") for item in verified_credentials),
                        default=None,
                    ),
                    "enabled": bool(provider["enabled"]),
                    "default_model": provider.get("default_model"),
                    "models": safe_models,
                    "model_names": [item["model_id"] for item in safe_models],
                    "credential_mask": "configured" if has_credential else None,
                })
            return result

    def _upsert_model(self, conn, provider_id: int, config: dict[str, Any]) -> dict[str, Any]:
        model_id = str(config.get("model_id", "")).strip()
        if not model_id:
            raise ValueError("Model ID cannot be empty")
        modality = str(config.get("modality", "text")).strip().lower()
        if modality not in {"text", "image"}:
            raise ValueError("Model modality must be text or image")
        metadata = {
            key: value
            for key, value in config.items()
            if key not in {
                "model_id", "name", "model", "modality", "context_window",
                "supports_streaming", "input_price_per_million",
                "output_price_per_million", "image_price", "api_key",
            }
        }
        existing = conn.execute(
            "SELECT id FROM provider_models WHERE provider_id = ? AND model_id = ?",
            (provider_id, model_id),
        ).fetchone()
        values = (
            modality,
            config.get("context_window"),
            bool(config.get("supports_streaming", False)),
            config.get("input_price_per_million"),
            config.get("output_price_per_million"),
            config.get("image_price"),
            bool(config.get("enabled", True)),
            Jsonb(metadata),
        )
        if existing:
            conn.execute(
                """
                UPDATE provider_models
                SET modality = ?, context_window = ?, supports_streaming = ?,
                    input_price_per_million = ?, output_price_per_million = ?,
                    image_price = ?, enabled = ?, metadata = ?
                WHERE id = ?
                """,
                (*values, existing["id"]),
            )
            model_db_id = int(existing["id"])
        else:
            row = conn.execute(
                """
                INSERT INTO provider_models
                (provider_id, model_id, modality, context_window, supports_streaming,
                 input_price_per_million, output_price_per_million, image_price,
                 enabled, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (provider_id, model_id, *values),
            ).fetchone()
            model_db_id = int(row["id"])
        if "api_key" in config and config.get("api_key") is not None:
            self._upsert_credential(conn, provider_id, model_db_id, str(config["api_key"]))
        return {"id": model_db_id, "model_id": model_id}

    @staticmethod
    def _upsert_credential(conn, provider_id: int, provider_model_id: int | None, api_key: str) -> None:
        encrypted = CredentialCipher.encrypt(api_key)
        fingerprint = CredentialCipher.fingerprint(api_key)
        if provider_model_id is None:
            existing = conn.execute(
                "SELECT id FROM provider_credentials WHERE provider_id = ? AND provider_model_id IS NULL",
                (provider_id,),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM provider_credentials WHERE provider_id = ? AND provider_model_id = ?",
                (provider_id, provider_model_id),
            ).fetchone()
        values = (encrypted, fingerprint, _now())
        if existing:
            conn.execute(
                "UPDATE provider_credentials SET encrypted_api_key = ?, key_fingerprint = ?, updated_at = ?, verified_at = NULL WHERE id = ?",
                (*values, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO provider_credentials
                (provider_id, provider_model_id, key_version, encrypted_api_key,
                 key_fingerprint, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (provider_id, provider_model_id, "fernet-v1", encrypted, fingerprint, _now(), _now()),
            )

    def upsert(
        self,
        name: str,
        display_name: str | None,
        base_url: str,
        models: list[str | dict[str, Any]],
        api_key: str | None = None,
        role: str = "answer",
        enabled: bool = True,
    ) -> dict[str, Any]:
        provider_name = _provider_name(name)
        if not provider_name:
            raise ValueError("Provider name cannot be empty")
        normalized_base_url = validate_provider_base_url(base_url)
        normalized_models = [_model_config(item) for item in models]
        normalized_models = [item for item in normalized_models if item["model_id"]]
        if not normalized_models:
            raise ValueError("At least one model is required")
        for model in normalized_models:
            model_name = model["model_id"].lower()
            if provider_name == "qwen" and "image" in model_name:
                model.setdefault("modality", "image")
                model.setdefault("runtime_provider", "qwen_image")
                model.setdefault("role", "image")
            elif provider_name == "qwen" and model_name == "qwen3.8-flash":
                model.setdefault("runtime_provider", "qwen_classifier")
                model.setdefault("role", "router")
        with get_postgres_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM providers WHERE workspace_id = ? AND name = ?",
                (self.workspace_id, provider_name),
            ).fetchone()
            values = (
                provider_name,
                display_name or provider_name.title(),
                "openai_compatible",
                normalized_base_url,
                role,
                "configured" if api_key else "not_configured",
                bool(enabled),
                normalized_models[0]["model_id"],
                Jsonb({}),
                _now(),
                _now(),
            )
            if existing:
                provider_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE providers SET display_name = ?, provider_type = ?, base_url = ?,
                        role = ?, enabled = ?, default_model = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ?
                    """,
                    (values[1], values[2], values[3], values[4], values[6], values[7], _now(), provider_id, self.workspace_id),
                )
            else:
                row = conn.execute(
                    """
                    INSERT INTO providers
                    (workspace_id, name, display_name, provider_type, base_url, role,
                     status, enabled, default_model, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (self.workspace_id, *values),
                ).fetchone()
                provider_id = int(row["id"])
            for config in normalized_models:
                model = self._upsert_model(conn, provider_id, config)
                if config.get("api_key") is not None:
                    self._upsert_credential(conn, provider_id, model["id"], str(config["api_key"]))
            if api_key:
                self._upsert_credential(conn, provider_id, None, api_key)
        return next(item for item in self.list() if int(item["id"]) == provider_id)

    def update_models(self, name: str, models: list[str | dict[str, Any]]) -> dict[str, Any]:
        provider_name = _provider_name(name)
        with get_postgres_connection() as conn:
            provider = conn.execute(
                "SELECT id FROM providers WHERE workspace_id = ? AND name = ?",
                (self.workspace_id, provider_name),
            ).fetchone()
            if not provider:
                raise KeyError("Provider not found")
            for config in [_model_config(item) for item in models]:
                if config["model_id"]:
                    self._upsert_model(conn, int(provider["id"]), config)
            first = conn.execute(
                "SELECT model_id FROM provider_models WHERE provider_id = ? ORDER BY id LIMIT 1",
                (provider["id"],),
            ).fetchone()
            conn.execute(
                "UPDATE providers SET default_model = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
                (first["model_id"] if first else None, _now(), provider["id"], self.workspace_id),
            )
        return next(item for item in self.list() if int(item["id"]) == int(provider["id"]))

    def delete(self, name: str) -> bool:
        with get_postgres_connection() as conn:
            result = conn.execute(
                "DELETE FROM providers WHERE workspace_id = ? AND name = ?",
                (self.workspace_id, _provider_name(name)),
            )
            return bool(result.rowcount)

    def delete_credential(self, name: str, model: str | None = None) -> bool:
        with get_postgres_connection() as conn:
            provider = conn.execute(
                "SELECT id FROM providers WHERE workspace_id = ? AND name = ?",
                (self.workspace_id, _provider_name(name)),
            ).fetchone()
            if not provider:
                return False
            if model:
                model_row = conn.execute(
                    "SELECT id FROM provider_models WHERE provider_id = ? AND model_id = ?",
                    (provider["id"], model),
                ).fetchone()
                if not model_row:
                    return False
                result = conn.execute(
                    "DELETE FROM provider_credentials WHERE provider_id = ? AND provider_model_id = ?",
                    (provider["id"], model_row["id"]),
                )
            else:
                result = conn.execute(
                    "DELETE FROM provider_credentials WHERE provider_id = ?",
                    (provider["id"],),
                )
            return bool(result.rowcount)

    def catalog(self) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        with get_postgres_connection() as conn:
            rows = conn.execute(
                """
                SELECT p.*, m.id AS model_db_id, m.model_id, m.modality, m.enabled AS model_enabled,
                       m.context_window, m.supports_streaming, m.input_price_per_million,
                       m.output_price_per_million, m.image_price, m.metadata AS model_metadata
                FROM providers p
                JOIN provider_models m ON m.provider_id = p.id
                WHERE p.workspace_id = ? AND p.enabled = TRUE AND m.enabled = TRUE
                ORDER BY p.id, m.id
                """,
                (self.workspace_id,),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                credential = self._credential(conn, row["id"], row["model_db_id"])
                if credential is None:
                    credential = self._credential(conn, row["id"])
                encrypted = credential.get("encrypted_api_key") if credential else None
                if not encrypted:
                    continue
                spec = {
                    "provider": row["name"],
                    "runtime_provider": _runtime_provider(row["name"], {
                        "modality": row["modality"],
                        **(row.get("model_metadata") or {}),
                    }),
                    "model": row["model_id"],
                    "base_url": (row.get("model_metadata") or {}).get("base_url") or row["base_url"],
                    "modality": row["modality"],
                    "role": row["role"],
                    "enabled": bool(row["model_enabled"]),
                    "metadata": row.get("model_metadata") or {},
                    "api_key": CredentialCipher.decrypt(encrypted),
                }
                if spec["runtime_provider"] == "qwen_classifier":
                    continue
                catalog.append(spec)
        return catalog

    def model_spec(self, provider: str, model: str) -> dict[str, Any] | None:
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip().lower()
        for spec in self.catalog():
            if spec["runtime_provider"].lower() == normalized_provider and spec["model"].lower() == normalized_model:
                return spec
            if spec["provider"].lower() == normalized_provider and spec["model"].lower() == normalized_model:
                return spec
        classifier = self.classifier_spec()
        if classifier and classifier["model"].lower() == normalized_model and normalized_provider in {
            "qwen",
            "qwen_classifier",
        }:
            return classifier
        return None

    def classifier_spec(self) -> dict[str, Any] | None:
        with get_postgres_connection() as conn:
            rows = conn.execute(
                """
                SELECT p.*, m.id AS model_db_id, m.model_id, m.modality, m.metadata AS model_metadata
                FROM providers p JOIN provider_models m ON m.provider_id = p.id
                WHERE p.workspace_id = ? AND p.enabled = TRUE AND m.enabled = TRUE
                """,
                (self.workspace_id,),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                metadata = row.get("model_metadata") or {}
                role = str(metadata.get("role", metadata.get("routing_role", ""))).lower()
                if role not in {"classifier", "router"}:
                    continue
                credential = self._credential(conn, row["id"], row["model_db_id"]) or self._credential(conn, row["id"])
                if not credential or not credential.get("encrypted_api_key"):
                    continue
                return {
                    "provider": "qwen_classifier",
                    "model": row["model_id"],
                    "base_url": metadata.get("base_url") or row["base_url"],
                    "api_key": CredentialCipher.decrypt(credential["encrypted_api_key"]),
                }
        return None

    def mark_verified(self, provider: str, model: str) -> None:
        spec = self.model_spec(provider, model)
        if not spec:
            return
        with get_postgres_connection() as conn:
            row = conn.execute(
                """
                SELECT p.id, m.id AS model_id
                FROM providers p JOIN provider_models m ON m.provider_id = p.id
                WHERE p.workspace_id = ? AND p.name = ? AND m.model_id = ?
                """,
                (self.workspace_id, _provider_name(provider), model),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE provider_credentials SET verified_at = ?, updated_at = ? WHERE provider_id = ? AND (provider_model_id = ? OR provider_model_id IS NULL)",
                    (_now(), _now(), row["id"], row["model_id"]),
                )

    def capabilities(self) -> CapabilityRegistry:
        return CapabilityRegistry(models=[_capability(item) for item in self.catalog()])


__all__ = ["WorkspaceProviderStore"]
