from app.middleware.request_context_middleware import RequestContextMiddleware
from app.middleware.logger import LoggerMiddleware
from app.middleware.cost_tracker import CostTrackerMiddleware


class MiddlewarePipeline:

    def __init__(self, gateway):

        self.gateway = gateway

        self.middlewares = [
            RequestContextMiddleware(),
            LoggerMiddleware(),
            CostTrackerMiddleware(),
        ]


    async def execute(self, request):

        async def call(index, req):

            if index >= len(self.middlewares):
                return await self.gateway.chat(req)


            middleware = self.middlewares[index]


            return await middleware.handle(
                req,
                lambda r: call(index + 1, r)
            )


        return await call(0, request)