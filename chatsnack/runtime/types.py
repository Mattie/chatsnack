from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol, AsyncIterator, Iterator, runtime_checkable

EVENT_SCHEMA_VERSION = "1.0"
RESERVED_EVENT_TYPES = {
    "text_delta",
    "tool_call_delta",
    "tool_result",
    "phase",
    "usage",
    "completed",
    "error",
}


@dataclass
class NormalizedToolFunction:
    name: str
    arguments: str = ""


@dataclass
class NormalizedToolCall:
    id: str
    type: str = "function"
    function: Optional[NormalizedToolFunction] = None
    payload: Optional[Dict[str, Any]] = None


@dataclass
class NormalizedAssistantMessage:
    role: str = "assistant"
    content: Optional[str] = None
    reasoning: Optional[str] = None
    encrypted_content: Optional[str] = None
    sources: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    files: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[NormalizedToolCall] = field(default_factory=list)


@dataclass
class NormalizedCompletionResult:
    message: NormalizedAssistantMessage
    finish_reason: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeTerminalMetadata:
    finish_reason: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    response_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeErrorPayload:
    message: str
    code: Optional[str] = None
    retriable: bool = False
    details: Optional[Dict[str, Any]] = None


@dataclass
class RuntimeStreamEvent:
    type: Literal[
        "text_delta",
        "tool_call_delta",
        "tool_result",
        "phase",
        "usage",
        "completed",
        "error",
    ]
    index: int
    data: Dict[str, Any]
    schema_version: str = EVENT_SCHEMA_VERSION


@runtime_checkable
class RuntimeAdapter(Protocol):
    """
    RuntimeAdapter owns only provider I/O and normalization.
    Prompt compilation and template expansion remain Chat-layer responsibilities.
    """

    def create_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> NormalizedCompletionResult:
        ...

    async def create_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any) -> NormalizedCompletionResult:
        ...

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Iterator[RuntimeStreamEvent]:
        ...

    async def stream_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any) -> AsyncIterator[RuntimeStreamEvent]:
        ...
