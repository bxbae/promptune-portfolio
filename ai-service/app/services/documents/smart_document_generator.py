from __future__ import annotations

import re

from app.services.documents.document_composer import compose_document
from app.services.documents.document_planner import build_document_plan
from app.services.documents.docx_renderer import render_docx
from app.services.documents.docx_to_pdf import render_pdf_from_docx
from app.services.documents.layout_planner import apply_layout_plan


def _safe_filename(title: str) -> str:
    value = re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        str(title or "").strip(),
    )

    return value or "document"


def generate_smart_document(
    title: str,
    content: str,
    output_format: str,
) -> tuple[bytes, str, str]:
    fmt = output_format.strip().lower()

    if fmt not in {"docx", "pdf"}:
        raise ValueError(
            "Smart Document Generator는 현재 docx, pdf를 지원합니다."
        )

    request = (
        f"문서 제목: {title.strip()}\n\n"
        f"사용자 요청 및 원본 자료:\n"
        f"{content.strip()}"
    )

    plan = build_document_plan(request)

    if title.strip():
        plan.title = title.strip()

    composed = compose_document(
        plan,
        content.strip(),
    )

    if not composed.title.strip():
        composed.title = plan.title

    result = apply_layout_plan(
        plan,
        composed,
    )

    safe_title = _safe_filename(
        result.title or plan.title or title
    )

    if fmt == "docx":
        data = render_docx(result)

        return (
            data,
            f"{safe_title}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    data = render_pdf_from_docx(result)

    return (
        data,
        f"{safe_title}.pdf",
        "application/pdf",
    )
