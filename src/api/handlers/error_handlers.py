from fastapi import Request
from fastapi.responses import JSONResponse

from src.api.v0.schemas.base_schemas import ErrorCode, ErrorResponse
from src.core._exceptions import NonRetryableError
from src.infra.logger import get_logger

logger = get_logger()


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for any unhandled exceptions."""
    logger.critical(f"Unhandled exception at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=ErrorCode.SERVER_ERROR, detail="An internal server error occurred, please contact support."
        ),
    )


async def non_retryable_exception_handler(request: Request, exc: NonRetryableError) -> JSONResponse:
    """Catch and log a non-retryable error."""
    logger.error(f"Non-retryable error at {request.url.path}: {exc.error_message}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=ErrorCode.SERVER_ERROR,
            detail=f"An internal error occurred while processing your request: {exc.error_message}.",
        ),
    )
