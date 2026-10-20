import time
import uuid
import logging


from starlette.middleware.base import (
    BaseHTTPMiddleware
)



logger = logging.getLogger(
    "gateway"
)


logging.basicConfig(
    level=logging.INFO
)



class RequestLoggerMiddleware(
    BaseHTTPMiddleware
):


    async def dispatch(
        self,
        request,
        call_next
    ):


        request_id=str(
            uuid.uuid4()
        )


        start=time.time()



        response=await call_next(
            request
        )


        latency=(

            time.time()

            -

            start

        )*1000



        logger.info(
            {
                "request_id":
                    request_id,

                "method":
                    request.method,

                "path":
                    request.url.path,

                "latency_ms":
                    round(
                        latency,
                        2
                    )
            }
        )



        response.headers[
            "X-Request-ID"
        ]=request_id



        return response