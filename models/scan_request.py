from pydantic import BaseModel, Field


class DomainRequest(BaseModel):
    domain: str = Field(description="Domain", example="example.com")


class DomainRequestParams(BaseModel):
    timeout: int = Field(description="Timeout in seconds", default="15", example="15")
    bypass_cache: int = Field(description="Set to 1 to bypass cache", default="0", example="0")
    uri_scheme: str = Field(description="URL schemes: http or https", default="https", example="https")
    pageload_wait_seconds: float = Field(description="Time to wait for page load", default="5.0", example="5.0")
