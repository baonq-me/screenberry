from pydantic import BaseModel, Field


class DomainRequest(BaseModel):
    domain: str = Field(description="Domain", example="example.com")


class DomainRequestParams(BaseModel):
    timeout: int = Field(description="Timeout in seconds", default="3", example="3")
    bypass_cache: int = Field(description="Set to 1 to bypass cache", default="0", example="0")
