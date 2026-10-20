from __future__ import annotations


from app.schemas.llm_response import LLMResponse




class FallbackProvider:


    """
    Provider fallback wrapper.

    Try primary provider,
    then fallback provider.
    """



    def __init__(
        self,
        primary,
        fallback,
    ) -> None:


        self.primary = primary

        self.fallback = fallback




    def chat(

        self,

        messages: list[dict],

        model: str | None = None,

    ) -> LLMResponse:



        try:


            return self.primary.chat(

                messages,

                model,

            )



        except Exception:



            return self.fallback.chat(

                messages,

                model,

            )