from supabase import AsyncClient, create_async_client

from src.infrastructure.common.logger import get_logger
from src.infrastructure.config.settings import settings

logger = get_logger()


class SupabaseClient:
    """Efficient Supabase client with immediate connection initialization."""

    def __init__(self, url: str = settings.supabase_url, key: str = settings.supabase_key) -> None:
        """Initialize Supabase client and connect immediately."""
        self.url = url
        self.key = key
        self._client: AsyncClient | None = None

    async def connect(self) -> None:
        """Connect to Supabase, handling potential errors."""
        if self._client is None:  # Only connect if not already connected
            try:
                logger.info(
                    f"Attempting to connect to Supabase at: {self.url} with key partially masked as: {self.key[:5]}..."
                )
                self._client = await create_async_client(
                    supabase_url=self.url,
                    supabase_key=self.key,
                )
                logger.info("Connected to Supabase successfully.")
            except Exception as e:
                logger.error(f"Unexpected error connecting to Supabase: {e}", exc_info=True)
                raise

    async def get_client(self) -> AsyncClient:
        """Get the connected client instance."""
        if self._client is None:
            await self.connect()
        return self._client


supabase_client = SupabaseClient()
