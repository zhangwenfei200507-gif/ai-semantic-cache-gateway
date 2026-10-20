from pydantic import BaseModel



class ChatResponse(BaseModel):


    id:str


    model:str


    answer:str


    source:str


    latency_ms:float