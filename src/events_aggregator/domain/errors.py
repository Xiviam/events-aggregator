class DomainError(Exception):
    """Base class for expected application errors."""


class EventNotFoundError(DomainError):
    pass


class TicketNotFoundError(DomainError):
    pass


class EventUnavailableError(DomainError):
    pass


class RegistrationClosedError(DomainError):
    pass


class SyncInProgressError(DomainError):
    pass


class ProviderError(DomainError):
    """The provider could not complete a request."""


class ProviderNotFoundError(ProviderError):
    pass


class ProviderConflictError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class PaginationLoopError(ProviderResponseError):
    pass
