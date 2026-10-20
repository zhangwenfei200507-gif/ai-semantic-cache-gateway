from __future__ import annotations


from app.providers.base import BaseProvider


from app.schemas.llm_response import LLMResponse




class DeepSeekProvider(
    BaseProvider
):


    name = "deepseek"




    def chat(

        self,

        messages: list[dict],

        model: str | None = None,

        **kwargs,

    ) -> LLMResponse:



        response = self.client.chat(

            messages=messages,

            model=model,

            **kwargs,

        )



        if not isinstance(

            response,

            LLMResponse,

        ):


            raise TypeError(

                "Client must return LLMResponse"

            )



        response.provider = (

            response.provider

            or self.name

        )



        return response
