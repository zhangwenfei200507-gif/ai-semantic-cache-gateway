from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway import get_gateway
from app.auth.dependencies import get_current_user
from app.providers.workspace_store import WorkspaceProviderStore
from app.providers.factory import ProviderFactory
from app.routing.modality_router import ModalityRouter
from app.config.settings import settings
from app.security.guards import public_error


router = APIRouter(
    prefix="/api/routing",
    tags=["routing"],
    dependencies=[Depends(get_current_user)],
)


class RoutingRequest(BaseModel):

    messages: list[dict[str, Any]] = Field(
        min_length=1
    )


@router.post(
    "/preview"
)
def routing_preview(
    payload: RoutingRequest,
    user: dict = Depends(get_current_user),
):

    gateway = get_gateway()


    try:

        if settings.database_url:
            store = WorkspaceProviderStore(user["workspace"]["id"])
            classifier = ProviderFactory.create_classifier_for_workspace(user["workspace"]["id"])
            decision = gateway.model_router.route(
                payload.messages,
                registry=store.capabilities(),
                modality_router=ModalityRouter(classifier_client=getattr(classifier, "client", None)),
            )
        else:
            decision = gateway.model_router.route(payload.messages)


        return {

            "status":
                "ok",

            "routing":
                decision.to_dict(),

        }


    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=public_error(exc, "Invalid routing request"),
        ) from exc


    except Exception as exc:

        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Routing preview unavailable"),
        ) from exc


@router.get(
    "/models"
)
def routing_models(user: dict = Depends(get_current_user)):

    gateway = get_gateway()


    models = (
        WorkspaceProviderStore(user["workspace"]["id"]).capabilities().configured()
        if settings.database_url
        else gateway.model_router.registry.configured()
    )


    return {

        "count":
            len(models),

        "models": [

            {

                "provider":
                    model.provider,

                "model":
                    model.model,

                "description":
                    model.routing_description.strip(),

                "enabled":
                    model.enabled,

            }

            for model in models

        ]

    }


@router.post(
    "/diagnostics"
)
def routing_diagnostics(
    payload: RoutingRequest,
    user: dict = Depends(get_current_user),
):

    gateway = get_gateway()


    try:

        if settings.database_url:
            store = WorkspaceProviderStore(user["workspace"]["id"])
            classifier = ProviderFactory.create_classifier_for_workspace(user["workspace"]["id"])
            decision = gateway.model_router.route(
                payload.messages,
                registry=store.capabilities(),
                modality_router=ModalityRouter(classifier_client=getattr(classifier, "client", None)),
            )
        else:
            decision = gateway.model_router.route(payload.messages)


        result = decision.to_dict()


        return {

            "status":
                "ok",

            "selected": {

                "provider":
                    result["provider"],

                "model":
                    result["model"],

                "score":
                    result["score"],

                "confidence":
                    result["confidence"],

                "confidence_level":
                    result[
                        "confidence_level"
                    ],

                "reasons":
                    result["reasons"],

            },

            "request":
                result[
                    "request_profile"
                ],

            "candidates":
                result[
                    "candidates"
                ],

            "fallback":
                result[
                    "fallback_candidates"
                ],

        }


    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=public_error(exc, "Invalid routing request"),
        ) from exc


    except Exception as exc:

        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Routing diagnostics unavailable"),
        ) from exc
