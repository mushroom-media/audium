"""Registration and dispatch: every endpoint answers at /rest/<name> and /rest/<name>.view,
by GET or by form POST. Handlers are sync functions (they use the database) and run in the
threadpool like the def endpoints of the web API."""

from collections.abc import Callable
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from audium.api.subsonic import envelope
from audium.api.subsonic.auth import authenticate
from audium.api.subsonic.envelope import SubsonicError
from audium.config import Settings
from audium.db.engine import Database
from audium.errors import AudiumError
from audium.services import view_prefs
from audium.services.server_settings import server_setting
from audium.services.users import User

_HANDLERS: dict[str, tuple[Callable[["Call"], dict | Response], bool]] = {}

_FORMATS = ("json", "xml")


class Call:
    """One request: its parameters (names may repeat, e.g. star?id=1&id=2; the body wins over
    the query) and, once authenticated, the user."""

    def __init__(self, pairs: list[tuple[str, str]], request: Request) -> None:
        self._pairs = pairs
        self.request = request
        self.user: User = None  # type: ignore[assignment] - set by dispatch before the handler runs

    @property
    def state(self):
        return self.request.app.state

    @property
    def db(self) -> Database:
        return self.state.db

    @property
    def settings(self) -> Settings:
        return self.state.settings

    @property
    def client(self) -> str | None:
        """The app's name (parameter c), e.g. "Symfonium"."""
        c = self.get("c")
        return (c.strip()[:64] or None) if c else None

    def get(self, name: str, default: str | None = None) -> str | None:
        for key, value in reversed(self._pairs):
            if key == name:
                return value
        return default

    def getall(self, name: str) -> list[str]:
        return [value for key, value in self._pairs if key == name and value != ""]

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None or value == "":
            raise SubsonicError(envelope.MISSING_PARAMETER, f"required parameter is missing: {name}")
        return value

    def int(self, name: str, default: int | None = None, lo: int | None = None, hi: int | None = None) -> int | None:
        """An integer parameter, clamped to [lo, hi]."""
        raw = self.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise SubsonicError(envelope.GENERIC, f"parameter {name} must be a number") from exc
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)
        return value

    def bool(self, name: str, default: bool = False) -> bool:
        raw = self.get(name)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in ("true", "1", "yes")


def endpoint(name: str, *, auth: bool = True):
    def register(fn):
        _HANDLERS[name] = (fn, auth)
        return fn

    return register


def make_router() -> APIRouter:
    router = APIRouter(prefix="/rest", include_in_schema=False)

    @router.api_route("/{name}", methods=["GET", "POST"])
    async def dispatch(name: str, request: Request) -> Response:
        pairs = list(request.query_params.multi_items())
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if request.method == "POST" and content_type == "application/x-www-form-urlencoded":
            pairs += parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
        call = Call(pairs, request)

        fmt = call.get("f") or "xml"
        if fmt not in _FORMATS:
            return envelope.failed(SubsonicError(envelope.GENERIC, f"unsupported format: {fmt}"), "xml")
        entry = _HANDLERS.get(name.removesuffix(".view"))
        if entry is None:
            return envelope.failed(SubsonicError(envelope.GENERIC, f"not supported: {name}"), fmt)
        handler, needs_auth = entry
        try:
            result = await run_in_threadpool(_run, handler, needs_auth, call)
        except SubsonicError as exc:
            return envelope.failed(exc, fmt)
        except AudiumError as exc:
            return envelope.failed(_from_domain(exc), fmt)
        return result if isinstance(result, Response) else envelope.ok(result, fmt)

    return router


def _run(handler, needs_auth: bool, call: Call):
    with call.db.read() as conn:
        if server_setting(conn, "subsonic_api") != "on":
            raise SubsonicError(envelope.GENERIC, "the Subsonic API is turned off on this server")
    if needs_auth:
        call.user = authenticate(call)
        with call.db.read() as conn:
            view_prefs.apply(conn, call.user.id)  # same context as the handler: it runs right here
    return handler(call)


def _from_domain(exc: AudiumError) -> SubsonicError:
    code = {401: envelope.WRONG_CREDENTIALS, 403: envelope.NOT_AUTHORIZED, 404: envelope.NOT_FOUND}
    return SubsonicError(code.get(exc.status, envelope.GENERIC), exc.message)
