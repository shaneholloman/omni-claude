from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from anthropic.types import MessageParam
from pydantic import BaseModel, Field, model_validator

from src.infra.logger import get_logger
from src.models.base_models import SupabaseModel

logger = get_logger()


# Anthropic streaming event types
class StreamingEventType(str, Enum):
    """Custom application event types loosely based on Anthropic API event types."""

    # Streaming events
    MESSAGE_START = "message_start"
    CONTENT_BLOCK_DELTA = "content_block_delta"
    MESSAGE_STOP = "message_stop"

    # Error events
    ERROR = "error"

    # Custom events
    TEXT_TOKEN = "text_token"
    TOOL_RESULT = "tool_result"
    ASSISTANT_MESSAGE = "assistant_message"


class StreamingTextDelta(BaseModel):
    """Text delta event."""

    type: Literal["text_delta"] = "text_delta"
    text: str = Field(..., description="Text delta")


class ErrorEvent(BaseModel):
    """Error event."""

    type: Literal["error"] = "error"
    data: dict = Field(..., description="Error data")


class ToolUseEvent(BaseModel):
    """Tool use event."""

    type: Literal["tool_use"] = "tool_use"
    content: ToolUseBlock = Field(..., description="Tool use inputs")


class AssistantMessageEvent(BaseModel):
    """Assistant message event."""

    type: Literal["assistant_message"] = "assistant_message"
    content: list[TextBlock | ToolUseBlock] = Field(..., description="Assistant response content blocks")


class ToolResultEvent(BaseModel):
    """Tool result event."""

    type: Literal["tool_result"] = "tool_result"
    content: ToolResultBlock = Field(..., description="Tool result content block")


class StreamingEvent(BaseModel):
    """Anthropic event structure for internal use."""

    event_type: StreamingEventType = Field(..., description="Type of the event")
    event_data: StreamingTextDelta | ErrorEvent | AssistantMessageEvent | ToolUseEvent | ToolResultEvent | None = Field(
        None, description="Text delta or error event"
    )


# Content block types


class ContentBlockType(str, Enum):
    """Types of content blocks in a conversation that are used by Anthropic."""

    TEXT = "text"
    IMAGE = "image"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    DOCUMENT = "document"


class TextBlock(BaseModel):
    """Simple text content"""

    block_type: ContentBlockType = Field(ContentBlockType.TEXT, description="Type of the content block", alias="type")
    text: str = Field(..., description="Text content of the block")


class ToolUseBlock(BaseModel):
    """Tool usage by assistant"""

    block_type: ContentBlockType = Field(
        ContentBlockType.TOOL_USE, description="Type of the content block", alias="type"
    )
    tool_use_id: str = Field(..., description="ID of the tool use", alias="id")
    tool_name: str = Field(..., description="Name of the tool", alias="name")
    tool_input: dict = Field(..., description="Input to the tool", alias="input")


class ToolResultBlock(BaseModel):
    """Tool result from assistant"""

    block_type: ContentBlockType = Field(
        ContentBlockType.TOOL_RESULT, description="Type of the content block", alias="type"
    )
    tool_use_id: str = Field(..., description="ID of the tool use")
    content: str = Field(..., description="Result returned from the tool")
    is_error: bool = Field(False, description="Error returned from the tool")


# Messages
class Role(str, Enum):
    """Roles in the conversation."""

    ASSISTANT = "assistant"
    USER = "user"


class ConversationMessage(SupabaseModel):
    """A message in a conversation between a user and an LLM."""

    message_id: UUID = Field(
        default_factory=uuid4,
        description="UUID of a message. Generated by backend for assistant messages, sent by client for user messages.",
    )
    conversation_id: UUID | None = Field(None, description="FK reference to a conversation.")
    role: Role = Field(..., description="Role of the message sender")
    content: list[TextBlock | ToolUseBlock | ToolResultBlock] = Field(
        ...,
        description="Content of the message corresponding to Anthropic API",
    )

    _db_config: ClassVar[dict] = {"schema": "chat", "table": "messages", "primary_key": "message_id"}

    @model_validator(mode="before")
    def validate_content(cls, values: dict) -> dict:
        """Ensure the correct model is instantiated for each item in the `content` list."""
        content_data = values.get("content", [])
        resolved_content: list[TextBlock | ToolUseBlock | ToolResultBlock] = []

        for item in content_data:
            # Inspect the `block_type` field to determine which model to use
            if isinstance(item, TextBlock):
                resolved_content.append(item)
            elif isinstance(item, ToolUseBlock):
                resolved_content.append(item)
            elif isinstance(item, ToolResultBlock):
                resolved_content.append(item)
            elif isinstance(item, dict):
                if item.get("type") == ContentBlockType.TEXT:
                    resolved_content.append(TextBlock(**item))
                elif item.get("type") == ContentBlockType.TOOL_USE:
                    resolved_content.append(ToolUseBlock(**item))
                elif item.get("type") == ContentBlockType.TOOL_RESULT:
                    resolved_content.append(ToolResultBlock(**item))
                else:
                    raise ValueError(f"Unknown content block type: {item.get('type')}, {item}")
            else:
                raise ValueError(f"Unknown content block type: {type(item)}, {item}")

        values["content"] = resolved_content
        return values

    def to_anthropic(self) -> MessageParam:
        """Convert to Anthropic API format"""
        return {
            "role": self.role.value,
            "content": [block.model_dump(by_alias=True) for block in self.content],
        }


# Conversation
class Conversation(SupabaseModel):
    """Domain model for a conversation in chat.."""

    conversation_id: UUID = Field(default_factory=uuid4, description="UUID of the conversation")
    user_id: UUID = Field(..., description="FK reference to UUID of the user")
    title: str = Field(..., description="Title of the conversation")
    message_ids: list[UUID] | list = Field(
        default_factory=list, description="FK references to UUIDs of the messages in the conversation"
    )
    token_count: int = Field(default=0, description="Total token count for the conversation, initially 0")
    data_sources: list[UUID] = Field(
        default=...,
        description="FK references to UUIDs of the data sources last active for the conversation",
    )

    _db_config: ClassVar[dict] = {"schema": "chat", "table": "conversations", "primary_key": "conversation_id"}


class ConversationHistory(BaseModel):
    """A list of messages for a conversation"""

    conversation_id: UUID = Field(default_factory=uuid4, description="FK reference to UUID of the conversation")
    messages: list[ConversationMessage] = Field(
        default_factory=list, description="List of messages in the conversation"
    )
    token_count: int = Field(default=0, description="Total token count for the conversation, initially 0")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last updated timestamp")

    def to_anthropic_messages(self) -> Iterable[MessageParam]:
        """Convert entire history to Anthropic format"""
        result = [msg.to_anthropic() for msg in self.messages]
        logger.debug(f"To Anthropic conversion result: {result}")
        return result


class ConversationSummary(BaseModel):
    """Summary of a conversation returned by GET /conversations"""

    conversation_id: UUID = Field(..., description="UUID of the conversation")
    title: str = Field(..., description="Title of the conversation")
    updated_at: datetime = Field(..., description="Last updated timestamp")
