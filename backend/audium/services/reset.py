"""Reset to factory settings (Einstellungen > Zurücksetzen, admins only).

Empties the library, the analysis, playlists, server settings and jobs; the music files are only
read and stay as they are. The user accounts stay if the admin wants (with their own settings
and app passwords for Subsonic), but everyone is logged out, the audium apps and API tokens too.
Without them, only the admin from
AUDIUM_ADMIN_USER/PASSWORD remains (created again if it is gone). Afterwards the first-run
dialog is open again, as on a new installation.

Cover files stay on disk: they are named by their content, so the next scan finds them again
(and the scan worker remembers which ones it already rendered).
"""

from sqlalchemy import Connection, select, text, update

from audium.analysis.similarity import ANALYSIS_GENERATION
from audium.analysis.tasks import BACKEND_STATE, GENRES_DONE_STATE
from audium.auth import passwords
from audium.config import Settings
from audium.db.schema import app_passwords, app_state, jobs, metadata, user_settings, users
from audium.db.state import LIBRARY_GENERATION, RESET_STATE, bump_library_generation, set_state
from audium.errors import Forbidden
from audium.logging import get_logger
from audium.services import auth as auth_service
from audium.services import users as user_service
from audium.services.users import User
from audium.util import now_ms

log = get_logger(__name__)

_ACCOUNT_TABLES = frozenset({users.name, user_settings.name, app_passwords.name})
# Bookkeeping of the processes, not settings: what they found at their start, when they last ran.
# The generations count on, so the caches see a change and never a number they had before.
_KEEP_STATE = (BACKEND_STATE, GENRES_DONE_STATE, "maintenance.last_run", LIBRARY_GENERATION, ANALYSIS_GENERATION)
_FTS_TABLES = ("tracks_fts", "albums_fts", "artists_fts")


def reset_server(conn: Connection, settings: Settings, admin: User, password: str, keep_users: bool) -> None:
    row = conn.execute(select(users.c.password_hash).where(users.c.id == admin.id)).first()
    if row is None or not passwords.verify_password(row.password_hash, password):
        raise Forbidden("the password is wrong")

    # A running job cannot be stopped from here; it sees the request at its next progress report.
    conn.execute(update(jobs).where(jobs.c.status == "running").values(cancel_requested=True))
    conn.execute(jobs.delete().where(jobs.c.status != "running"))

    keep = _ACCOUNT_TABLES if keep_users else _ACCOUNT_TABLES - {users.name}
    for table in reversed(metadata.sorted_tables):  # children first
        if table.name not in keep and table not in (app_state, jobs):
            conn.execute(table.delete())
    if conn.dialect.name == "sqlite":
        for fts in _FTS_TABLES:
            conn.execute(text(f"DELETE FROM {fts}"))
    if not keep_users:
        _keep_env_admin_only(conn, settings)

    conn.execute(
        app_state.delete().where(app_state.c.key.not_in(_KEEP_STATE), app_state.c.key.not_like("worker.%.heartbeat"))
    )
    bump_library_generation(conn)
    set_state(conn, ANALYSIS_GENERATION, str(now_ms()))
    set_state(conn, auth_service.SETUP_STATE_KEY, "pending")
    set_state(conn, RESET_STATE, str(now_ms()))
    log.warning("server.reset", by=admin.username, keep_users=keep_users)


def _keep_env_admin_only(conn: Connection, settings: Settings) -> None:
    if not (settings.admin_user and settings.admin_password):
        conn.execute(users.delete())
        return
    name = user_service.normalize_username(settings.admin_user)
    conn.execute(users.delete().where(users.c.username != name))
    if user_service.count_users(conn) == 0:
        user_service.create_user(conn, settings.admin_user, settings.admin_password, role="admin")
    else:
        conn.execute(update(users).values(role="admin", status="active"))
