from __future__ import annotations

import textwrap

import fitz

from app.services.documents.document_content import (
    DocumentBlock,
    DocumentContent,
)


PAGE_WIDTH = 595
PAGE_HEIGHT = 842

LEFT = 50
RIGHT = 50
TOP = 50
BOTTOM = 50

BODY_SIZE = 10.5
HEADING_SIZE = 13
TITLE_SIZE = 18

BODY_LINE_HEIGHT = 17
HEADING_LINE_HEIGHT = 21

FONT_NAME = "korea"


class PdfWriter:
    def __init__(self) -> None:
        self.pdf = fitz.open()
        self.page = None
        self.y = TOP

        self.new_page()

    def new_page(self) -> None:
        self.page = self.pdf.new_page(
            width=PAGE_WIDTH,
            height=PAGE_HEIGHT,
        )
        self.y = TOP

    def ensure_space(
        self,
        required_height: float,
    ) -> None:
        if self.y + required_height > PAGE_HEIGHT - BOTTOM:
            self.new_page()

    def blank(self, height: float = 8) -> None:
        self.y += height

    def text(
        self,
        value: str,
        *,
        fontsize: float = BODY_SIZE,
        bold: bool = False,
        indent: float = 0,
    ) -> None:
        value = value.strip()

        if not value:
            return

        width = 46

        if fontsize >= TITLE_SIZE:
            width = 30
        elif fontsize >= HEADING_SIZE:
            width = 38

        prefix = ""

        if bold:
            prefix = ""

        lines = textwrap.wrap(
            value,
            width=width,
            break_long_words=True,
            replace_whitespace=False,
        ) or [value]

        line_height = (
            HEADING_LINE_HEIGHT
            if fontsize >= HEADING_SIZE
            else BODY_LINE_HEIGHT
        )

        for line in lines:
            self.ensure_space(line_height)

            self.page.insert_text(
                (
                    LEFT + indent,
                    self.y,
                ),
                prefix + line,
                fontsize=fontsize,
                fontname=FONT_NAME,
            )

            self.y += line_height

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> None:
        self.page.draw_line(
            (x1, y1),
            (x2, y2),
        )

    def finish(self) -> bytes:
        data = self.pdf.tobytes()
        self.pdf.close()
        return data


def _render_metadata(
    writer: PdfWriter,
    metadata: dict[str, str],
) -> None:
    items = [
        (key.strip(), value.strip())
        for key, value in metadata.items()
        if key.strip() and value.strip()
    ]

    if not items:
        return

    writer.blank(8)

    for index in range(0, len(items), 2):
        writer.ensure_space(24)

        row = items[index:index + 2]

        parts = []

        for key, value in row:
            parts.append(
                f"{key}: {value}"
            )

        writer.text(
            "    |    ".join(parts),
            fontsize=BODY_SIZE,
        )

    writer.blank(8)


def _render_table(
    writer: PdfWriter,
    rows: list[list[str]],
) -> None:
    cleaned = [
        [
            str(cell).strip()
            for cell in row
        ]
        for row in rows
        if row
    ]

    if not cleaned:
        return

    writer.blank(4)

    for row_index, row in enumerate(cleaned):
        writer.ensure_space(22)

        text = "  |  ".join(row)

        writer.text(
            text,
            fontsize=BODY_SIZE,
        )

        if row_index == 0:
            writer.line(
                LEFT,
                writer.y - 3,
                PAGE_WIDTH - RIGHT,
                writer.y - 3,
            )

    writer.blank(4)


def _render_key_value_table(
    writer: PdfWriter,
    data: dict[str, str],
) -> None:
    items = [
        (key.strip(), value.strip())
        for key, value in data.items()
        if key.strip() and value.strip()
    ]

    for key, value in items:
        writer.text(
            f"{key}: {value}",
        )


def _render_block(
    writer: PdfWriter,
    block: DocumentBlock,
) -> None:
    if block.type == "page_break":
        writer.new_page()
        return

    if block.type == "heading":
        writer.blank(8)

        writer.text(
            block.content or block.title,
            fontsize=HEADING_SIZE,
            bold=True,
        )

        writer.blank(2)
        return

    if block.title.strip():
        writer.blank(6)

        writer.text(
            block.title,
            fontsize=HEADING_SIZE,
            bold=True,
        )

    if block.type == "paragraph":
        writer.text(
            block.content,
        )

    elif block.type == "bullet_list":
        for item in block.items:
            if item.strip():
                writer.text(
                    f"• {item.strip()}",
                    indent=8,
                )

    elif block.type == "numbered_list":
        for index, item in enumerate(
            block.items,
            start=1,
        ):
            if item.strip():
                writer.text(
                    f"{index}. {item.strip()}",
                    indent=8,
                )

    elif block.type == "table":
        _render_table(
            writer,
            block.rows,
        )

    elif block.type == "key_value_table":
        _render_key_value_table(
            writer,
            block.data,
        )

    elif block.type == "callout":
        writer.blank(4)

        if block.title.strip():
            writer.text(
                block.title,
                fontsize=BODY_SIZE,
                bold=True,
            )

        writer.text(
            block.content,
            indent=8,
        )

        writer.blank(4)

    elif block.type == "signature":
        writer.blank(12)

        if block.title.strip():
            writer.text(
                block.title,
                fontsize=BODY_SIZE,
                bold=True,
            )

        if block.content.strip():
            writer.text(
                block.content,
                indent=20,
            )

        for key, value in block.data.items():
            if key.strip() and value.strip():
                writer.text(
                    f"{key.strip()}: {value.strip()}",
                    indent=20,
                )


def _render_legacy_content(
    writer: PdfWriter,
    doc: DocumentContent,
) -> None:
    if doc.body.strip():
        writer.text(
            doc.body,
        )

    for index, section in enumerate(
        doc.sections,
        start=1,
    ):
        if section.title.strip():
            writer.blank(8)

            writer.text(
                f"{index}. {section.title.strip()}",
                fontsize=HEADING_SIZE,
                bold=True,
            )

        if section.content.strip():
            writer.text(
                section.content,
            )


def render_pdf(
    doc: DocumentContent,
) -> bytes:
    writer = PdfWriter()

    writer.text(
        doc.title.strip() or "문서",
        fontsize=TITLE_SIZE,
        bold=True,
    )

    writer.blank(10)

    if doc.metadata:
        _render_metadata(
            writer,
            doc.metadata,
        )

    if doc.blocks:
        for block in doc.blocks:
            _render_block(
                writer,
                block,
            )
    else:
        _render_legacy_content(
            writer,
            doc,
        )

    return writer.finish()
