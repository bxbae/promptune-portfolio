from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.services.document_generator import generate_document
from app.services.documents.office_preview import convert_office_to_pdf
from app.services.documents.smart_document_generator import (
    generate_smart_document,
)


router = APIRouter(tags=["document-generator"])


class DocumentGenerateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    content: str = Field(..., min_length=1)
    format: Literal["pdf", "docx", "xlsx", "md", "txt"] = "pdf"


@router.post("/documents/generate")
def create_document(req: DocumentGenerateRequest):
    try:
        if req.format in {"docx", "pdf"}:
            data, filename, media_type = generate_smart_document(
                title=req.title,
                content=req.content,
                output_format=req.format,
            )
        else:
            data, filename, media_type = generate_document(
                title=req.title,
                content=req.content,
                output_format=req.format,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    encoded_filename = quote(filename)

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition":
                f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )

@router.post("/documents/preview")
async def preview_office_document(
    file: UploadFile = File(...),
):
    filename = file.filename or "document.docx"
    data = await file.read()

    if not data:
        raise HTTPException(
            status_code=400,
            detail="미리보기 파일이 비어 있습니다.",
        )

    try:
        pdf = convert_office_to_pdf(data, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    encoded_filename = quote(
        filename.rsplit(".", 1)[0] + ".pdf"
    )

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f"inline; filename*=UTF-8''{encoded_filename}"
        },
    )


@router.post("/documents/generate-template")
async def create_document_from_template(
    title: str = Form(...),
    content: str = Form(...),
    format: Literal["pdf", "docx", "xlsx", "md", "txt"] = Form(...),
    template: UploadFile = File(...),
):
    template_bytes = await template.read()

    if not template_bytes:
        raise HTTPException(
            status_code=400,
            detail="템플릿 파일이 비어 있습니다.",
        )

    try:
        data, filename, media_type = generate_document(
            title=title,
            content=content,
            output_format=format,
            template_bytes=template_bytes,
            template_filename=template.filename,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    encoded_filename = quote(filename)

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition":
                f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )
