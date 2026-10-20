from fastapi import APIRouter, Depends, Query

from audium.api.deps import get_db, require_admin
from audium.api.models import (
    InviteCreate,
    InviteCreated,
    InviteOut,
    Ok,
    Page,
    UserCreate,
    UserOut,
    UserUpdate,
)
from audium.db.engine import Database
from audium.services import users as user_service
from audium.services.users import User

router = APIRouter(prefix="/admin", tags=["admin: users"])


@router.get("/users", response_model=Page[UserOut])
def list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    with db.read() as conn:
        items, total = user_service.list_users(conn, limit, offset)
    # User lists are small; plain offset paging is enough here.
    return Page[UserOut](items=[UserOut(**u.__dict__) for u in items], total=total)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        user = user_service.create_user(conn, body.username, body.password, body.role, body.display_name)
    return UserOut(**user.__dict__)


@router.patch("/users/{user_id}", response_model=UserOut, summary="Change role, lock/unlock, reset password")
def update_user(user_id: int, body: UserUpdate, admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        user = user_service.update_user(
            conn,
            admin,
            user_id,
            role=body.role,
            status=body.status,
            display_name=body.display_name,
            password=body.password,
        )
    return UserOut(**user.__dict__)


@router.get("/invites", response_model=list[InviteOut])
def list_invites(_admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.read() as conn:
        return [InviteOut(**r._mapping) for r in user_service.list_invites(conn)]


@router.post("/invites", response_model=InviteCreated, status_code=201)
def create_invite(body: InviteCreate, admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        invite_id, token = user_service.create_invite(conn, admin, body.role, body.ttl_hours)
        row = next(r for r in user_service.list_invites(conn) if r.id == invite_id)
    return InviteCreated(**row._mapping, token=token)


@router.delete("/invites/{invite_id}", response_model=Ok)
def revoke_invite(invite_id: int, _admin: User = Depends(require_admin), db: Database = Depends(get_db)):
    with db.write() as conn:
        user_service.revoke_invite(conn, invite_id)
    return Ok()
