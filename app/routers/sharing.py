from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.library_files import read_owned_file
from app.rate_limit import enforce_rate_limit
from app.schemas import ShareOpenRequest
from app.shares import open_share

router = APIRouter(prefix="/shared", tags=["sharing"])


def shared_file(share, document):
    inline = share.permission == "view"
    return FileResponse(
        read_owned_file(document.user_id, document.storage_key),
        media_type=document.mime_type,
        filename=document.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/{token}")
def open_with_password(token: str, body: ShareOpenRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, "share")
    share, document = open_share(db, token, body.password)
    return shared_file(share, document)


@router.get("/{token}")
def open_public(token: str, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, "share")
    share, document = open_share(db, token, None)
    return shared_file(share, document)
