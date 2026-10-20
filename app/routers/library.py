import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.classify import SUGGESTED_CATEGORIES
from app.database import get_db
from app.library_files import delete_owned_file, read_owned_file, save_upload
from app.library_service import (
    add_document,
    assert_storage_room,
    create_category,
    create_folder,
    delete_category,
    delete_folder,
    ensure_folders,
    find_duplicate,
    list_categories,
    move_folder,
    owned_document,
    owned_folder,
    purge_document,
    query_documents,
    remove_document,
    rename_folder,
    reorder_folder,
    reprocess_document,
    restore_document,
    store_document_text,
    update_document,
)
from app.models import User
from app.rate_limit import enforce_rate_limit
from app.routers.auth import get_current_user
from app.schemas import (
    CategoryCreate,
    CategoryList,
    CategoryPublic,
    LibraryDocumentDetail,
    LibraryDocumentPublic,
    LibraryDocumentUpdate,
    LibraryFolderCreate,
    LibraryFolderPublic,
    LibraryFolderUpdate,
    LibrarySearchPage,
    ShareCreate,
    ShareCreated,
    SharePublic,
    TextSubmit,
)
from app.shares import create_share, list_shares, revoke_share

router = APIRouter(prefix="/library", tags=["library"])


def folder_out(folder) -> LibraryFolderPublic:
    return LibraryFolderPublic.model_validate(folder)


def document_out(document) -> LibraryDocumentPublic:
    return LibraryDocumentPublic.model_validate(document)


def file_response(document, path, inline: bool) -> FileResponse:
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/folders", response_model=list[LibraryFolderPublic])
def get_folders(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LibraryFolderPublic]:
    return [folder_out(folder) for folder in ensure_folders(db, user)]


@router.post("/folders", response_model=LibraryFolderPublic, status_code=201)
def post_folder(body: LibraryFolderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> LibraryFolderPublic:
    return folder_out(create_folder(db, user, body.name, body.parent_id))


@router.patch("/folders/{folder_id}", response_model=LibraryFolderPublic)
def patch_folder(
    folder_id: uuid.UUID,
    body: LibraryFolderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LibraryFolderPublic:
    if body.name is not None:
        rename_folder(db, user, folder_id, body.name)
    if "parent_id" in body.model_fields_set:
        move_folder(db, user, folder_id, body.parent_id)
    if body.sort_order is not None:
        reorder_folder(db, user, folder_id, body.sort_order)
    return folder_out(owned_folder(db, user, folder_id))


@router.delete("/folders/{folder_id}", status_code=204)
def remove_folder(
    folder_id: uuid.UUID,
    disposition: str = Query(default="uncategorized", pattern="^(uncategorized|delete)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    delete_folder(db, user, folder_id, disposition)


@router.get("/categories", response_model=CategoryList)
def get_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CategoryList:
    return CategoryList(suggested=SUGGESTED_CATEGORIES, custom=[CategoryPublic.model_validate(item) for item in list_categories(db, user)])


@router.post("/categories", response_model=CategoryPublic, status_code=201)
def post_category(body: CategoryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CategoryPublic:
    return CategoryPublic.model_validate(create_category(db, user, body.name))


@router.delete("/categories/{category_id}", status_code=204)
def remove_category(category_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    delete_category(db, user, category_id)


@router.get("/documents", response_model=list[LibraryDocumentPublic])
def get_documents(
    folder_id: uuid.UUID | None = None,
    favorite: bool | None = None,
    q: str | None = None,
    sort: str = Query(default="added", pattern="^(added|updated|name|size|type)$"),
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    trash: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[LibraryDocumentPublic]:
    ensure_folders(db, user)
    rows, _total = query_documents(db, user, folder_id, favorite, q, sort, limit, offset, trash)
    return [document_out(document) for document in rows]


@router.get("/search", response_model=LibrarySearchPage)
def search_documents(
    folder_id: uuid.UUID | None = None,
    favorite: bool | None = None,
    q: str | None = None,
    sort: str = Query(default="added", pattern="^(added|updated|name|size|type)$"),
    mime: str | None = Query(default=None, pattern="^(pdf|image)$"),
    category: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    trash: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LibrarySearchPage:
    ensure_folders(db, user)
    rows, total = query_documents(db, user, folder_id, favorite, q, sort, page_size, (page - 1) * page_size, trash, category, mime)
    return LibrarySearchPage(items=[document_out(document) for document in rows], page=page, page_size=page_size, total=total)


@router.post("/documents", response_model=LibraryDocumentPublic, status_code=201)
async def post_document(
    request: Request,
    folder_id: uuid.UUID = Form(),
    classification_key: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    category: str | None = Form(default=None),
    upload: UploadFile = File(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LibraryDocumentPublic:
    enforce_rate_limit(request, "upload")
    ensure_folders(db, user)
    storage_key, mime_type, size, filename, digest = await save_upload(user.id, upload)
    try:
        assert_storage_room(db, user, size)
        duplicate = find_duplicate(db, user, digest)
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'This file is already in your library as "{duplicate.filename}".',
            )
        document = add_document(db, user, folder_id, filename, mime_type, size, storage_key, classification_key, digest, notes, tags, category)
    except Exception:
        delete_owned_file(user.id, storage_key)
        raise
    return document_out(document)


@router.patch("/documents/{document_id}", response_model=LibraryDocumentPublic)
def patch_document(
    document_id: uuid.UUID,
    body: LibraryDocumentUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LibraryDocumentPublic:
    return document_out(update_document(db, user, document_id, body.model_dump(exclude_unset=True)))


@router.get("/documents/{document_id}", response_model=LibraryDocumentDetail)
def get_document(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> LibraryDocumentDetail:
    return LibraryDocumentDetail.model_validate(owned_document(db, user, document_id))


@router.post("/documents/{document_id}/text", response_model=LibraryDocumentDetail)
def post_text(
    document_id: uuid.UUID,
    body: TextSubmit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LibraryDocumentDetail:
    return LibraryDocumentDetail.model_validate(store_document_text(db, user, document_id, body.text))


@router.post("/documents/{document_id}/reprocess", response_model=LibraryDocumentDetail)
def post_reprocess(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> LibraryDocumentDetail:
    return LibraryDocumentDetail.model_validate(reprocess_document(db, user, document_id))


@router.get("/documents/{document_id}/file")
def download_document(
    document_id: uuid.UUID,
    disposition: str = Query(default="attachment", pattern="^(attachment|inline)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    document = owned_document(db, user, document_id)
    if disposition == "inline" and document.mime_type not in {"application/pdf", "image/jpeg", "image/png", "image/webp"}:
        disposition = "attachment"
    return file_response(document, read_owned_file(user.id, document.storage_key), disposition == "inline")


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: uuid.UUID,
    purge: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if purge:
        purge_document(db, user, document_id)
        return
    remove_document(db, user, document_id)


@router.post("/documents/{document_id}/restore", response_model=LibraryDocumentPublic)
def post_restore(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> LibraryDocumentPublic:
    return document_out(restore_document(db, user, document_id))


@router.post("/documents/{document_id}/shares", response_model=ShareCreated, status_code=201)
def post_share(
    document_id: uuid.UUID,
    body: ShareCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShareCreated:
    share, token = create_share(db, user, document_id, body.hours, body.permission, body.password)
    return ShareCreated(
        id=share.id,
        document_id=share.document_id,
        expires_at=share.expires_at,
        permission=share.permission,
        password_protected=share.password_hash is not None,
        token=token,
    )


@router.get("/shares", response_model=list[SharePublic])
def get_shares(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SharePublic]:
    return [
        SharePublic(
            id=share.id,
            document_id=share.document_id,
            expires_at=share.expires_at,
            revoked_at=share.revoked_at,
            permission=share.permission,
            password_protected=share.password_hash is not None,
            created_at=share.created_at,
        )
        for share in list_shares(db, user)
    ]


@router.delete("/shares/{share_id}", status_code=204)
def delete_share(share_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    revoke_share(db, user, share_id)
