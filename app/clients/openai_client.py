from __future__ import annotations


from app.clients.openai_compatible_client import (
    OpenAICompatibleClient,
)




class OpenAIClient(
    OpenAICompatibleClient
):


    """
    OpenAI client.

    Uses OpenAI compatible protocol.
    """



    def __init__(
        self,
        **kwargs,
    ) -> None:


        super().__init__(

            provider_name="openai",

            **kwargs,

        )