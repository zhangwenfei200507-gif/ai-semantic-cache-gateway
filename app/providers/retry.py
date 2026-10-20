from __future__ import annotations


import time

from typing import Callable, TypeVar





T = TypeVar(
    "T"
)




class RetryPolicy:
    """
    Retry execution policy.
    """



    def __init__(
        self,
        retries: int = 2,
        delay: float = 1.0,
    ) -> None:


        self.retries = retries

        self.delay = delay





    def execute(
        self,
        func: Callable[[], T],
    ) -> T:



        last_error = None



        for attempt in range(

            self.retries + 1

        ):



            try:

                return func()



            except Exception as exc:



                last_error = exc



                if attempt >= self.retries:

                    break



                time.sleep(

                    self.delay

                )



        raise RuntimeError(

            "retry failed"

        ) from last_error