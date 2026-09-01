from __future__ import annotations

import re
import subprocess

import pymupdf

from app.services.documents.document_content import (
    DocumentBlock,
    DocumentContent,
)


def _normalize(text: str) -> str:
    return re.sub(
        r"\s+",
        "",
        str(text or "").strip(),
    ).lower()


def _find_font_file() -> str:
    result = subprocess.run(
        [
            "fc-match",
            "-f",
            "%{file}\n",
            "Noto Sans CJK KR",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "한글 폰트를 찾지 못했습니다."
        )

    path = result.stdout.strip().splitlines()

    if not path:
        raise RuntimeError(
            "Noto Sans CJK 폰트 경로가 없습니다."
        )

    return path[0]


def _block_text(
    block: DocumentBlock,
) -> str:
    if block.type == "paragraph":
        return block.content.strip()

    if block.type == "bullet_list":
        return "\n".join(
            f"• {item.strip()}"
            for item in block.items
            if item.strip()
        )

    if block.type == "numbered_list":
        return "\n".join(
            f"{index}. {item.strip()}"
            for index, item in enumerate(
                block.items,
                start=1,
            )
            if item.strip()
        )

    if block.type == "table":
        return "\n".join(
            " | ".join(
                str(cell).strip()
                for cell in row
            )
            for row in block.rows
            if row
        )

    if block.type == "key_value_table":
        return "\n".join(
            f"{key.strip()}: {value.strip()}"
            for key, value in block.data.items()
            if key.strip() and value.strip()
        )

    if block.type in {
        "callout",
        "signature",
    }:
        values: list[str] = []

        if block.content.strip():
            values.append(
                block.content.strip()
            )

        values.extend(
            f"{key.strip()}: {value.strip()}"
            for key, value in block.data.items()
            if key.strip() and value.strip()
        )

        return "\n".join(values)

    return block.content.strip()


def _collect_sections(
    doc: DocumentContent,
) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_heading: str | None = None

    for block in doc.blocks:
        if block.type == "heading":
            current_heading = (
                block.content
                or block.title
            ).strip()

            if current_heading:
                sections.setdefault(
                    current_heading,
                    [],
                )

            continue

        if not current_heading:
            continue

        text = _block_text(block)

        if text:
            sections[current_heading].append(
                text
            )

    return {
        title: "\n".join(parts).strip()
        for title, parts in sections.items()
        if parts
    }


def _find_label_rect(
    page,
    label: str,
):
    normalized_label = _normalize(label)

    direct_candidates = [
        label,
        label.replace(" ", ""),
    ]

    for candidate in direct_candidates:
        rects = page.search_for(candidate)

        if rects:
            return rects[0]

    words = page.get_text("words")

    for word in words:
        text = word[4]

        if _normalize(text) == normalized_label:
            return pymupdf.Rect(
                word[0],
                word[1],
                word[2],
                word[3],
            )

    return None


def _contains_point(
    cell,
    point,
) -> bool:
    rect = pymupdf.Rect(cell)

    return rect.contains(point)


def _find_metadata_target_cell(
    page,
    label: str,
):
    label_rect = _find_label_rect(
        page,
        label,
    )

    if label_rect is None:
        return None

    center = pymupdf.Point(
        (
            label_rect.x0
            + label_rect.x1
        ) / 2,
        (
            label_rect.y0
            + label_rect.y1
        ) / 2,
    )

    finder = page.find_tables()

    for table in finder.tables:
        label_cell = None

        for cell in table.cells:
            if (
                cell is not None
                and _contains_point(
                    cell,
                    center,
                )
            ):
                label_cell = pymupdf.Rect(
                    cell
                )
                break

        if label_cell is None:
            continue

        candidates = []

        for cell in table.cells:
            if cell is None:
                continue

            rect = pymupdf.Rect(cell)

            same_row = (
                abs(
                    rect.y0
                    - label_cell.y0
                ) < 2
                and abs(
                    rect.y1
                    - label_cell.y1
                ) < 2
            )

            is_right = (
                rect.x0
                >= label_cell.x1 - 1
            )

            if same_row and is_right:
                candidates.append(rect)

        if candidates:
            candidates.sort(
                key=lambda rect: rect.x0
            )

            return candidates[0]

    return None


def _horizontal_body_lines(
    page,
) -> list[tuple[float, float, float]]:
    lines: list[
        tuple[float, float, float]
    ] = []

    min_length = page.rect.width * 0.45

    for drawing in page.get_drawings():
        for item in drawing.get(
            "items",
            [],
        ):
            if (
                not item
                or item[0] != "l"
            ):
                continue

            p1 = item[1]
            p2 = item[2]

            if abs(p1.y - p2.y) > 0.5:
                continue

            x0 = min(p1.x, p2.x)
            x1 = max(p1.x, p2.x)

            if x1 - x0 < min_length:
                continue

            lines.append(
                (
                    p1.y,
                    x0,
                    x1,
                )
            )

    lines.sort(
        key=lambda item: item[0]
    )

    unique = []

    for line in lines:
        if (
            unique
            and abs(
                unique[-1][0]
                - line[0]
            ) < 1
        ):
            continue

        unique.append(line)

    return unique


def _find_section_target_rect(
    page,
    heading: str,
):
    heading_rect = _find_label_rect(
        page,
        heading,
    )

    if heading_rect is None:
        return None

    center_y = (
        heading_rect.y0
        + heading_rect.y1
    ) / 2

    lines = [
        line
        for line in _horizontal_body_lines(
            page
        )
        if line[0] > center_y
    ]

    if len(lines) < 2:
        return None

    top = lines[0]
    bottom = lines[1]

    x0 = max(
        top[1],
        bottom[1],
    )
    x1 = min(
        top[2],
        bottom[2],
    )

    if x1 <= x0:
        return None

    return pymupdf.Rect(
        x0 + 4,
        top[0] + 2,
        x1 - 4,
        bottom[0] - 2,
    )


def _insert_fitted_text(
    page,
    rect,
    text: str,
    *,
    start_size: float = 8.5,
    min_size: float = 6.0,
) -> None:
    value = text.strip()

    if not value:
        return

    size = start_size

    while size >= min_size:
        result = page.insert_textbox(
            rect,
            value,
            fontsize=size,
            fontname="korea",
            lineheight=1.1,
        )

        if result >= 0:
            return

        size -= 0.5

    raise ValueError(
        "PDF 템플릿의 입력 영역이 "
        f"내용에 비해 너무 작습니다: {value[:80]}"
    )


def render_pdf_template(
    template_bytes: bytes,
    doc: DocumentContent,
) -> bytes:
    pdf = pymupdf.open(
        stream=template_bytes,
        filetype="pdf",
    )

    section_values = _collect_sections(
        doc
    )

    try:
        for page in pdf:
            for key, value in doc.metadata.items():
                if (
                    not key.strip()
                    or not value.strip()
                ):
                    continue

                rect = _find_metadata_target_cell(
                    page,
                    key,
                )

                if rect is None:
                    continue

                target = pymupdf.Rect(
                    rect.x0 + 3,
                    rect.y0 + 2,
                    rect.x1 - 3,
                    rect.y1 - 2,
                )

                _insert_fitted_text(
                    page,
                    target,
                    value,
                    start_size=8,
                )

            for heading, content in section_values.items():
                if not content.strip():
                    continue

                rect = _find_section_target_rect(
                    page,
                    heading,
                )

                if rect is None:
                    continue

                _insert_fitted_text(
                    page,
                    rect,
                    content,
                    start_size=8,
                )

        return pdf.tobytes(
            garbage=4,
            deflate=True,
        )

    finally:
        pdf.close()
