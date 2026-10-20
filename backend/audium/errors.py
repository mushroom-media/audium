"""Domain errors raised by services; the API layer maps them to HTTP status codes."""


class AudiumError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", **details) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


class BadRequest(AudiumError):
    status = 400
    code = "bad_request"


class Unauthorized(AudiumError):
    status = 401
    code = "unauthorized"


class Forbidden(AudiumError):
    status = 403
    code = "forbidden"


class NotFound(AudiumError):
    status = 404
    code = "not_found"


class Conflict(AudiumError):
    status = 409
    code = "conflict"


class RateLimited(AudiumError):
    status = 429
    code = "rate_limited"

    def __init__(self, retry_after: int) -> None:
        super().__init__("too many attempts", retry_after=retry_after)
        self.retry_after = retry_after
