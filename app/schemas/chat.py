from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = Field(
        ..., description="The role of the message author."
    )
    content: str = Field(..., description="The textual contents of the message.")
    name: Optional[str] = Field(
        default=None, description="An optional identifier for the participant."
    )


class ChatCompletionRequest(BaseModel):
    model: str = Field(
        default="default",
        description="ID of the model or 'default' to let the router pick the optimal model.",
    )
    messages: List[ChatMessage] = Field(
        ..., min_length=1, description="List of messages comprising the conversation."
    )
    temperature: Optional[float] = Field(
        default=0.7, ge=0.0, le=2.0, description="Sampling temperature between 0.0 and 2.0."
    )
    top_p: Optional[float] = Field(
        default=1.0, ge=0.0, le=1.0, description="Nucleus sampling probability threshold."
    )
    n: Optional[int] = Field(
        default=1, ge=1, le=1, description="Number of completions to generate."
    )
    stream: Optional[bool] = Field(
        default=False, description="Streaming support toggle."
    )
    max_tokens: Optional[int] = Field(
        default=1024, ge=1, description="Maximum number of tokens to generate."
    )
    presence_penalty: Optional[float] = Field(
        default=0.0, ge=-2.0, le=2.0, description="Presence penalty parameter."
    )
    frequency_penalty: Optional[float] = Field(
        default=0.0, ge=-2.0, le=2.0, description="Frequency penalty parameter."
    )
    stop: Optional[Union[str, List[str]]] = Field(
        default=None, description="Sequences where generation stops."
    )
    provider: Optional[str] = Field(
        default=None,
        description="Explicit provider override ('openai', 'anthropic', 'groq', 'openrouter').",
    )


class ChatCompletionChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionChoiceMessage
    finish_reason: Optional[str] = "stop"


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RouterMetadata(BaseModel):
    provider_used: str = Field(..., description="The LLM provider that satisfied the request.")
    model_used: str = Field(..., description="The actual model identifier invoked.")
    latency_ms: float = Field(..., description="Total round-trip execution latency in milliseconds.")
    fallback_chain: List[str] = Field(
        default_factory=list,
        description="List of providers that were attempted and failed prior to success.",
    )
    retries_attempted: int = Field(
        default=0, description="Total number of retries executed."
    )


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: UsageInfo
    router_meta: RouterMetadata = Field(
        ...,
        alias="_router_meta",
        description="Diagnostic metadata detailing provider selection, fallbacks, and latency.",
    )

    model_config = {
        "populate_by_name": True,
    }


class APIError(BaseModel):
    message: str
    type: str
    param: Optional[str] = None
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    error: APIError
