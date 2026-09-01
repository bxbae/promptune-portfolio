from __future__ import annotations

import re

from app.services.documents.document_content import (
    DocumentContent,
    DocumentSection,
)


METADATA_FIELDS = [
    "문서명",
    "작성일",
    "작성부서",
    "작성자",
    "보고대상",
    "문서번호",
]


def _normalize_input(content: str) -> str:
    text = content.replace("\r\n", "\n").replace("\r", "\n").strip()

    for field in METADATA_FIELDS:
        text = re.sub(
            rf"(?<!\n)[ \t]*(?={re.escape(field)}\s*[:：])",
            "\n",
            text,
        )

    text = re.sub(
        r"(?<!\n)[ \t]*(?=(?:#{1,6}\s+|\d+\s*[.)]\s*)[^\n]+)",
        "\n",
        text,
    )

    return text.strip()


def parse_document_content(
    title: str,
    content: str,
) -> DocumentContent:
    text = _normalize_input(content)

    metadata: dict[str, str] = {}
    sections: list[DocumentSection] = []
    body_lines: list[str] = []

    metadata_pattern = re.compile(
        rf"^({'|'.join(map(re.escape, METADATA_FIELDS))})"
        r"\s*[:：]\s*(.*)$"
    )

    known_section_titles = [
        "보고 목적",
        "주요 내용",
        "현황 및 문제점",
        "검토 내용",
        "조치 / 실행 계획",
        "요청 및 결정 사항",
        "첨부 / 참고 자료",
    ]

    numbered_section_pattern = re.compile(
        r"^\d+\s*[.)]\s*(.+)$"
    )

    markdown_section_pattern = re.compile(
        r"^#{1,6}\s+(.+)$"
    )

    current_title: str | None = None
    current_lines: list[str] = []

    def flush_section() -> None:
        nonlocal current_title, current_lines

        if current_title is not None:
            sections.append(
                DocumentSection(
                    title=current_title.strip(),
                    content="\n".join(current_lines).strip(),
                )
            )

        current_title = None
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            if current_title is not None and current_lines:
                current_lines.append("")
            elif body_lines:
                body_lines.append("")
            continue

        metadata_match = metadata_pattern.match(line)
        if metadata_match:
            key = metadata_match.group(1)
            value = metadata_match.group(2).strip()
            metadata[key] = value
            continue

        markdown_match = markdown_section_pattern.match(line)
        if markdown_match:
            flush_section()
            current_title = markdown_match.group(1).strip()
            continue

        numbered_match = numbered_section_pattern.match(line)
        if numbered_match:
            remainder = numbered_match.group(1).strip()

            matched_title = None
            inline_body = ""

            for known_title in sorted(
                known_section_titles,
                key=len,
                reverse=True,
            ):
                if remainder == known_title:
                    matched_title = known_title
                    break

                prefix = known_title + " "
                if remainder.startswith(prefix):
                    matched_title = known_title
                    inline_body = remainder[len(prefix):].strip()
                    break

            flush_section()

            if matched_title is not None:
                current_title = matched_title
                if inline_body:
                    current_lines.append(inline_body)
            else:
                current_title = remainder

            continue
        if current_title is not None:
            current_lines.append(line)
        else:
            body_lines.append(line)

    flush_section()

    resolved_title = (
        metadata.get("문서명")
        or title.strip()
        or "문서"
    )

    return DocumentContent(
        title=resolved_title,
        metadata={
            key: value
            for key, value in metadata.items()
            if key != "문서명" and value
        },
        sections=sections,
        body="\n".join(body_lines).strip(),
    )
