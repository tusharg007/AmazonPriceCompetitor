"""Public application errors and sanitized database failure translation."""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class ApplicationError(Exception):
    def __init__(self, message: str, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class NotFoundError(ApplicationError):
    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} not found", "not_found", 404)


class InputError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "invalid_input", 422)


class CooldownError(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "Marketplace collection is cooling down after an access block", "cooldown", 429
        )
        self.retry_after = retry_after


class EvidenceError(ApplicationError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message, "evidence_unavailable", status_code)


class LeaseLostError(RuntimeError):
    """A stale worker must stop collecting and cannot publish observations or job results."""


def database_error(exc: SQLAlchemyError) -> ApplicationError:
    if isinstance(exc, IntegrityError):
        return ApplicationError("Database operation conflicts with stored data", "conflict", 409)
    return ApplicationError("Database temporarily unavailable", "database_unavailable", 503)
