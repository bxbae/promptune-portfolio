from __future__ import annotations

from copy import deepcopy
import re

from app.services.documents.document_content import (
    DocumentBlock,
    DocumentContent,
    DocumentPlan,
)


def _normalize(text: str) -> str:
    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(text or "").lower(),
    )


def _split_items(text: str) -> list[str]:
    lines = []

    for raw in str(text or "").splitlines():
        value = raw.strip()

        if not value:
            continue

        value = re.sub(
            r"^(?:[-•▪◦*]|(?:\d+|[가-힣])[\.\)])\s*",
            "",
            value,
        ).strip()

        if value:
            lines.append(value)

    return lines


def _table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []

    for line in str(text or "").splitlines():
        if "|" not in line:
            continue

        row = [
            cell.strip()
            for cell in line.strip().strip("|").split("|")
        ]

        if len(row) >= 2:
            rows.append(row)

    if len(rows) < 2:
        return []

    width = len(rows[0])

    if any(len(row) != width for row in rows):
        return []

    return rows


def _heading_role(title: str) -> str:
    value = _normalize(title)

    role_keywords = {
        "action": [
            "actionitems",
            "actionitem",
            "다음할일",
            "후속조치",
            "조치계획",
            "실행계획",
            "추진계획",
            "재발방지",
        ],
        "decision": [
            "결정사항",
            "합의사항",
            "결론",
            "요청사항",
            "승인요청",
        ],
        "agenda": [
            "주요안건",
            "안건",
            "핵심사항",
            "주요기능",
            "기대효과",
        ],
        "schedule": [
            "향후일정",
            "추진일정",
            "일정계획",
            "향후계획",
        ],
        "risk": [
            "리스크",
            "위험요인",
            "문제점",
            "유의사항",
            "주의사항",
        ],
    }

    for role, keywords in role_keywords.items():
        if any(keyword in value for keyword in keywords):
            return role

    return "normal"


def _transform_paragraph(
    block: DocumentBlock,
    role: str,
) -> DocumentBlock:
    content = block.content.strip()

    if not content:
        return block

    rows = _table_rows(content)

    if rows:
        return DocumentBlock(
            type="table",
            rows=rows,
        )

    items = _split_items(content)

    if role in {
        "action",
        "agenda",
        "schedule",
    } and len(items) >= 2:
        return DocumentBlock(
            type="bullet_list",
            items=items,
        )

    if role in {
        "decision",
        "risk",
    }:
        return DocumentBlock(
            type="callout",
            content=content,
        )

    return block


def _legacy_blocks(
    doc: DocumentContent,
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []

    for section in doc.sections:
        title = section.title.strip()
        content = section.content.strip()

        if title:
            blocks.append(
                DocumentBlock(
                    type="heading",
                    content=title,
                )
            )

        if content:
            blocks.append(
                DocumentBlock(
                    type="paragraph",
                    content=content,
                )
            )

    if not blocks and doc.body.strip():
        blocks.append(
            DocumentBlock(
                type="paragraph",
                content=doc.body.strip(),
            )
        )

    return blocks


def apply_layout_plan(
    plan: DocumentPlan,
    doc: DocumentContent,
) -> DocumentContent:
    result = deepcopy(doc)

    result.document_kind = (
        plan.document_kind
        or result.document_kind
    )
    result.blueprint_key = plan.blueprint_key
    result.style_profile = plan.style_profile
    result.layout_hint = plan.layout_hint

    source_blocks = (
        result.blocks
        if result.blocks
        else _legacy_blocks(result)
    )

    final_blocks: list[DocumentBlock] = []
    current_role = "normal"

    for block in source_blocks:
        if block.type == "heading":
            heading = (
                block.content
                or block.title
            ).strip()

            if not heading:
                continue

            current_role = _heading_role(
                heading
            )

            final_blocks.append(
                DocumentBlock(
                    type="heading",
                    content=heading,
                )
            )
            continue

        if block.type == "paragraph":
            final_blocks.append(
                _transform_paragraph(
                    block,
                    current_role,
                )
            )
            continue

        final_blocks.append(
            deepcopy(block)
        )

    result.blocks = final_blocks

    return result
