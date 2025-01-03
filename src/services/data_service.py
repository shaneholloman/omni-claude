from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from src.api.v0.schemas.chat_schemas import ConversationSummary
from src.api.v0.schemas.sources_schemas import AddContentSourceRequest
from src.core._exceptions import ConversationNotFoundError
from src.infrastructure.common.logger import get_logger
from src.infrastructure.storage.data_repository import DataRepository
from src.models.base_models import SupabaseModel
from src.models.chat_models import Conversation, ConversationHistory, ConversationMessage
from src.models.content_models import DataSource, Document, SourceSummary
from src.models.job_models import Job

logger = get_logger()

T = TypeVar("T", bound=SupabaseModel)


class DataService:
    """Service layer responsible for coordinating data operations and business logic.

    This service acts as an intermediary between the application and data access layer.
    It handles:
    - Business logic and validation
    - Data transformation and mapping
    - Coordination between multiple repositories if needed
    - Transaction management
    - Event emission for data changes

    The service uses DataRepository for actual database operations while focusing on
    higher-level business operations and data integrity.
    """

    def __init__(self, repository: DataRepository):
        self.repository = repository
        logger.debug("Initialized data service")

    # Core methods used by all services

    async def update_entity(self, model_class: type[T], entity_id: UUID, updates: dict[str, Any]) -> T:
        """Generic update operation for any entity."""
        # Get and validate current entity
        current = await self.repository.find_by_id(model_class, entity_id)

        # Create updated copy with validation
        updated = model_class.model_validate(current.model_dump())
        updated = updated.model_copy(update=updates)

        # Save and validate result
        result = await self.repository.save(updated)
        return model_class.model_validate(result.model_dump())

    async def save_job(self, job: Job) -> Job:
        """Save or update a job."""
        logger.debug(f"Saving job {job.job_id}")
        result = await self.repository.save(job)
        # Explicit type cast to satisfy mypy
        return Job.model_validate(result.model_dump())

    async def get_job(self, job_id: UUID) -> Job:
        """Get job by ID with proper type casting."""
        result = await self.repository.find_by_id(Job, job_id)
        # Explicit type cast to satisfy mypy
        return result

    async def get_by_firecrawl_id(self, firecrawl_id: str) -> Job | None:
        """Get job by FireCrawl ID with proper type casting."""
        jobs = await self.repository.find(Job, filters={"details->>firecrawl_id": firecrawl_id})
        if not jobs:
            return None
        return Job.model_validate(jobs[0].model_dump())

    async def save_datasource(self, data_source: DataSource) -> DataSource:
        """Save or update a data source."""
        logger.debug(f"Saving data source {data_source.source_id}")
        result = await self.repository.save(data_source)
        return DataSource.model_validate(result)

    async def update_datasource(self, source_id: UUID, updates: dict[str, Any]) -> DataSource:
        """Update a data source with new data."""
        result = await self.update_entity(DataSource, source_id, updates)
        return DataSource.model_validate(result)

    async def save_user_request(self, request: AddContentSourceRequest) -> AddContentSourceRequest:
        """Save user request."""
        logger.debug(f"Saving user request {request.request_id}")
        result = await self.repository.save(request)
        return result

    async def save_documents(self, documents: list[Document]) -> list[Document]:
        """Saves list of crawled documents."""
        logger.debug(f"Saving list of documents {len(documents)}")
        saved_documents = await self.repository.save(entity=documents)

        return [Document.model_validate(document) for document in saved_documents]

    async def list_datasources(self) -> list[DataSource]:
        """List all data sources."""
        results = await self.repository.find(DataSource)
        return results

    async def retrieve_datasource(self, source_id: UUID) -> DataSource:
        """Get data source by ID."""
        result = await self.repository.find_by_id(DataSource, source_id)
        return DataSource.model_validate(result)

    async def _load_summaries(self) -> list[SourceSummary]:
        """Load document summaries from Supabase storage."""
        result = await self.repository.find(SourceSummary)
        return result

    async def save_summaries(self, summaries: list[SourceSummary]) -> list[SourceSummary]:
        """Save document summaries to Supabase storage."""
        result = await self.repository.save(summaries)
        return result

    async def get_all_summaries(self) -> list[SourceSummary]:
        """Get all document summaries."""
        result = await self.repository.find(SourceSummary)
        return result

    async def clear_summaries(self) -> None:
        """Clear all document summaries."""
        pass

    async def get_documents_by_source(self, source_id: UUID) -> list[Document]:
        """Get documents by source ID."""
        documents = await self.repository.find(Document, filters={"source_id": source_id})
        return [Document.model_validate(document) for document in documents]

    async def update_document_status(self, document_id: UUID, error: str | None = None) -> None:
        """Update document status."""
        await self.update_entity(Document, document_id, {"error": error})

    async def get_conversations(self, user_id: UUID) -> list[ConversationSummary]:
        """Get all conversations for a user."""
        conversations = await self.repository.find(Conversation, filters={"user_id": str(user_id)})
        return [
            ConversationSummary(
                conversation_id=c.conversation_id,
                title=c.title,
                data_sources=c.data_sources,
                updated_at=c.updated_at,
            )
            for c in conversations
        ]

    async def get_conversation(self, conversation_id: UUID) -> Conversation:
        """Get a single conversation by its ID in accordance with RLS policies."""
        conversation = await self.repository.find_by_id(Conversation, conversation_id)
        return conversation

    async def get_conversation_history(self, conversation_id: UUID) -> ConversationHistory:
        """Get a single conversation history by its ID in accordance with RLS policies."""
        try:
            # Find messages next
            messages = await self.repository.find(ConversationMessage, filters={"conversation_id": conversation_id})
            # Create ConversationHistory model
            conversation_history = ConversationHistory(
                messages=messages,
            )
            # Return it
            return conversation_history
        except ConversationNotFoundError:
            logger.error(f"Conversation with id {conversation_id} not found", exc_info=True)
            raise ConversationNotFoundError(f"Conversation with id {conversation_id} not found") from e

    async def update_conversation_supabase(
        self, history: ConversationHistory, messages: list[ConversationMessage]
    ) -> None:
        """Update conversation in Supabase."""
        await self.update_conversation(history, messages)
        await self.save_messages(messages)

    async def update_conversation(self, history: ConversationHistory, messages: list[ConversationMessage]) -> None:
        """Update conversation in Supabase."""
        # Extract message IDs from the new messages
        new_message_ids = [message.message_id for message in messages]

        # Get the current conversation
        conversation = await self.get_conversation(history.conversation_id)

        # Append new message IDs to existing message IDs
        conversation.message_ids.extend(new_message_ids)
        conversation.token_count = history.token_count
        conversation.updated_at = datetime.now(UTC)

        # Save updated conversation
        await self.repository.save(conversation)

    async def save_messages(self, messages: list[ConversationMessage]) -> None:
        """Save messages to Supabase."""
        await self.repository.save(messages)

    async def save_conversation(self, conversation: Conversation) -> None:
        """Save conversation to Supabase."""
        await self.repository.save(conversation)
