from __future__ import annotations


from abc import ABC, abstractmethod


from app.schemas.llm_response import LLMResponse




class BaseProvider(
    ABC
):


    """
    Provider abstraction layer.


    Gateway

        |

    Provider

        |

    Client

    """



    name: str = ""




    def __init__(
        self,
        client,
    ) -> None:


        self.client = client




    @abstractmethod
    def chat(

        self,

        messages: list[dict],

        model: str | None = None,

    ) -> LLMResponse:


        raise NotImplementedError