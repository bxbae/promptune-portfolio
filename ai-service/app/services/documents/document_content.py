from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BlockType = Literal[
    "heading",
    "paragraph",
    "key_value_table",
    "table",
    "bullet_list",
    "numbered_list",
    "callout",
    "signature",
    "page_break",
]


@dataclass
class DocumentBlock:
    type: BlockType

    title: str = ""
    content: str = ""

    items: list[str] = field(default_factory=list)

    rows: list[list[str]] = field(default_factory=list)

    data: dict[str, str] = field(default_factory=dict)


@dataclass
class DocumentPlan:
    document_kind: str
    title: str

    purpose: str = ""
    audience: str = ""

    metadata_fields: list[str] = field(default_factory=list)

    section_hints: list[str] = field(default_factory=list)

    layout_hint: str = "standard"

    blueprint_key: str = "FREEFORM"

    style_profile: str = "corporate_clean"


@dataclass
class DocumentSection:
    title: str
    content: str


@dataclass
class DocumentContent:
    title: str

    metadata: dict[str, str] = field(default_factory=dict)

    blocks: list[DocumentBlock] = field(default_factory=list)

    sections: list[DocumentSection] = field(default_factory=list)

    body: str = ""

    document_kind: str = "generic"

    blueprint_key: str = "FREEFORM"

    style_profile: str = "corporate_clean"

    layout_hint: str = "standard"

    def is_structured(self) -> bool:
        return bool(
            self.metadata
            or self.blocks
            or self.sections
        )

    def to_plain_text(self) -> str:
        parts: list[str] = []

        if self.title:
            parts.append(self.title)

        if self.metadata:
            if parts:
                parts.append("")

            for key, value in self.metadata.items():
                if value:
                    parts.append(f"{key}: {value}")

        if self.blocks:
            for block in self.blocks:
                if block.type == "page_break":
                    parts.append("")
                    continue

                if block.title:
                    parts.append("")
                    parts.append(block.title)

                if block.content:
                    parts.append(block.content)

                if block.data:
                    for key, value in block.data.items():
                        parts.append(f"{key}: {value}")

                if block.items:
                    for item in block.items:
                        parts.append(f"- {item}")

                if block.rows:
                    for row in block.rows:
                        parts.append(" | ".join(row))

        elif self.sections:
            for section in self.sections:
                if parts:
                    parts.append("")

                if section.title:
                    parts.append(section.title)

                if section.content:
                    parts.append(section.content)

        if self.body:
            if parts:
                parts.append("")

            parts.append(self.body)

        return "\n".join(parts).strip()
