from pydantic import BaseModel



class ChatMessage(BaseModel):

    role:str

    content:str




class ChatRequest(BaseModel):


    model:str="auto"


    messages:list[ChatMessage]