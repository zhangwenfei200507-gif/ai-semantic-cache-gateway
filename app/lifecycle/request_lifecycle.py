from __future__ import annotations

from app.context.request_context import RequestContext


class RequestLifecycle:
    """Small state-transition helper for one gateway request."""

    def __init__(self, context: RequestContext) -> None:
        self.context = context

    def start(self) -> RequestContext:
        self.context.start()
        return self.context

    def complete(self) -> RequestContext:
        self.context.complete()
        return self.context

    def fail(self, error: str | BaseException) -> RequestContext:
        self.context.fail(error)
        return self.context
