from fastapi import APIRouter, Depends

from app.models import User
from app.routers.auth import get_current_user
from app.schemas import UserPublic
from app.services import public_user

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/plan", response_model=UserPublic)
def plan(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(public_user(user))
