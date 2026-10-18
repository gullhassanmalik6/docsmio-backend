import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user
from app.schemas import HistoryCreate, HistoryItem, HistoryPage
from app.services import create_history, delete_history, get_owned_history, list_history

router = APIRouter(prefix="/history", tags=["history"])


def to_item(record) -> HistoryItem:
    return HistoryItem.model_validate(record)


@router.get("", response_model=HistoryPage)
def list_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    operation_type: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryPage:
    rows, total = list_history(db, user, page, page_size, operation_type, status_filter)
    return HistoryPage(items=[to_item(row) for row in rows], page=page, page_size=page_size, total=total)


@router.post("", response_model=HistoryItem, status_code=status.HTTP_201_CREATED)
def create_record(body: HistoryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> HistoryItem:
    record = create_history(db, user, body.original_filename, body.operation_type, body.original_size, body.output_size, body.status)
    return to_item(record)


@router.get("/{record_id}", response_model=HistoryItem)
def get_record(record_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> HistoryItem:
    return to_item(get_owned_history(db, user, record_id))


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_record(record_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    delete_history(db, user, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
