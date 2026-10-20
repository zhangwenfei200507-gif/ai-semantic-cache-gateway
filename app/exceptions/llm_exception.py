from __future__ import annotations



class LLMException(Exception):
    """
    Base LLM gateway exception.
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        model: str | None = None,
        cause: Exception | None = None,
    ):

        super().__init__(message)

        self.message = message

        self.provider = provider

        self.model = model

        self.cause = cause



    def to_dict(self):

        return {

            "message":
                self.message,

            "provider":
                self.provider,

            "model":
                self.model,

            "cause":
                str(self.cause)
                if self.cause
                else None,
        }




class ProviderException(
    LLMException
):
    """
    Provider layer failure.
    """



class ClientException(
    LLMException
):
    """
    HTTP/API client failure.
    """