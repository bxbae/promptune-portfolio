from __future__ import annotations

from app.services.documents.document_content import (
    DocumentBlock,
    DocumentContent,
)


def _escape_cell(value: str) -> str:
    return str(value).strip().replace("|", "\\|")


def _render_block(block: DocumentBlock) -> list[str]:
    lines: list[str] = []

    if block.type == "page_break":
        return ["", "---", ""]

    if block.type == "heading":
        text = (block.content or block.title).strip()
        return [f"## {text}", ""] if text else []

    if block.title.strip():
        lines.extend([
            f"### {block.title.strip()}",
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
        if block.data:
            lines.extend([
                "| 항목 | 내용 |",
                "| --- | --- |",
            ])

            for key, value in block.data.items():
                if key.strip() and value.strip():
                    lines.append(
                        f"| {_escape_cell(key)} | {_escape_cell(value)} |"
                    )

            lines.append("")

    elif block.type == "table":
        rows = [
            [_escape_cell(cell) for cell in row]
            for row in block.rows
            if row
        ]

        if rows:
            width = max(len(row) for row in rows)

            first = rows[0] + [""] * (width - len(rows[0]))

            lines.append(
                "| " + " | ".join(first) + " |"
            )
            lines.append(
                "| " + " | ".join(["---"] * width) + " |"
            )

            for row in rows[1:]:
                padded = row + [""] * (width - len(row))
                lines.append(
                    "| " + " | ".join(padded) + " |"
                )

            lines.append("")

    elif block.type == "callout":
        if block.content.strip():
            for line in block.content.strip().splitlines():
                lines.append(f"> {line}")
            lines.append("")

    elif block.type == "signature":
        if block.content.strip():
            lines.append(block.content.strip())

        for key, value in block.data.items():
            if key.strip() and value.strip():
                lines.append(
                    f"**{key.strip()}:** {value.strip()}"
                )

        lines.append("")

    return lines


def render_markdown(doc: DocumentContent) -> bytes:
    lines: list[str] = []

    if doc.title.strip():
        lines.extend([
            f"# {doc.title.strip()}",
            "",
        ])

    if doc.metadata:
        lines.extend([
            "| 항목 | 내용 |",
            "| --- | --- |",
        ])

        for key, value in doc.metadata.items():
            if key.strip() and value.strip():
                lines.append(
                    f"| {_escape_cell(key)} | {_escape_cell(value)} |"
                )

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
                    f"## {section.title.strip()}",
                    "",
                ])

            if section.content.strip():
                lines.extend([
                    section.content.strip(),
                    "",
                ])

    text = "\n".join(lines).strip() + "\n"
    return text.encode("utf-8")
