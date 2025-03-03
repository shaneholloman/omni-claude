from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel
from redis.asyncio import Redis as AsyncRedis

from src.infra.external.redis_manager import RedisManager
from src.infra.logger import get_logger
from src.models.chat_models import ConversationHistory, ConversationMessage

logger = get_logger()

T = TypeVar("T", bound=BaseModel)  # T can be any type that is a sub class of BaseModel == all data models


# model[T] == instance of a model
# type[T] == class of a model


class RedisRepository:
    """Asynchronous Redis repository for storing and retrieving data.

    This repository manages two main types of data structures in Redis:
    1. Key-Value Pairs (SET/GET):
       - Used for conversation history
       - Key format: conversations:{conversation_id}:history
       - Value: JSON serialized ConversationHistory
       - TTL: 24 hours

    2. Lists (RPUSH/LRANGE):
       - Used for pending messages
       - Key format: conversations:{conversation_id}:pending_messages
       - Value: List of JSON serialized ConversationMessage
       - TTL: 1 hour

    Key Patterns:
    - Each model type has a defined prefix pattern in prefix_config
    - Keys are constructed as: prefix.format(conversation_id=uuid)

    Usage Examples:
    ```python
    # Store conversation history
    await repo.set_method(
        key=conversation_id,
        value=conversation_history,  # ConversationHistory instance
    )

    # Add pending message
    await repo.rpush_method(
        key=conversation_id,
        value=message,  # ConversationMessage instance
    )

    # Get conversation history
    history = await repo.get_method(key=conversation_id, model_class=ConversationHistory)

    # Get all pending messages
    messages = await repo.lrange_method(key=conversation_id, start=0, end=-1, model_class=ConversationMessage)
    ```

    Pipeline Support:
    - Supports Redis transactions through pipeline operations
    - Use create_pipeline() to start a transaction
    - Pass the pipeline to methods that support it (set_method, delete_method)

    Error Handling:
    - Methods return None if key doesn't exist
    - Raises ValueError for undefined model prefixes/TTLs
    - Redis connection errors are propagated up
    """

    def __init__(self, manager: RedisManager):
        self.manager = manager
        self.prefix_config = {
            ConversationHistory: "conversations:{conversation_id}:history",
            ConversationMessage: "conversations:{conversation_id}:pending_messages",
        }
        self.ttl_config = {
            ConversationHistory: 60 * 60 * 24,  # 1 day
            ConversationMessage: 60 * 60,  # 1 hour
        }

    def _get_prefix(self, model_class: type[T], **kwargs: Any) -> str:
        """Get the prefix for the model.

        Args:
            model_class: The class of the model (e.g., ConversationHistory)
            **kwargs: Key-value pairs to format the prefix template
                     (e.g., conversation_id=uuid)

        Returns:
            str: Formatted Redis key (e.g., "conversations:123:history")

        Raises:
            ValueError: If no prefix is defined for the model class
        """
        try:
            prefix_template = self.prefix_config[model_class]
            return prefix_template.format(**kwargs)
        except KeyError:
            logger.error(f"No key prefix defined for model class: {model_class.__name__}", exc_info=True)
            raise ValueError(f"No key prefix defined for model class: {model_class.__name__}")

    def _get_ttl(self, model_class: type[T]) -> int:
        """Get TTL for the model.

        Args:
            model_class: The class of the model

        Returns:
            int: TTL in seconds

        Raises:
            ValueError: If no TTL is defined for the model class
        """
        try:
            return self.ttl_config[model_class]
        except KeyError:
            raise ValueError(f"No TTL defined for model class: {model_class.__name__}")

    def _to_json(self, model: T) -> str:
        """Convert a model to a JSON string.

        Args:
            model: Pydantic model instance to serialize

        Returns:
            str: JSON string representation of the model
        """
        json_str = model.model_dump_json(by_alias=True, serialize_as_any=True)
        return json_str

    def _from_json(self, json_str: str, model_class: type[T]) -> T:
        """Convert a JSON string to a model.

        Args:
            json_str: JSON string to deserialize
            model_class: The class to deserialize into

        Returns:
            T: Instance of model_class
        """
        result = model_class.model_validate_json(json_str)
        return result

    async def create_pipeline(self, transaction: bool = True) -> AsyncRedis:
        """Create a new pipeline"""
        client = await self.manager.get_async_client()
        return client.pipeline(transaction=transaction)

    async def set_method(self, key: UUID, value: T, pipe: AsyncRedis | None = None) -> None:
        """Set a value in the Redis database, optionally as part of pipeline."""
        prefix = self._get_prefix(type(value), conversation_id=key)
        ttl = self._get_ttl(type(value))
        if pipe:
            await pipe.set(prefix, self._to_json(value), ex=ttl)
            logger.debug(f"Pipeline: SET {prefix} (TTL: {ttl}s)")
        else:
            client = await self.manager.get_async_client()
            await client.set(prefix, self._to_json(value), ex=ttl)
            logger.info(f"SET {prefix} (TTL: {ttl}s)")

    async def get_method(self, key: UUID, model_class: type[T]) -> T | None:
        """Get a value from the Redis database."""
        prefix = self._get_prefix(model_class, conversation_id=key)
        client = await self.manager.get_async_client()
        data = await client.get(prefix)
        if data is None:
            logger.debug(f"GET {prefix}: Key not found")
            return None
        logger.debug(f"GET {prefix}: Found")
        return self._from_json(data, model_class)

    async def rpush_method(self, key: UUID, value: T) -> None:
        """Push a value to the end of a list."""
        prefix = self._get_prefix(type(value), conversation_id=key)
        ttl = self._get_ttl(type(value))
        client = await self.manager.get_async_client()
        await client.rpush(prefix, self._to_json(value))
        await client.expire(prefix, ttl)
        logger.info(f"RPUSH {prefix} (TTL: {ttl}s)")

    async def lrange_method(self, key: UUID, start: int, end: int, model_class: type[T]) -> list[T]:
        """Retrieve a range of elements from a list."""
        prefix = self._get_prefix(model_class, conversation_id=key)
        client = await self.manager.get_async_client()
        items = await client.lrange(prefix, start, end)
        logger.debug(f"LRANGE {prefix} [{start}:{end}]: {len(items)} items")
        return [self._from_json(item, model_class) for item in items]

    async def delete_method(self, key: UUID, model_class: type[T], pipe: AsyncRedis | None = None) -> None:
        """Delete a key from the Redis database."""
        prefix = self._get_prefix(model_class=model_class, conversation_id=key)
        if pipe:
            await pipe.delete(prefix)
            logger.debug(f"Pipeline: DELETE {prefix}")
        else:
            client = await self.manager.get_async_client()
            await client.delete(prefix)
            logger.info(f"DELETE {prefix}")

    async def lpop_method(self, key: UUID, model_class: type[T]) -> T | None:
        """Pop the first element from a list."""
        prefix = self._get_prefix(model_class, conversation_id=key)
        client = await self.manager.get_async_client()
        data = await client.lpop(prefix)
        if data is None:
            logger.debug(f"LPOP {prefix}: Empty list")
            return None
        logger.debug(f"LPOP {prefix}: Popped item")
        return self._from_json(data, model_class)

    async def rpop_method(self, key: UUID, model_class: type[T]) -> T | None:
        """Pop the last element from a list."""
        prefix = self._get_prefix(model_class, conversation_id=key)
        client = await self.manager.get_async_client()
        data = await client.rpop(prefix)
        if data is None:
            logger.debug(f"RPOP {prefix}: Empty list")
            return None
        logger.debug(f"RPOP {prefix}: Popped item")
        return self._from_json(data, model_class)
