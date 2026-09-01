from __future__ import annotations

from app.services.documents.document_content import (
    DocumentBlock,
    DocumentContent,
)


def _render_block(block: DocumentBlock) -> list[str]:
    lines: list[str] = []

    if block.type == "page_break":
        return ["", "\f", ""]

    if block.type == "heading":
        text = (block.content or block.title).strip()
        return [text, ""] if text else []

    if block.title.strip():
        lines.extend([
            block.title.strip(),
            "",
        ])

    if block.type == "paragraph":
        if block.content.strip():
            lines.extend([
                block.content.strip(),
                "",
            ])

    elif block.type == "bullet_list":
        for item in block.items:
            if item.strip():
                lines.append(f"- {item.strip()}")
        lines.append("")

    elif block.type == "numbered_list":
        for index, item in enumerate(block.items, start=1):
            if item.strip():
                lines.append(f"{index}. {item.strip()}")
        lines.append("")

    elif block.type == "key_value_table":
        for key, value in block.data.items():
            if key.strip() and value.strip():
                lines.append(
                    f"{key.strip()}: {value.strip()}"
                )
        lines.append("")

    elif block.type == "table":
        for row in block.rows:
            if row:
                lines.append(
                    " | ".join(str(cell).strip() for cell in row)
                )
        lines.append("")

    elif block.type == "callout":
        if block.content.strip():
            lines.extend([
                block.content.strip(),
                "",
            ])

    elif block.type == "signature":
        if block.content.strip():
            lines.append(block.content.strip())

        for key, value in block.data.items():
            if key.strip() and value.strip():
                lines.append(
                    f"{key.strip()}: {value.strip()}"
                )

        lines.append("")

    return lines


def render_text(doc: DocumentContent) -> bytes:
    lines: list[str] = []

    if doc.title.strip():
        lines.extend([
            doc.title.strip(),
            "",
        ])

    for key, value in doc.metadata.items():
        if key.strip() and value.strip():
            lines.append(
                f"{key.strip()}: {value.strip()}"
            )

    if doc.metadata:
        lines.append("")

    if doc.blocks:
        for block in doc.blocks:
            lines.extend(_render_block(block))
    else:
        if doc.body.strip():
            lines.extend([
                doc.body.strip(),
                "",
            ])

        for section in doc.sections:
            if section.title.strip():
                lines.extend([
                    section.title.strip(),
                    "",
                ])

            if section.content.strip():
                lines.extend([
                    section.content.strip(),
                    "",
                ])

    text = "\n".join(lines).strip() + "\n"
    return text.encode("utf-8")
