from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from app.services import authenticate, issue_session, public_user, register_user, resolve_session, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def presented_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return request.cookies.get(get_settings().cookie_name)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = presented_token(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return resolve_session(db, token)


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_minutes * 60,
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    user = register_user(db, body.name, str(body.email), body.password)
    token = issue_session(db, user)
    set_session_cookie(response, token)
    return AuthResponse(user=UserPublic.model_validate(public_user(user)))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    user = authenticate(db, str(body.email), body.password)
    token = issue_session(db, user)
    set_session_cookie(response, token)
    return AuthResponse(user=UserPublic.model_validate(public_user(user)))


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(public_user(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Response:
    token = presented_token(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    revoke_session(db, token)
    settings = get_settings()
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    result.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure, samesite="lax", httponly=True)
    return result
