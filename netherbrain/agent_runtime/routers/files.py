"""File browsing, read, write, upload, and download endpoints.

Thin HTTP adapter -- delegates all business logic to the file manager.
All endpoints are scoped to a ``project_id`` mapping to a managed directory.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from starlette.responses import FileResponse

from netherbrain.agent_runtime.deps import CurrentUser
from netherbrain.agent_runtime.managers.files import (
    FileListResult,
    FileReadResult,
    FileWriteResult,
    ProjectPathResolver,
    UploadResult,
    build_archive,
    create_directory,
    delete_path,
    list_directory,
    read_file,
    resolve_download,
    save_upload,
    write_file,
)
from netherbrain.agent_runtime.settings import get_settings

router = APIRouter(prefix="/files", tags=["files"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolver() -> ProjectPathResolver:
    """Create a path resolver from current settings."""
    s = get_settings()
    return ProjectPathResolver(data_root=s.data_root, data_prefix=s.data_prefix)


def _not_found(project_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Not found in project '{project_id}'.")


# Spec: path traversal (403) is silently reported as 404.
_CATCH = (LookupError, PermissionError)

# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field  # noqa: E402


class WriteBody(BaseModel):
    path: str
    content: str


class ArchiveBody(BaseModel):
    paths: list[str] = Field(..., min_length=1)


class DeleteBody(BaseModel):
    paths: list[str] = Field(..., min_length=1)


class MkdirBody(BaseModel):
    path: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{project_id}/list", response_model=FileListResult)
async def handle_list(
    project_id: str,
    user: CurrentUser,
    path: str = Query("", description="Relative directory path"),
) -> FileListResult:
    """List directory contents (dirs first, then files, alphabetical)."""
    try:
        return await asyncio.to_thread(list_directory, _resolver(), project_id, path)
    except _CATCH:
        raise _not_found(project_id) from None


@router.get("/{project_id}/read", response_model=FileReadResult)
async def handle_read(
    project_id: str,
    user: CurrentUser,
    path: str = Query(..., description="Relative file path"),
    max_size: int = Query(1_048_576, ge=1, description="Max bytes to read"),
) -> FileReadResult:
    """Read text file content for preview or editing."""
    try:
        return await asyncio.to_thread(read_file, _resolver(), project_id, path, max_size)
    except ValueError as exc:
        # Binary file or other validation error
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    except _CATCH:
        raise _not_found(project_id) from None


@router.post("/{project_id}/write", response_model=FileWriteResult)
async def handle_write(
    project_id: str,
    body: WriteBody,
    user: CurrentUser,
) -> FileWriteResult:
    """Write text content to a file (create or overwrite)."""
    try:
        return await asyncio.to_thread(write_file, _resolver(), project_id, body.path, body.content)
    except _CATCH:
        raise _not_found(project_id) from None


@router.post("/{project_id}/upload", response_model=UploadResult)
async def handle_upload(
    project_id: str,
    user: CurrentUser,
    files: list[UploadFile],
    path: str = Form(""),
) -> UploadResult:
    """Upload one or more files via multipart form data."""
    resolver = _resolver()
    uploaded = []

    for f in files:
        if not f.filename:
            continue
        data = await f.read()
        try:
            info = await asyncio.to_thread(save_upload, resolver, project_id, path, f.filename, data)
            uploaded.append(info)
        except ValueError as exc:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from None
        except _CATCH:
            raise _not_found(project_id) from None

    return UploadResult(project_id=project_id, uploaded=uploaded)


@router.get("/{project_id}/download")
async def handle_download(
    project_id: str,
    user: CurrentUser,
    path: str = Query(..., description="Relative file path"),
) -> FileResponse:
    """Download a single file."""
    try:
        real_path, mime_type = await asyncio.to_thread(resolve_download, _resolver(), project_id, path)
    except _CATCH:
        raise _not_found(project_id) from None

    filename = real_path.name
    return FileResponse(
        path=real_path,
        media_type=mime_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{project_id}/delete")
async def handle_delete(
    project_id: str,
    body: DeleteBody,
    user: CurrentUser,
) -> dict:
    """Delete one or more files or directories."""
    errors: list[str] = []
    deleted = 0
    for p in body.paths:
        try:
            await asyncio.to_thread(delete_path, _resolver(), project_id, p)
            deleted += 1
        except ValueError as exc:
            errors.append(str(exc))
        except _CATCH:
            errors.append(f"Not found: {p}")
    if errors and deleted == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="; ".join(errors))
    return {"deleted": deleted, "errors": errors}


@router.post("/{project_id}/mkdir")
async def handle_mkdir(
    project_id: str,
    body: MkdirBody,
    user: CurrentUser,
) -> dict:
    """Create a new directory."""
    try:
        await asyncio.to_thread(create_directory, _resolver(), project_id, body.path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except _CATCH:
        raise _not_found(project_id) from None
    return {"path": body.path}


@router.post("/{project_id}/download-archive")
async def handle_download_archive(
    project_id: str,
    body: ArchiveBody,
    user: CurrentUser,
) -> StreamingResponse:
    """Package multiple files/directories into a zip archive for download."""
    try:
        buf = await asyncio.to_thread(build_archive, _resolver(), project_id, body.paths)
    except ValueError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from None
    except _CATCH:
        raise _not_found(project_id) from None

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}.zip"',
        },
    )
