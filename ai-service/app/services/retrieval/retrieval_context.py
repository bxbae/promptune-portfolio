from __future__ import annotations

from collections import OrderedDict

from app.schemas.models import Document


MAX_TOTAL_CONTENT_LENGTH = 10000
MAX_DESCRIPTION_LENGTH = 400


def build_internal_context(
    documents: list[Document],
) -> str:
    """
    검색 결과 chunk를 "문서 단위"로 묶어 HCX에 전달한다.

    예전 구현은 한 파일의 chunk 10개를 서로 다른 "내부 문서 1~10"처럼
    보여줘 모델이 문서 경계를 오해할 수 있었다. document_id/title을 기준으로
    그룹화하고 chunk_index 순서대로 이어서 하나의 문서 본문처럼 전달한다.
    """

    if not documents:
        return "없음"

    groups: OrderedDict[str, list[Document]] = OrderedDict()

    for doc in documents:
        key = (
            f"id:{doc.document_id}"
            if doc.document_id is not None
            else f"title:{doc.title}"
        )
        groups.setdefault(key, []).append(doc)

    parts: list[str] = []
    total_chars = 0

    for document_index, chunks in enumerate(groups.values(), start=1):
        chunks = sorted(
            chunks,
            key=lambda item: (
                item.chunk_index is None,
                item.chunk_index if item.chunk_index is not None else 10**9,
            ),
        )

        first = chunks[0]
        description = (first.description or "").strip() or "설명 없음"
        description = description[:MAX_DESCRIPTION_LENGTH]

        body_parts: list[str] = []

        for chunk in chunks:
            content = (chunk.content or "").strip()
            if not content:
                continue

            remaining = MAX_TOTAL_CONTENT_LENGTH - total_chars
            if remaining <= 0:
                break

            content = content[:remaining]
            label = (
                f"[chunk {chunk.chunk_index}]"
                if chunk.chunk_index is not None
                else "[chunk]"
            )
            body_parts.append(f"{label}\n{content}")
            total_chars += len(content)

        if not body_parts:
            continue

        parts.append(
            f"[내부 문서 {document_index}]\n"
            f"document_id: {first.document_id}\n"
            f"제목: {first.title}\n"
            f"문서 유형: {first.document_type}\n"
            f"설명: {description}\n"
            f"본문:\n" + "\n\n".join(body_parts)
        )

        if total_chars >= MAX_TOTAL_CONTENT_LENGTH:
            break

    return "\n\n".join(parts) if parts else "없음"
