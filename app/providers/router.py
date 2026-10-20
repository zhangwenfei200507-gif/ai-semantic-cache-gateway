from __future__ import annotations




class ProviderRouter:
    """
    Provider routing layer.

    Used for multi provider strategy.
    """



    def __init__(
        self,
        providers: dict,
    ) -> None:


        self.providers = providers





    def get(
        self,
        name: str,
    ):


        provider = self.providers.get(

            name

        )



        if provider is None:


            raise ValueError(

                f"Provider not found: {name}"

            )



        return provider