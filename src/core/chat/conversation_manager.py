# TODO: refactor token counting https://github.com/anthropics/anthropic-sdk-python?tab=readme-ov-file#token-counting
from typing import Any
from uuid import UUID

import tiktoken
from pydantic import ValidationError

from src.infrastructure.common.logger import get_logger
from src.models.chat_models import ConversationHistory, ConversationMessage, MessageContent, Role

logger = get_logger()


class ConversationManager:
    """Manages conversation state, including in-memory storage and token management."""

    def __init__(self, max_tokens: int = 200000, tokenizer: str = "cl100k_base"):
        self.max_tokens = max_tokens
        self.tokenizer = tiktoken.get_encoding(tokenizer)
        # Main conversation storage
        self.conversations: dict[UUID, ConversationHistory] = {}
        # Temporary storage for messages during tool use
        self.pending_messages: dict[UUID, list[ConversationMessage]] = {}

    async def get_or_create_conversation(self, conversation_id: UUID | None = None) -> ConversationHistory:
        """
        Get or create conversation history by ID.

        Args:
            conversation_id: Optional UUID for the conversation. If None, creates a new conversation
                           with a generated UUID.
        """
        if conversation_id is None:
            # Create new conversation with auto-generated UUID
            conversation = await self.create_conversation()
            logger.info(f"Created new conversation: {conversation.conversation_id}")
            return conversation

        if conversation_id not in self.conversations:
            # Create new conversation with provided UUID
            conversation = await self.create_conversation(conversation_id=conversation_id)
            self.conversations[conversation_id] = conversation
            logger.info(f"Created new conversation: {conversation.conversation_id}")
            return conversation

        return self.conversations[conversation_id]

    async def create_conversation(self) -> ConversationHistory:
        """Create a new conversation history with auto-generated UUID."""
        conversation = ConversationHistory()  # UUID is auto-generated by the model
        # Save to memory using the auto-generated ID
        self.conversations[conversation.conversation_id] = conversation
        return conversation

    async def add_message(self, conversation_id: UUID, role: str, content: MessageContent) -> None:
        """Add a message directly to conversation history."""
        try:
            conversation = self.conversations.get(conversation_id)
            if not conversation:
                logger.error(f"No conversation found for {conversation_id}", exc_info=True)
                raise ValueError(f"Conversation {conversation_id} not found")

            message = ConversationMessage(conversation_id=conversation_id, role=role, content=content)
            conversation.messages.append(message)

            # Update token count
            token_count = await self._estimate_tokens(content)
            conversation.token_count += token_count

            # Prune if needed
            await self._prune_history(conversation)

            logger.debug(f"Conversation length after adding a message: {len(conversation.messages)}")
        except ValidationError as e:
            logger.error(f"Error adding message: {e}, {conversation_id}, {role}, {content}", exc_info=True)
            raise

    async def add_pending_message(self, conversation_id: UUID, role: Role, content: Any) -> None:
        """Add message to pending state during tool use."""
        if conversation_id not in self.pending_messages:
            self.pending_messages[conversation_id] = []

        message = ConversationMessage(role=role, content=MessageContent.from_str(content))
        self.pending_messages[conversation_id].append(message)
        logger.info(f"Added pending message to conversation {conversation_id}: {message}")
        logger.debug(f"Pending messages: {self.pending_messages[conversation_id]}")

    async def commit_pending(self, conversation_id: UUID) -> None:
        """Commit pending messages to conversation history."""
        logger.debug(f"Number of pending messages: {len(self.pending_messages)}")

        if pending := self.pending_messages.pop(conversation_id, None):
            conversation = self.conversations.get(conversation_id)
            if conversation:
                conversation.messages.extend(pending)
                # Update token count
                for message in pending:
                    conversation.token_count += await self._estimate_tokens(message.content)
                await self._prune_history(conversation)

        logger.debug(f"Number of pending messages: {len(self.pending_messages)}")
        logger.debug(f"Number of messages in current conversation: {len(self.conversations[conversation_id].messages)}")

    async def rollback_pending(self, conversation_id: UUID) -> None:
        """Discard pending messages."""
        self.pending_messages.pop(conversation_id, None)

    async def _estimate_tokens(self, content: str | list[dict[str, Any]]) -> int:
        """Estimate token count for content."""
        if isinstance(content, str):
            return len(self.tokenizer.encode(content))
        elif isinstance(content, list):
            return sum(
                len(self.tokenizer.encode(item["text"]))
                for item in content
                if isinstance(item, dict) and "text" in item
            )
        return 0

    async def _prune_history(self, conversation: ConversationHistory) -> None:
        """Prune conversation history if it exceeds token limit."""
        while conversation.token_count > self.max_tokens * 0.9 and len(conversation.messages) > 1:
            removed_message = conversation.messages.pop(0)
            conversation.token_count -= await self._estimate_tokens(removed_message.content)

    async def get_conversation_with_pending(self, conversation_id: UUID | None) -> ConversationHistory:
        """
        Get a conversation history that includes both stable and pending messages.
        This creates a temporary copy for sending to the LLM.
        """
        conversation = self.conversations.get(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Create a copy of stable conversation
        combined = ConversationHistory(
            conversation_id=conversation.conversation_id,
            messages=conversation.messages.copy(),
            token_count=conversation.token_count,
        )

        # Add pending messages
        pending = self.pending_messages.get(conversation_id)
        if pending:
            combined.messages.extend(pending)

        return combined