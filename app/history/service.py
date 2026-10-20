from __future__ import annotations


from app.context.request_context import RequestContext

from app.schemas.gateway_response import GatewayResponse

from app.history.models import RequestHistory

from app.history.repository import (
    history_repository,
)



class HistoryService:


    def __init__(
        self,
    ) -> None:

        self.repository = (
            history_repository
        )



    def record_success(
        self,
        result: GatewayResponse,
        messages: list[dict],
    ) -> None:


        context = result.context


        question = ""


        if messages:

            question = str(
                messages[-1].get(
                    "content",
                    "",
                )
            )



        item = RequestHistory(

            request_id=context.request_id,

            user_id=context.user_id,

            provider=result.provider,

            model=result.model,

            question=question,

            answer=result.answer,

            cache_hit=result.cache_hit,

            cache_type=result.cache_type,

            similarity=context.metadata.get(
                "similarity"
            ),

            threshold=context.metadata.get(
                "threshold"
            ),

            latency_ms=context.latency_ms,

            prompt_tokens=result.llm.prompt_tokens,

            completion_tokens=result.llm.completion_tokens,

            total_tokens=result.tokens,

            cost=result.llm.cost,

            status="completed",

        )


        self.repository.save(
            item
        )




    def record_failure(
        self,
        context: RequestContext,
        error: Exception,
        messages: list[dict],
    ) -> None:


        question = ""


        if messages:

            question = str(
                messages[-1].get(
                    "content",
                    "",
                )
            )


        item = RequestHistory(

            request_id=context.request_id,

            user_id=context.user_id,

            provider=context.provider or "",

            model=context.model or "",

            question=question,

            answer="",


            cache_hit=context.cache_hit,

            cache_type=context.cache_type,


            latency_ms=context.latency_ms,


            prompt_tokens=context.prompt_tokens,

            completion_tokens=context.completion_tokens,

            total_tokens=context.total_tokens,


            cost=context.cost,


            status="failed",

            error=str(error),

        )


        self.repository.save(
            item
        )




history_service = HistoryService()