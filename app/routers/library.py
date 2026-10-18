import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.library_files import read_owned_file, save_upload
from app.library_service import (
    add_document,
    create_folder,
    delete_folder,
    ensure_folders,
    list_documents,
    move_folder,
    owned_document,
    owned_folder,
    remove_document,
    rename_folder,
    update_document,
)
from app.models import User
from app.routers.auth import get_current_user
from app.schemas import LibraryDocumentPublic, LibraryFolderCreate, LibraryFolderPublic, LibraryFolderUpdate, LibraryDocumentUpdate

router = APIRouter(prefix="/library", tags=["library"])


def folder_out(folder) -> LibraryFolderPublic:
    return LibraryFolderPublic.model_validate(folder)


def document_out(document) -> LibraryDocumentPublic:
    return LibraryDocumentPublic.model_validate(document)


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
    return folder_out(owned_folder(db, user, folder_id))


@router.delete("/folders/{folder_id}", status_code=204)
def remove_folder(
    folder_id: uuid.UUID,
    disposition: str = Query(default="uncategorized", pattern="^(uncategorized|delete)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    delete_folder(db, user, folder_id, disposition)


@router.get("/documents", response_model=list[LibraryDocumentPublic])
def get_documents(
    folder_id: uuid.UUID | None = None,
    favorite: bool | None = None,
    q: str | None = None,
    sort: str = Query(default="added", pattern="^(added|updated|name|size|type)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[LibraryDocumentPublic]:
    ensure_folders(db, user)
    return [document_out(document) for document in list_documents(db, user, folder_id, favorite, q, sort)]


@router.post("/documents", response_model=LibraryDocumentPublic, status_code=201)
async def post_document(
    folder_id: uuid.UUID = Form(),
    classification_key: str | None = Form(default=None),
    upload: UploadFile = File(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LibraryDocumentPublic:
    ensure_folders(db, user)
    storage_key, mime_type, size, filename = await save_upload(user.id, upload)
    try:
        document = add_document(db, user, folder_id, filename, mime_type, size, storage_key, classification_key)
    except Exception:
        from app.library_files import delete_owned_file

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
    return document_out(update_document(db, user, document_id, body.filename, body.folder_id, body.favorite))


@router.get("/documents/{document_id}/file")
def download_document(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    document = owned_document(db, user, document_id)
    path = read_owned_file(user.id, document.storage_key)
    return FileResponse(path, media_type=document.mime_type, filename=document.filename)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    remove_document(db, user, document_id)
