from __future__ import annotations


from app.clients.openai_compatible_client import (
    OpenAICompatibleClient,
)




class DeepSeekClient(
    OpenAICompatibleClient
):


    """
    DeepSeek OpenAI-compatible client.
    """



    def __init__(
        self,
        **kwargs,
    ) -> None:


        super().__init__(

            provider_name="deepseek",

            **kwargs,

        )