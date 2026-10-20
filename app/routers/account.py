from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.account_service import change_password, complete_onboarding, delete_account, export_account, list_sessions, revoke_other_sessions, update_profile
from app.database import get_db
from app.models import User
from app.rate_limit import enforce_rate_limit
from app.routers.auth import get_current_user
from app.schemas import AccountDeleteRequest, OnboardingRequest, PasswordChange, ProfileUpdate, SessionPublic, UserPublic
from app.services import public_user

router = APIRouter(prefix="/account", tags=["account"])


def current_session_id(request: Request):
    return getattr(request.state, "session_id", None)


@router.get("/plan", response_model=UserPublic)
def plan(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(public_user(user))


@router.patch("/profile", response_model=UserPublic)
def patch_profile(body: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserPublic:
    updated = update_profile(db, user, body.model_dump(exclude_unset=True))
    return UserPublic.model_validate(public_user(updated))


@router.post("/onboarding", response_model=UserPublic)
def post_onboarding(body: OnboardingRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserPublic:
    updated = complete_onboarding(db, user, body.audience, body.timezone_name, body.skip)
    return UserPublic.model_validate(public_user(updated))


@router.post("/password", status_code=204)
def post_password(
    body: PasswordChange,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    enforce_rate_limit(request, "auth")
    change_password(db, user, body.current_password, body.new_password, current_session_id(request))


@router.get("/sessions", response_model=list[SessionPublic])
def get_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SessionPublic]:
    current = current_session_id(request)
    return [
        SessionPublic(
            id=item.id,
            created_at=item.created_at,
            expires_at=item.expires_at,
            revoked_at=item.revoked_at,
            current=item.id == current,
        )
        for item in list_sessions(db, user)
    ]


@router.post("/sessions/revoke-others", status_code=204)
def post_revoke_others(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    revoke_other_sessions(db, user, current_session_id(request))


@router.get("/export")
def get_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JSONResponse:
    response = JSONResponse(export_account(db, user))
    response.headers["Content-Disposition"] = 'attachment; filename="docsmio-export.json"'
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.delete("", status_code=204)
def remove_account(
    body: AccountDeleteRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    enforce_rate_limit(request, "auth")
    delete_account(db, user, body.password, body.confirm)
