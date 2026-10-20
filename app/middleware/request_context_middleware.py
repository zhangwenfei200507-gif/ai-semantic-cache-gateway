from __future__ import annotations

from app.context.request_context import RequestContext


class RequestContextMiddleware:
    """Compatibility middleware for the existing middleware pipeline."""

    async def handle(self, request, next_call):
        request.context = RequestContext(
            provider=getattr(request, "provider", None),
            model=getattr(request, "model", None),
            user_id=getattr(request, "user_id", None),
        )
        request.context.start()
        return await next_call(request)
