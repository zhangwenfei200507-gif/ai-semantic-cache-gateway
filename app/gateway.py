from __future__ import annotations

import time
import threading
import uuid
import logging
from typing import Any

from app.cache.cache_service import CacheService
from app.config.settings import settings
from app.context.request_context import RequestContext
from app.cost.cost_calculator import cost_calculator
from app.history.repository import history_repository
from app.lifecycle.lifecycle_manager import LifecycleManager

from app.metrics.gateway_metrics import (
    CACHE_EXACT_HIT_TOTAL,
    CACHE_HIT_TOTAL,
    CACHE_MISS_TOTAL,
    CACHE_SEMANTIC_HIT_TOTAL,
    GATEWAY_ERROR_TOTAL,
    GATEWAY_REQUEST_TOTAL,
    PROVIDER_ERROR_TOTAL,
    PROVIDER_LATENCY_SECONDS,
    PROVIDER_REQUEST_TOTAL,
    REQUEST_LATENCY_SECONDS,
)

from app.providers.factory import ProviderFactory

from app.routing.model_router import ModelRouter
from app.routing.modality_router import ModalityRouter

from app.schemas.gateway_response import GatewayResponse
from app.schemas.llm_response import LLMResponse


logger = logging.getLogger(__name__)


class AIGateway:
    """
    Main AI gateway.

    Request flow:

        Client
            |
            v
        AIGateway
            |
            +--> Semantic / Exact Cache
            |       |
            |       +--> HIT  -> return cached answer
            |       |
            |       +--> MISS
            |
            v
        ModelRouter
            |
            +--> qwen_classifier
            |       |
            |       +--> classify request type
            |
            v
        Candidate Models
            |
            +--> qwen_image
            +--> deepseek
            +--> openai
            |
            v
        Provider
            |
            v
        Cache
            |
            v
        History / Metrics

    Important project rule:

        There is NO dedicated document provider.

    Documents are classified as request/input content and are
    handled by the normal routing system. This gateway does not
    create or call qwen_document.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        cache: CacheService | None = None,
        lifecycle_manager: LifecycleManager | None = None,
    ) -> None:

        # ========================================================
        # Default provider
        # ========================================================

        self.provider_name = (
            provider
            or settings.default_provider
            or ""
        ).strip().lower()

        if not self.provider_name:
            raise ValueError(
                "Provider cannot be empty"
            )

        # ========================================================
        # Default model
        # ========================================================

        configured_model = (
            model
            if model is not None
            else settings.default_model
        )

        self.model_name = (
            configured_model.strip()
            if isinstance(
                configured_model,
                str,
            )
            else ""
        )

        if not self.model_name:
            raise ValueError(
                "Model cannot be empty"
            )

        self.configured_model_name = (
            self.model_name
        )

        # ========================================================
        # Cache
        # ========================================================

        self.cache = (
            cache
            or CacheService(
                similarity_threshold=(
                    settings.cache_threshold
                )
            )
        )

        # ========================================================
        # Model Router
        #
        # IMPORTANT:
        #
        # ModelRouter uses the SAME embedding service owned by
        # CacheService.
        #
        # This prevents creating duplicate embedding models.
        # ========================================================

        self.model_router = ModelRouter(
            embedding_service=(
                self.cache.embedding_service
            )
        )

        # ========================================================
        # Lifecycle
        # ========================================================

        self.lifecycle_manager = (
            lifecycle_manager
            or LifecycleManager()
        )

        # ========================================================
        # Provider instance cache
        #
        # key:
        #
        #     (provider, model)
        #
        # This prevents recreating provider clients for every
        # request.
        # ========================================================

        self._providers: dict[
            tuple[str, str],
            Any,
        ] = {}

        # ========================================================
        # Preserve default-provider compatibility
        #
        # Some existing code may access:
        #
        #     gateway.provider
        #
        # Therefore keep this property.
        #
        # Provider initialization failure should NOT prevent the
        # gateway itself from starting.
        # ========================================================

        try:

            self.provider = (
                self._get_provider(
                    self.provider_name,
                    self.model_name,
                )
            )

        except Exception:

            self.provider = None

    # ============================================================
    # Validation
    # ============================================================

    @staticmethod
    def _validate_messages(
        messages: list[dict],
    ) -> None:
        """
        Validate OpenAI-compatible messages.
        """

        if not isinstance(
            messages,
            list,
        ):
            raise ValueError(
                "messages must be list"
            )

        if not messages:
            raise ValueError(
                "messages empty"
            )

        for index, message in enumerate(
            messages
        ):

            if not isinstance(
                message,
                dict,
            ):
                raise ValueError(
                    f"messages[{index}] must be object"
                )

            if "role" not in message:
                raise ValueError(
                    f"messages[{index}] missing role"
                )

            if "content" not in message:
                raise ValueError(
                    f"messages[{index}] missing content"
                )

    # ============================================================
    # Provider resolution
    # ============================================================

    def _provider_for_model(
        self,
        model: str,
    ) -> str:
        """
        Resolve provider from a concrete model name.

        This method intentionally supports only the providers that
        belong to the current project architecture.

        qwen_document is NOT supported.
        """

        normalized_model = (
            str(model or "")
            .strip()
        )

        if not normalized_model:
            raise ValueError(
                "Model cannot be empty"
            )

        # --------------------------------------------------------
        # DeepSeek
        # --------------------------------------------------------

        if normalized_model == str(
            settings.deepseek_model or ""
        ).strip():

            if not settings.is_deepseek_configured():

                raise ValueError(
                    "DeepSeek is not configured"
                )

            return "deepseek"

        # --------------------------------------------------------
        # OpenAI
        # --------------------------------------------------------

        if normalized_model == str(
            settings.openai_model or ""
        ).strip():

            if not settings.is_openai_configured():

                raise ValueError(
                    "OpenAI is not configured"
                )

            return "openai"

        # --------------------------------------------------------
        # Qwen Classifier
        # --------------------------------------------------------

        if normalized_model == str(
            settings.qwen_classifier_model or ""
        ).strip():

            if not settings.is_qwen_classifier_configured():

                raise ValueError(
                    "Qwen Classifier is not configured"
                )

            return "qwen_classifier"

        # --------------------------------------------------------
        # Qwen Image
        # --------------------------------------------------------

        if normalized_model in {
            item.strip()
            for item in settings.model_names("qwen_image")
        }:

            if not settings.is_qwen_image_configured():

                raise ValueError(
                    "Qwen Image is not configured"
                )

            return "qwen_image"

        # --------------------------------------------------------
        # Explicit document rejection
        # --------------------------------------------------------

        if (
            "document" in normalized_model.lower()
            or
            normalized_model.lower()
            == "qwen_document"
        ):

            raise ValueError(
                "Dedicated document models are not supported"
            )

        # --------------------------------------------------------
        # Unknown model
        # --------------------------------------------------------

        raise ValueError(
            f"Unsupported model {normalized_model}"
        )

    # ============================================================
    # Provider instance
    # ============================================================

    def _get_provider(
        self,
        provider: str,
        model: str,
        workspace_id: str | None = None,
    ):
        """
        Create or reuse provider instance.
        """

        normalized_provider = (
            str(provider or "")
            .strip()
            .lower()
        )

        normalized_model = (
            str(model or "")
            .strip()
        )

        if not normalized_provider:
            raise ValueError(
                "Provider cannot be empty"
            )

        if not normalized_model:
            raise ValueError(
                "Model cannot be empty"
            )

        if workspace_id:
            return ProviderFactory.create_for_workspace(
                provider=normalized_provider,
                model=normalized_model,
                workspace_id=workspace_id,
            )

        key = (
            normalized_provider,
            normalized_model,
        )

        # --------------------------------------------------------
        # Reuse existing instance
        # --------------------------------------------------------

        if key in self._providers:

            return self._providers[key]

        # --------------------------------------------------------
        # Create provider
        #
        # ProviderFactory itself is responsible for:
        #
        #   deepseek
        #   openai
        #   qwen_classifier
        #   qwen_image
        #
        # and explicitly rejects:
        #
        #   qwen_document
        # --------------------------------------------------------

        instance = ProviderFactory.create(
            provider=normalized_provider,
            model=normalized_model,
        )

        self._providers[key] = instance

        return instance

    # ============================================================
    # Cache lookup
    # ============================================================

    def _lookup_cache(
        self,
        messages,
        workspace_id: str | None = None,
        cache_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Lookup exact / semantic cache.

        Preferred path:

            cache.lookup()

        Compatibility fallback:

            get_exact()
            get_semantic()
        """

        lookup = getattr(
            self.cache,
            "lookup",
            None,
        )

        # --------------------------------------------------------
        # New cache API
        # --------------------------------------------------------

        if callable(lookup):

            result = lookup(
                messages,
                workspace_id=workspace_id,
                cache_context=cache_context,
            )

            if isinstance(
                result,
                dict,
            ):

                return result

        # --------------------------------------------------------
        # Exact cache
        # --------------------------------------------------------

        exact = self.cache.get_exact(
            messages,
            workspace_id=workspace_id,
            cache_context=cache_context,
        )

        if exact is not None:

            return {
                "hit": True,
                "type": "exact",
                "answer": exact,
                "similarity": 1.0,
            }

        # --------------------------------------------------------
        # Semantic cache
        # --------------------------------------------------------

        semantic = self.cache.get_semantic(
            messages,
            workspace_id=workspace_id,
            cache_context=cache_context,
        )

        if semantic:

            return {
                "hit": True,
                "type": "semantic",
                **semantic,
            }

        # --------------------------------------------------------
        # Miss
        # --------------------------------------------------------

        return {
            "hit": False,
        }

    # ============================================================
    # History
    # ============================================================

    def _save_history(
        self,
        data: dict[str, Any],
        workspace_id: str | None = None,
    ) -> None:
        """
        History persistence must never break the gateway request.
        """

        try:

            record = dict(data)
            if workspace_id is not None:
                record["workspace_id"] = int(workspace_id)
            history_repository.save(record)

        except Exception:
            logger.warning("History save failed")

    @staticmethod
    def _persist_images(
        response: LLMResponse,
        *,
        workspace_id: str | None,
        user_id: str | None,
        request_id: str,
    ) -> None:
        """Replace provider URLs with private Gateway image resources."""
        if not response.images or not workspace_id:
            return
        from app.storage import get_image_asset_service

        assets = get_image_asset_service().persist(
            response.images,
            workspace_id=workspace_id,
            user_id=user_id,
            request_id=request_id,
        )
        urls = [asset["url"] for asset in assets]
        response.images = urls
        response.answer = "\n".join(urls)
        response.raw = {
            "images": urls,
            "assets": [
                {
                    "id": asset["id"],
                    "url": asset["url"],
                    "download_url": asset.get("download_url", f"/api/images/{asset['id']}/download"),
                    "mime_type": asset["mime_type"],
                    "width": asset.get("width"),
                    "height": asset.get("height"),
                }
                for asset in assets
            ],
        }

    # ============================================================
    # Routing
    # ============================================================

    def _resolve_routing(
        self,
        messages: list[dict],
        requested_model: str | None,
        workspace_id: str | None = None,
    ):
        """
        Resolve automatic or manual routing.

        auto / empty:
            ModelRouter decides.

        explicit model:
            ModelRouter performs manual routing.

        No document-specific provider is introduced here.
        """

        normalized = (
            requested_model.strip().lower()
            if isinstance(
                requested_model,
                str,
            )
            else ""
        )

        registry = None
        modality_router = None
        if workspace_id:
            from app.providers.workspace_store import WorkspaceProviderStore

            store = WorkspaceProviderStore(workspace_id)
            registry = store.capabilities()
            classifier = ProviderFactory.create_classifier_for_workspace(workspace_id)
            modality_router = ModalityRouter(
                classifier_client=getattr(classifier, "client", None)
            )

        # --------------------------------------------------------
        # Automatic routing
        # --------------------------------------------------------

        if normalized in {
            "",
            "auto",
        }:

            return self.model_router.route(
                messages,
                registry=registry,
                modality_router=modality_router,
            )

        # --------------------------------------------------------
        # Manual routing
        # --------------------------------------------------------

        return self.model_router.route_manual(
            requested_model,
            messages,
            registry=registry,
        )

    # ============================================================
    # Extract question
    # ============================================================

    @staticmethod
    def _extract_question(
        messages: list[dict],
    ) -> str:
        """
        Extract the latest user content for history/logging.

        Supports both:

            "hello"

        and multimodal content lists.
        """

        if not messages:
            return ""

        try:

            content = messages[-1].get(
                "content",
                "",
            )

        except Exception:

            return ""

        # --------------------------------------------------------
        # Normal text
        # --------------------------------------------------------

        if isinstance(
            content,
            str,
        ):

            return content

        # --------------------------------------------------------
        # Multimodal content
        # --------------------------------------------------------

        if isinstance(
            content,
            list,
        ):

            parts: list[str] = []

            for item in content:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                item_type = item.get(
                    "type"
                )

                if item_type == "text":

                    text = item.get(
                        "text",
                        "",
                    )

                    if text:
                        parts.append(
                            str(text)
                        )

                elif item_type in {
                    "image_url",
                    "input_image",
                }:

                    parts.append(
                        "[image]"
                    )

                elif item_type in {
                    "file",
                    "input_file",
                }:

                    parts.append(
                        "[file]"
                    )

            return " ".join(parts)

        # --------------------------------------------------------
        # Fallback
        # --------------------------------------------------------

        try:

            return str(
                content
            )

        except Exception:

            return ""

    # ============================================================
    # Chat
    # ============================================================

    def chat(
        self,
        messages: list[dict],
        model: str | None = "auto",
        user_id: str | None = None,
        workspace_id: str | None = None,
        temperature: float | None = 0.7,
        max_tokens: int | None = 1024,
    ) -> GatewayResponse:

        start = time.perf_counter()

        request_id = (
            f"req_{uuid.uuid4().hex[:12]}"
        )

        GATEWAY_REQUEST_TOTAL.inc()

        # ========================================================
        # Validate
        # ========================================================

        self._validate_messages(
            messages
        )

        question = (
            self._extract_question(
                messages
            )
        )

        # Detailed architecture/coding prompts need more generation time;
        # ordinary requests keep the shorter fail-fast budget.
        request_timeout = float(settings.llm_timeout)
        if len(question) > 1200 or int(max_tokens or 0) > 2048:
            request_timeout = max(request_timeout, 90.0)

        requested_model = str(model or "auto").strip()
        workspace_scope = str(workspace_id).strip() if workspace_id is not None else None
        if settings.byok_required and not workspace_scope:
            raise RuntimeError("Authenticated workspace is required for BYOK requests")
        cache_context = {
            "model": requested_model.lower() or "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "modality": "text",
        }
        manual_model = bool(
            requested_model
            and requested_model.lower() != "auto"
        )
        # Image generation must not reuse old text answers or expiring image URLs.
        image_request = ModalityRouter._looks_like_image_generation(messages)

        try:

            # ====================================================
            # CACHE FIRST
            #
            # This is intentionally BEFORE ModelRouter.
            #
            # Cache hit:
            #
            #   no classifier
            #   no provider
            #   no upstream tokens
            # ====================================================

            try:
                cached = (
                    {"hit": False}
                    if manual_model or image_request
                    else self._lookup_cache(
                        messages,
                        workspace_id=workspace_scope or str(user_id or "system"),
                        cache_context=cache_context,
                    )
                )
            except Exception:
                # Redis is an acceleration layer. A lookup outage must not
                # prevent an authenticated request from reaching its provider.
                logger.warning("Cache lookup unavailable; continuing with miss")
                cached = {"hit": False, "cache_unavailable": True}

            if cached.get("hit"):

                cache_type = (
                    cached.get(
                        "type",
                        "exact",
                    )
                )

                CACHE_HIT_TOTAL.inc()

                if cache_type == "semantic":

                    CACHE_SEMANTIC_HIT_TOTAL.inc()

                else:

                    CACHE_EXACT_HIT_TOTAL.inc()

                # ------------------------------------------------
                # Do NOT execute ModelRouter on cache hit.
                # ------------------------------------------------

                cache_provider = (
                    self.provider_name
                )

                cache_model = (
                    self.configured_model_name
                )

                context = RequestContext(
                    provider=cache_provider,
                    model=cache_model,
                    user_id=user_id,
                    request_id=request_id,
                )

                self.lifecycle_manager.start(
                    context
                )

                context.set_cache(
                    True,
                    cache_type,
                )
                context.metadata.update(
                    {
                        "similarity": cached.get("similarity"),
                        "threshold": cached.get("threshold"),
                    }
                )

                answer = str(
                    cached.get(
                        "answer",
                        "",
                    )
                )

                latency = (
                    time.perf_counter()
                    - start
                ) * 1000

                response = LLMResponse(
                    answer=answer,
                    model=cache_model,
                    provider=cache_provider,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost=0.0,
                    latency_ms=round(
                        latency,
                        2,
                    ),
                    finish_reason="cache",
                    raw=None,
                )

                # ------------------------------------------------
                # History
                # ------------------------------------------------

                self._save_history({

                    "request_id":
                        request_id,

                    "user_id":
                        user_id,

                    "provider":
                        cache_provider,

                    "model":
                        cache_model,

                    "question":
                        question,

                    "answer":
                        answer,

                    "cache_hit":
                        True,

                    "cache_type":
                        cache_type,

                    "similarity":
                        cached.get(
                            "similarity"
                        ),

                    "threshold":
                        cached.get(
                            "threshold"
                        ),

                    "prompt_tokens":
                        0,

                    "completion_tokens":
                        0,

                    "total_tokens":
                        0,

                    "cost":
                        0,

                    "saved_cost":
                        cached.get(
                            "saved_cost",
                            0,
                        ),

                    "latency_ms":
                        latency,

                    "status":
                        "success",

                }, workspace_id=workspace_scope)

                self.lifecycle_manager.complete(
                    context
                )

                return GatewayResponse(
                    llm=response,
                    cache_hit=True,
                    cache_type=cache_type,
                    similarity=cached.get(
                        "similarity"
                    ),
                    threshold=cached.get(
                        "threshold"
                    ),
                    context=context,
                    routing={
                        "mode": "cache",
                        "provider": cache_provider,
                        "model": cache_model,
                        "reason": [
                            "cache hit; upstream routing skipped"
                        ],
                    },
                )

            # ====================================================
            # CACHE MISS
            # ====================================================

            CACHE_MISS_TOTAL.inc()

            # ====================================================
            # ROUTING
            #
            # Only executed after cache miss.
            # ====================================================

            decision = (
                self._resolve_routing(
                    messages,
                    model,
                    workspace_id=workspace_scope,
                )
            )

            routing = decision.to_dict()

            last_error: Exception | None = None

            candidates = [
                (
                    candidate.provider,
                    candidate.model,
                )
                for candidate in decision.candidates
            ]

            # ====================================================
            # Provider candidates
            #
            # Candidate order is controlled by ModelRouter.
            #
            # Possible providers:
            #
            #   qwen_classifier
            #   qwen_image
            #   deepseek
            #   openai
            #
            # qwen_document is NOT part of this gateway.
            # ====================================================

            if not candidates:

                raise RuntimeError(
                    "ModelRouter returned no candidates"
                )

            # ====================================================
            # Try candidates / fallback
            # ====================================================

            for index, (
                provider_name,
                candidate_model,
            ) in enumerate(
                candidates
            ):

                context = RequestContext(
                    provider=provider_name,
                    model=candidate_model,
                    user_id=user_id,
                    request_id=request_id,
                )

                self.lifecycle_manager.start(
                    context
                )

                provider_start = (
                    time.perf_counter()
                )

                try:

                    # ------------------------------------------------
                    # Create / reuse provider
                    # ------------------------------------------------

                    provider = (
                        self._get_provider(
                            provider_name,
                            candidate_model,
                            workspace_id=workspace_scope,
                        )
                    )

                    PROVIDER_REQUEST_TOTAL.inc()

                    # ------------------------------------------------
                    # Upstream call
                    # ------------------------------------------------

                    try:

                        response = provider.chat(
                            messages=messages,
                            model=candidate_model,
                            timeout=request_timeout,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )

                    except Exception:

                        PROVIDER_ERROR_TOTAL.inc()

                        raise

                    finally:

                        PROVIDER_LATENCY_SECONDS.observe(
                            time.perf_counter()
                            - provider_start
                        )

                    # ------------------------------------------------
                    # Validate provider response
                    # ------------------------------------------------

                    if not isinstance(
                        response,
                        LLMResponse,
                    ):

                        raise TypeError(
                            "Provider response invalid"
                        )

                    self._persist_images(
                        response,
                        workspace_id=workspace_scope,
                        user_id=str(user_id) if user_id is not None else None,
                        request_id=request_id,
                    )

                    # OpenAI-compatible providers usually return usage but
                    # not a cost. Fill it from the gateway pricing registry.
                    if not response.cost and response.total_tokens:
                        priced = cost_calculator.calculate(
                            response.model or candidate_model,
                            {
                                "prompt_tokens": response.prompt_tokens,
                                "completion_tokens": response.completion_tokens,
                            },
                        )
                        response.cost = float(priced["total_cost"])

                    # ------------------------------------------------
                    # Cache successful response
                    # ------------------------------------------------

                    try:

                        if not manual_model and provider_name != "qwen_image":
                            self.cache.set(
                                messages,
                                response.answer,
                                workspace_id=workspace_scope or str(user_id or "system"),
                                cache_context=cache_context,
                            )

                    except Exception:
                        logger.warning("Cache set failed")

                    # ------------------------------------------------
                    # Latency
                    # ------------------------------------------------

                    latency = (
                        time.perf_counter()
                        - start
                    ) * 1000

                    # ------------------------------------------------
                    # Final provider/model
                    # ------------------------------------------------

                    final_provider = (
                        response.provider
                        or provider_name
                    )

                    final_model = (
                        response.model
                        or candidate_model
                    )

                    # ------------------------------------------------
                    # Routing metadata
                    # ------------------------------------------------

                    final_routing = dict(
                        routing
                    )

                    final_routing[
                        "selected_provider"
                    ] = final_provider

                    final_routing[
                        "selected_model"
                    ] = final_model

                    final_routing[
                        "fallback_used"
                    ] = (
                        index > 0
                    )

                    final_routing[
                        "attempt"
                    ] = (
                        index + 1
                    )

                    if index > 0:

                        final_routing[
                            "fallback_reason"
                        ] = (
                            "previous candidate failed"
                        )

                    # ------------------------------------------------
                    # History
                    # ------------------------------------------------

                    self._save_history({

                        "request_id":
                            request_id,

                        "user_id":
                            user_id,

                        "provider":
                            final_provider,

                        "model":
                            final_model,

                        "question":
                            question,

                        "answer":
                            response.answer,

                        "cache_hit":
                            False,

                        "cache_type":
                            "miss",

                        "similarity":
                            None,

                        "threshold":
                            None,

                        "prompt_tokens":
                            response.prompt_tokens,

                        "completion_tokens":
                            response.completion_tokens,

                        "total_tokens":
                            response.total_tokens,

                        "cost":
                            response.cost,

                        "saved_cost":
                            0,

                        "latency_ms":
                            latency,

                        "provider_latency_ms":
                            response.latency_ms,

                        "status":
                            "success",

                    }, workspace_id=workspace_scope)

                    # ------------------------------------------------
                    # Lifecycle complete
                    # ------------------------------------------------

                    self.lifecycle_manager.complete(
                        context
                    )

                    # ------------------------------------------------
                    # Request latency
                    # ------------------------------------------------

                    REQUEST_LATENCY_SECONDS.observe(
                        time.perf_counter()
                        - start
                    )

                    # ------------------------------------------------
                    # Return
                    # ------------------------------------------------

                    return GatewayResponse(
                        llm=response,
                        cache_hit=False,
                        cache_type="miss",
                        similarity=None,
                        threshold=None,
                        context=context,
                        routing=final_routing,
                    )

                # ====================================================
                # Candidate failed
                # ====================================================

                except Exception as exc:

                    last_error = exc

                    self.lifecycle_manager.fail(
                        context,
                        exc,
                    )

                    # Continue to next candidate.

                    continue

            # ========================================================
            # ALL CANDIDATES FAILED
            # ========================================================

            GATEWAY_ERROR_TOTAL.inc()

            error_message = str(
                last_error
                or
                "All routing candidates failed"
            )

            self._save_history({

                "request_id":
                    request_id,

                "user_id":
                    user_id,

                "provider":
                    getattr(
                        decision,
                        "provider",
                        self.provider_name,
                    ),

                "model":
                    getattr(
                        decision,
                        "model",
                        self.configured_model_name,
                    ),

                "question":
                    question,

                "status":
                    "failed",

                "error":
                    error_message,

            }, workspace_id=workspace_scope)

            raise RuntimeError(
                "All configured routing candidates failed: "
                + error_message
            )

        except Exception:

            # --------------------------------------------------------
            # Do not double-count errors already handled above.
            #
            # Gateway errors that reach this level are unexpected
            # request-level failures.
            # --------------------------------------------------------

            raise

        finally:

            # ========================================================
            # Request latency
            # ========================================================

            try:

                REQUEST_LATENCY_SECONDS.observe(
                    time.perf_counter()
                    - start
                )

            except Exception:

                pass

    # ============================================================
    # Health
    # ============================================================

    def health(self):
        """
        Gateway health information.
        """

        try:

            redis_ok = (
                self.cache.ping()
            )

            cache_size = (
                self.cache.size()
            )

        except Exception:

            redis_ok = False
            cache_size = 0

        try:

            cache_info = (
                self.cache.repository.info()
            )

        except Exception:

            cache_info = {}

        try:

            lifecycle = (
                self.lifecycle_manager.snapshot()
            )

        except Exception:

            lifecycle = {}

        return {

            "status":
                (
                    "ok"
                    if redis_ok
                    else "degraded"
                ),

            "provider":
                self.provider_name,

            "model":
                self.configured_model_name,

            "redis":
                redis_ok,

            "cache_size":
                cache_size,

            "cache":
                cache_info,

            "lifecycle":
                lifecycle,

        }


# ================================================================
# Default gateway
# ================================================================

_default_gateway: AIGateway | None = None
_default_gateway_lock = threading.Lock()


def get_gateway() -> AIGateway:
    """
    Return singleton gateway instance.
    """

    global _default_gateway

    if _default_gateway is None:
        with _default_gateway_lock:
            if _default_gateway is None:
                _default_gateway = AIGateway()

    return _default_gateway


__all__ = [
    "AIGateway",
    "get_gateway",
]
