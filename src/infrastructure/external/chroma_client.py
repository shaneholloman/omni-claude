import chromadb
from chromadb.api.async_api import AsyncClientAPI

from src.infrastructure.common.logger import get_logger
from src.infrastructure.config.settings import settings

logger = get_logger()


class ChromaClient:
    """Thin async client for ChromaDB."""

    def __init__(self) -> None:
        """Initialize ChromaClient with the necessary dependencies."""
        self.client: AsyncClientAPI | None = None

    @classmethod
    async def create_client(cls, host: str = settings.chroma_host, port: int = settings.chroma_port) -> "ChromaClient":
        """Create a new asyncChroma client."""
        instance = cls()
        instance.client = await chromadb.AsyncHttpClient(host=host, port=port)
        logger.info(f"Chroma client initialized with host: {host} and port: {port}")
        await instance.client.heartbeat()
        return instance
