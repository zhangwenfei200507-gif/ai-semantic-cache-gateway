import requests


from app.clients.llm_client import LLMClient



class OllamaClient(
    LLMClient
):


    def __init__(

        self,

        base_url=
        "http://localhost:11434",

        model=
        "llama3"

    ):


        super().__init__(

            api_key="",

            base_url=base_url,

            model=model

        )



    def chat(
        self,
        messages
    ):


        response = requests.post(

            self.base_url + "/api/chat",

            json={

                "model":
                self.model,


                "messages":
                messages,


                "stream":
                False

            },

            timeout=60

        )


        data=response.json()



        return {


            "answer":

            data["message"]["content"],


            "model":

            self.model,


            "prompt_tokens":

            0,


            "completion_tokens":

            0,


            "tokens":

            0,


            "cost":

            0

        }