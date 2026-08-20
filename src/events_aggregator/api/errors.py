from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from events_aggregator.domain.errors import (
    EventNotFoundError,
    EventUnavailableError,
    ProviderConflictError,
    ProviderError,
    ProviderNotFoundError,
    RegistrationClosedError,
    SyncInProgressError,
    TicketNotFoundError,
)


async def _not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


async def _provider_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": str(exc)},
    )


async def _sync_in_progress_handler(request: Request, exc: Exception) -> JSONResponse:
    del request, exc
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "already_running"},
    )


async def _validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": jsonable_encoder(exc.errors())},
    )


def register_error_handlers(application: FastAPI) -> None:
    for error_type in (EventNotFoundError, TicketNotFoundError, ProviderNotFoundError):
        application.add_exception_handler(error_type, _not_found_handler)
    for error_type in (
        EventUnavailableError,
        RegistrationClosedError,
        ProviderConflictError,
    ):
        application.add_exception_handler(error_type, _conflict_handler)
    application.add_exception_handler(SyncInProgressError, _sync_in_progress_handler)
    application.add_exception_handler(ProviderError, _provider_error_handler)
    application.add_exception_handler(RequestValidationError, _validation_error_handler)
