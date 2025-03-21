from pydantic import BaseModel


class ExecuteRequest(BaseModel):
    user_id: str
    code: str
