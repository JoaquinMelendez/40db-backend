class DomainError(Exception):
    code: str = "domain_error"
    http_status: int = 500

    def __init__(self, message: str = "", details=None):
        super().__init__(message)
        self.details = details


class NotFoundError(DomainError):
    code = "not_found"
    http_status = 404


class UnauthorizedError(DomainError):
    code = "unauthorized"
    http_status = 401


class ForbiddenError(DomainError):
    code = "forbidden"
    http_status = 403


class ValidationError(DomainError):
    code = "validation_error"
    http_status = 409


class InvalidStateTransitionError(ValidationError):
    code = "invalid_state_transition"


class ConflictError(DomainError):
    code = "conflict"
    http_status = 409


class ExternalServiceError(DomainError):
    code = "external_service_error"
    http_status = 503


# ── Subtipos específicos ──────────────────────────────────────────────────────

class ReporteNotFoundError(NotFoundError):
    code = "reporte_not_found"


class UsuarioNotFoundError(NotFoundError):
    code = "usuario_not_found"


class ComunaMismatchError(ForbiddenError):
    code = "comuna_mismatch"


class InvalidTokenError(UnauthorizedError):
    code = "invalid_token"
