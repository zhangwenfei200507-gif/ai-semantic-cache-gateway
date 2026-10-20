from __future__ import annotations

import platform
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.gateway import get_gateway
from app.config.settings import settings
from app.history.repository import history_repository
from app.metrics.llm_metrics import llm_metrics


router = APIRouter(
    prefix="/api",
    tags=["admin"],
)


# ============================================================
# Session
# ============================================================

@router.get("/session")
def create_session():

    return {
        "user_id":
            f"gateway_user_{uuid.uuid4().hex[:12]}"
    }



# ============================================================
# Status
# ============================================================

@router.get("/status")
def status():

    gateway = get_gateway()

    health = gateway.health()

    return {

        "name":
            settings.app_name,

        "version":
            settings.app_version,

        "status":
            health.get("status"),

        "provider":
            health.get("provider"),

        "model":
            health.get("model"),

        "redis":
            health.get("redis"),

    }



# ============================================================
# Dashboard
# ============================================================

@router.get("/dashboard")
def dashboard():

    gateway = get_gateway()

    health = gateway.health()


    history = (
        history_repository.list(
            10000
        )
    )


    metrics = (
        llm_metrics.snapshot()
    )


    total = len(history)


    cache_hits = sum(
        1
        for item in history
        if item.get("cache_hit")
    )


    exact_hits = sum(
        1
        for item in history
        if item.get("cache_type")
        == "exact"
    )


    semantic_hits = sum(
        1
        for item in history
        if item.get("cache_type")
        == "semantic"
    )


    hit_rate = (
        0
        if total == 0
        else round(
            cache_hits
            /
            total
            *
            100,
            2
        )
    )


    return {

        "kpi": {

            "total_requests":
                total,


            "cache_hit_rate":
                hit_rate,


            "cache_size":
                health.get(
                    "cache_size",
                    0
                ),


            "semantic_hits":
                semantic_hits,


            "exact_hits":
                exact_hits,


            "total_tokens":
                metrics.get(
                    "total_tokens",
                    0
                ),


            "total_cost":
                metrics.get(
                    "total_cost",
                    0
                ),

        },


        "cache": {

            "size":
                health.get(
                    "cache_size",
                    0
                ),


            "hit_rate":
                hit_rate,


            "exact_hits":
                exact_hits,


            "semantic_hits":
                semantic_hits,

        },


        "recent_requests":
            history[
                :10
            ],


        "system": {

            "redis":
                health.get(
                    "redis"
                ),


            "provider":
                health.get(
                    "provider"
                ),


            "model":
                health.get(
                    "model"
                ),

        },

    }



# ============================================================
# Models Registry
# ============================================================

@router.get("/models")
def models():

    result = []


    # DeepSeek

    result.append({

        "provider":
            "deepseek",

        "model":
            settings.deepseek_model,

        "configured":
            settings.is_deepseek_configured(),

    })


    # OpenAI

    result.append({

        "provider":
            "openai",

        "model":
            settings.openai_model,

        "configured":
            settings.is_openai_configured(),

    })


    return {

        "models":
            result

    }



# ============================================================
# Requests
# ============================================================

@router.get("/requests")
def requests(
    limit: int = 50,
    keyword: str | None = None,
    cache_type: str | None = None,
):

    items = history_repository.list(
        limit
    )


    if keyword:

        keyword_lower = (
            keyword.lower()
        )

        items = [

            x
            for x in items

            if keyword_lower
            in str(
                x
            ).lower()

        ]


    if cache_type:

        items = [

            x
            for x in items

            if x.get(
                "cache_type"
            )
            ==
            cache_type

        ]


    return {

        "items":
            items

    }



@router.get("/requests/{request_id}")
def request_detail(
    request_id: str,
):

    item = (
        history_repository.get(
            request_id
        )
    )


    if item is None:

        raise HTTPException(

            status_code=404,

            detail="Request not found"

        )


    return item
# ============================================================
# Cache Management
# ============================================================


@router.get("/cache")
def cache():

    gateway = get_gateway()


    try:

        repository = gateway.cache.repository


        info = repository.info()


        entries = []


        list_method = getattr(
            repository,
            "list_entries",
            None
        )


        if callable(list_method):

            result = list_method()


            if isinstance(
                result,
                list
            ):

                entries = result



        return {


            "size":
                gateway.cache.size(),



            "info":
                info,



            "entries":
                entries,



        }



    except Exception as exc:


        raise HTTPException(

            status_code=503,

            detail=str(exc),

        )





@router.get("/cache/{cache_id}")
def cache_detail(
    cache_id: str,
):

    gateway = get_gateway()


    try:


        repository = gateway.cache.repository



        getter = getattr(
                repository,
                "get_entry",
                None
            )



        if not callable(getter):

            raise HTTPException(

                status_code=501,

                detail=
                "Cache detail is not implemented",

            )



        result = getter(
                cache_id
            )



        if result is None:


            raise HTTPException(

                status_code=404,

                detail=
                "Cache entry not found",

            )



        return result



    except HTTPException:

        raise


    except Exception as exc:


        raise HTTPException(

            status_code=503,

            detail=str(exc),

        )






@router.delete("/cache/{cache_id}")
def delete_cache_entry(
    cache_id: str,
):

    gateway = get_gateway()


    try:


        repository = gateway.cache.repository



        delete_method = getattr(
                repository,
                "delete",
                None
            )



        if not callable(delete_method):


            raise HTTPException(

                status_code=501,

                detail=
                "Cache delete is not implemented",

            )



        delete_method(
            cache_id
        )



        return {


            "status":
                "ok",



            "deleted":
                cache_id,



        }



    except HTTPException:

        raise


    except Exception as exc:


        raise HTTPException(

            status_code=503,

            detail=str(exc),

        )





@router.delete("/cache")
def clear_cache():

    gateway = get_gateway()


    try:


        gateway.cache.clear()



        return {


            "status":
                "ok",



            "size":
                gateway.cache.size(),



        }



    except Exception as exc:


        raise HTTPException(

            status_code=503,

            detail=str(exc),

        )


# ============================================================
# Providers
# ============================================================

@router.get("/providers")
def providers():

    providers = []


    providers.append({

        "name":
            "deepseek",

        "model":
            settings.deepseek_model,

        "base_url":
            settings.deepseek_base_url,

        "configured":
            settings.is_deepseek_configured(),

        "status":
            (
                "configured"
                if settings.is_deepseek_configured()
                else "not_configured"
            ),

    })


    providers.append({

        "name":
            "openai",

        "model":
            settings.openai_model,

        "base_url":
            settings.openai_base_url,

        "configured":
            settings.is_openai_configured(),

        "status":
            (
                "configured"
                if settings.is_openai_configured()
                else "not_configured"
            ),

    })


    return {

        "providers":
            providers

    }



# ============================================================
# System Information
# ============================================================

@router.get("/system")
def system():

    gateway = get_gateway()

    health = gateway.health()


    cache_info = (
        health.get(
            "cache"
        )
        or {}
    )


    return {


        "gateway": {

            "name":
                settings.app_name,


            "version":
                settings.app_version,


            "platform":
                platform.platform(),


            "python":
                platform.python_version(),

        },


        "redis": {

            "status":
                (
                    "healthy"
                    if health.get("redis")
                    else "unavailable"
                ),


            "url":
                settings.redis_url,


            "index":
                cache_info.get(
                    "index_name"
                ),


            "algorithm":
                cache_info.get(
                    "algorithm"
                ),


            "distance":
                cache_info.get(
                    "distance_metric"
                ),


            "dimension":
                cache_info.get(
                    "vector_dim"
                ),

        },


        "embedding": {

            "model":
                settings.embedding_model,


            "dimension":
                settings.vector_dimension,

        },


        "runtime": {

            "timestamp":
                time.time(),

        },


        "lifecycle":
            health.get(
                "lifecycle"
            ),

    }



# ============================================================
# Metrics
# ============================================================

@router.get("/metrics/data")
def metrics_data():

    return llm_metrics.snapshot()



# ============================================================
# Cost
# ============================================================

@router.get("/cost")
def cost():

    metrics = (
        llm_metrics.snapshot()
    )


    return {

        "total_tokens":
            metrics.get(
                "total_tokens",
                0
            ),


        "total_cost":
            metrics.get(
                "total_cost",
                0
            ),


        "currency":
            "USD",

    }