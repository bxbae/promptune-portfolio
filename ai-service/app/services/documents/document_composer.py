from __future__ import annotations

import json
import logging
import re

from app.services.documents.document_content import (
    DocumentBlock,
    DocumentContent,
    DocumentPlan,
)


logger = logging.getLogger(__name__)


ALLOWED_BLOCK_TYPES = {
    "heading",
    "paragraph",
    "key_value_table",
    "table",
    "bullet_list",
    "numbered_list",
    "callout",
    "signature",
    "page_break",
}


def _extract_json_object(text: str) -> dict:
    cleaned = text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        cleaned,
        flags=re.DOTALL,
    )

    if not match:
        raise ValueError(
            "HCX 응답에서 JSON object를 찾지 못했습니다."
        )

    value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError(
            "Composer 결과가 JSON object가 아닙니다."
        )

    return value


def _clean_text(value) -> str:
    return str(value or "").strip()


def _clean_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []

    result: list[str] = []

    for item in value:
        text = _clean_text(item)

        if text:
            result.append(text)

    return result


def _clean_rows(value) -> list[list[str]]:
    if not isinstance(value, list):
        return []

    rows: list[list[str]] = []

    for row in value:
        if not isinstance(row, list):
            continue

        cleaned = [
            _clean_text(cell)
            for cell in row
        ]

        if any(cleaned):
            rows.append(cleaned)

    return rows


def _clean_data(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    return {
        _clean_text(key): _clean_text(item)
        for key, item in value.items()
        if _clean_text(key) and _clean_text(item)
    }


def _normalize_block(raw: dict) -> DocumentBlock | None:
    if not isinstance(raw, dict):
        return None

    block_type = _clean_text(
        raw.get("type")
    ).lower()

    aliases = {
        "text": "paragraph",
        "body": "paragraph",
        "section": "heading",
        "unordered_list": "bullet_list",
        "ordered_list": "numbered_list",
        "kv_table": "key_value_table",
        "keyvalue": "key_value_table",
    }

    block_type = aliases.get(
        block_type,
        block_type,
    )

    if block_type not in ALLOWED_BLOCK_TYPES:
        content = _clean_text(
            raw.get("content")
            or raw.get("text")
        )

        if not content:
            return None

        block_type = "paragraph"

    return DocumentBlock(
        type=block_type,
        title=_clean_text(raw.get("title")),
        content=_clean_text(
            raw.get("content")
            or raw.get("text")
        ),
        items=_clean_string_list(
            raw.get("items")
        ),
        rows=_clean_rows(
            raw.get("rows")
        ),
        data=_clean_data(
            raw.get("data")
        ),
    )


def _heading_key(text: str) -> str:
    return re.sub(
        r"[^0-9a-z가-힣]+",
        "",
        str(text or "").lower(),
    )


def _dedupe_section_headings(
    blocks: list[DocumentBlock],
) -> list[DocumentBlock]:
    result: list[DocumentBlock] = []
    seen: set[str] = set()

    for block in blocks:
        if block.type == "heading":
            heading = (
                block.content
                or block.title
            ).strip()

            key = _heading_key(heading)

            if key and key in seen:
                continue

            if key:
                seen.add(key)

            result.append(block)
            continue

        if block.title.strip():
            key = _heading_key(block.title)

            if key and key in seen:
                block.title = ""
            elif key:
                seen.add(key)

        result.append(block)

    return result


def _extract_source_metadata(
    plan: DocumentPlan,
    source_material: str,
) -> dict[str, str]:
    metadata: dict[str, str] = {}

    for field in plan.metadata_fields:
        label = field.strip()

        if not label:
            continue

        match = re.search(
            rf"(?m)^\s*{re.escape(label)}\s*[:：]\s*(.*?)\s*$",
            source_material,
        )

        if not match:
            continue

        value = match.group(1).strip()

        if value:
            metadata[label] = value

    return metadata


DATE_PATTERNS = [
    re.compile(
        r"(?<!\\d)(20\\d{2})\\s*년\\s*(\\d{1,2})\\s*월\\s*(\\d{1,2})\\s*일"
    ),
    re.compile(
        r"(?<!\\d)(20\\d{2})[-./](\\d{1,2})[-./](\\d{1,2})(?!\\d)"
    ),
]


def _extract_dates(
    text: str,
) -> list[tuple[tuple[int, int, int], str]]:
    result = []

    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            key = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )

            if not any(
                existing[0] == key
                for existing in result
            ):
                result.append(
                    (key, match.group(0))
                )

    return result


def _preserve_source_date(
    text: str,
    source_material: str,
) -> str:
    source_dates = _extract_dates(
        source_material
    )

    if len(source_dates) != 1:
        return text

    source_key, source_text = source_dates[0]

    def replace(match):
        generated_key = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )

        if generated_key == source_key:
            return match.group(0)

        return source_text

    result = text

    for pattern in DATE_PATTERNS:
        result = pattern.sub(
            replace,
            result,
        )

    return result


def _apply_source_fact_guard(
    title: str,
    blocks: list[DocumentBlock],
    source_material: str,
) -> tuple[str, list[DocumentBlock]]:
    title = _preserve_source_date(
        title,
        source_material,
    )

    for block in blocks:
        block.title = _preserve_source_date(
            block.title,
            source_material,
        )
        block.content = _preserve_source_date(
            block.content,
            source_material,
        )
        block.items = [
            _preserve_source_date(
                item,
                source_material,
            )
            for item in block.items
        ]
        block.rows = [
            [
                _preserve_source_date(
                    cell,
                    source_material,
                )
                for cell in row
            ]
            for row in block.rows
        ]
        block.data = {
            key: _preserve_source_date(
                value,
                source_material,
            )
            for key, value in block.data.items()
        }

    return title, blocks


def _fallback_content(
    plan: DocumentPlan,
    source_material: str,
) -> DocumentContent:
    context = (
        f"{plan.document_kind} "
        f"{plan.title} "
        f"{source_material}"
    ).lower()

    blocks: list[DocumentBlock] = []

    if "보고" in context or "report" in context:
        blocks = [
            DocumentBlock(
                type="key_value_table",
                data={
                    "보고기간": "________________",
                    "작성부서": "________________",
                    "작성자": "________________",
                    "보고대상": "________________",
                },
            ),
            DocumentBlock(
                type="heading",
                content="1. 금주 주요 업무",
            ),
            DocumentBlock(
                type="table",
                rows=[
                    ["업무 항목", "진행 내용", "상태"],
                    ["", "", ""],
                    ["", "", ""],
                    ["", "", ""],
                ],
            ),
            DocumentBlock(
                type="heading",
                content="2. 주요 성과",
            ),
            DocumentBlock(
                type="bullet_list",
                items=[
                    "________________________________",
                    "________________________________",
                ],
            ),
            DocumentBlock(
                type="heading",
                content="3. 이슈 및 리스크",
            ),
            DocumentBlock(
                type="table",
                rows=[
                    ["이슈", "영향", "대응 계획"],
                    ["", "", ""],
                    ["", "", ""],
                ],
            ),
            DocumentBlock(
                type="heading",
                content="4. 차주 추진 계획",
            ),
            DocumentBlock(
                type="table",
                rows=[
                    ["추진 항목", "세부 계획", "일정"],
                    ["", "", ""],
                    ["", "", ""],
                ],
            ),
            DocumentBlock(
                type="heading",
                content="5. 지원 / 결정 요청사항",
            ),
            DocumentBlock(
                type="callout",
                content="________________________________",
            ),
        ]

    elif "회의" in context or "meeting" in context:
        blocks = [
            DocumentBlock(
                type="key_value_table",
                data={
                    "일시": "________________",
                    "장소": "________________",
                    "참석자": "________________",
                    "작성자": "________________",
                },
            ),
            DocumentBlock(
                type="heading",
                content="1. 주요 안건",
            ),
            DocumentBlock(
                type="bullet_list",
                items=[
                    "________________________________",
                    "________________________________",
                ],
            ),
            DocumentBlock(
                type="heading",
                content="2. 논의 내용",
            ),
            DocumentBlock(
                type="paragraph",
                content="________________________________",
            ),
            DocumentBlock(
                type="heading",
                content="3. 결정 사항",
            ),
            DocumentBlock(
                type="callout",
                content="________________________________",
            ),
            DocumentBlock(
                type="heading",
                content="4. Action Items",
            ),
            DocumentBlock(
                type="table",
                rows=[
                    ["업무", "담당자", "기한"],
                    ["", "", ""],
                    ["", "", ""],
                ],
            ),
        ]

    else:
        sections = [
            section.strip()
            for section in plan.section_hints
            if section.strip()
        ]

        for index, section in enumerate(sections, start=1):
            blocks.append(
                DocumentBlock(
                    type="heading",
                    content=f"{index}. {section}",
                )
            )
            blocks.append(
                DocumentBlock(
                    type="paragraph",
                    content="________________________________",
                )
            )

        if not blocks:
            blocks = [
                DocumentBlock(
                    type="heading",
                    content="1. 주요 내용",
                ),
                DocumentBlock(
                    type="paragraph",
                    content="________________________________",
                ),
            ]

    return DocumentContent(
        title=plan.title,
        document_kind=plan.document_kind,
        metadata={},
        blocks=blocks,
    )


def _to_document_content(
    data: dict,
    plan: DocumentPlan,
    source_material: str,
) -> DocumentContent:
    title = _clean_text(
        data.get("title")
    ) or plan.title

    raw_metadata = data.get("metadata")

    metadata = _extract_source_metadata(
        plan,
        source_material,
    )

    if isinstance(raw_metadata, dict):
        allowed_fields = {
            field.strip()
            for field in plan.metadata_fields
            if field.strip()
        }

        for key, value in raw_metadata.items():
            key_text = _clean_text(key)
            value_text = _clean_text(value)

            if not key_text or not value_text:
                continue

            if (
                allowed_fields
                and key_text not in allowed_fields
            ):
                continue

            if key_text in metadata:
                continue

            if value_text not in source_material:
                continue

            metadata[key_text] = value_text

    blocks: list[DocumentBlock] = []

    raw_blocks = data.get("blocks")

    if isinstance(raw_blocks, list):
        for raw_block in raw_blocks[:40]:
            block = _normalize_block(raw_block)

            if block is not None:
                blocks.append(block)

    if not blocks:
        return _fallback_content(
            plan,
            source_material,
        )

    section_titles = {
        section.strip()
        for section in plan.section_hints
        if section.strip()
    }

    normalized_blocks: list[DocumentBlock] = []

    for block in blocks:
        content = block.content.strip()

        if (
            block.type == "heading"
            and content
            and content == title.strip()
        ):
            continue

        if (
            block.type == "paragraph"
            and content in section_titles
        ):
            block.type = "heading"

        normalized_blocks.append(block)

    blocks = _dedupe_section_headings(
        normalized_blocks
    )

    title, blocks = _apply_source_fact_guard(
        title,
        blocks,
        source_material,
    )

    return DocumentContent(
        title=title,
        document_kind=plan.document_kind,
        metadata=metadata,
        blocks=blocks,
    )


def compose_document(
    plan: DocumentPlan,
    source_material: str,
) -> DocumentContent:
    import torch

    from app.services.hcx_runtime import (
        HCX_MODEL_LOCK,
        load_hcx_runtime,
    )

    source = source_material.strip()

    if not source:
        return _fallback_content(
            plan,
            source,
        )

    plan_text = json.dumps(
        {
            "document_kind": plan.document_kind,
            "title": plan.title,
            "purpose": plan.purpose,
            "audience": plan.audience,
            "metadata_fields": plan.metadata_fields,
            "section_hints": plan.section_hints,
            "layout_hint": plan.layout_hint,
        },
        ensure_ascii=False,
        indent=2,
    )

    system_prompt = """
너는 기업용 문서 작성 시스템의 Document Composer다.

DocumentPlan과 사용자 자료를 바탕으로
실제 문서에 들어갈 내용을 구조화해서 작성한다.

중요 원칙:
1. 제공되지 않은 사실, 사람, 날짜, 수치, 회사 정보를 만들어내지 않는다.
2. source_material에 있는 사실을 우선 사용한다.
3. DocumentPlan의 목적, 독자, 섹션 구성을 따른다.
4. 필요한 경우 문장을 자연스럽게 정리하거나 요약할 수 있다.
5. 문서 종류에 맞는 업무 문체를 사용한다.
6. 보고서에만 맞춘 구조를 강요하지 않는다.
7. 표가 유용하면 table 또는 key_value_table을 사용한다.
8. 항목 나열이 유용하면 bullet_list 또는 numbered_list를 사용한다.
9. metadata 값은 source_material에서 확인 가능한 값만 사용한다.
10. 작성자, 직급, 부서, 날짜, 회사명 등 제공되지 않은 정보를 추론해서 만들지 않는다.
11. source_material의 사실 문장과 작업 항목을 임의로 삭제하지 않는다.
12. source_material의 중요한 기술명, 결정 사항, 조건, 순서를 요약 과정에서 없애지 않는다.
13. source_material에 없는 서론, 인사말, 일반적인 설명 문장을 새로 만들지 않는다.
14. DocumentPlan의 section_hints를 섹션 제목으로 사용할 경우 반드시 heading block으로 출력한다.
15. 섹션 제목만 있는 내용을 paragraph block으로 출력하지 않는다.
16. 서로 다른 주제는 가능한 한 별도의 block으로 나눈다.
17. source_material에 여러 bullet 항목이 있으면 하나의 문장으로 합치지 말고 bullet_list의 items로 보존한다.
18. "다음 할 일:", "Action Items:"처럼 목록을 소개하는 문구 뒤에 여러 항목이 있으면 heading + bullet_list 구조를 우선 사용한다.
19. source_material에 명시된 각 주요 사실은 최종 blocks 어딘가에 최소 한 번 포함되어야 한다.
20. 같은 내용을 여러 block에 중복 작성하지 않는다.
21. 문서 제목을 blocks 안에서 다시 heading으로 반복하지 않는다.
22. source_material에는 사용자의 문서 생성 지시가 포함될 수 있다. "만들어줘", "작성해줘", "구성하세요", "사실을 임의로 만들지 마세요" 같은 명령문은 최종 문서 본문에 복사하지 않는다.
23. 사용자가 양식 또는 템플릿을 요청했지만 실제 채울 정보가 없다면, 업무에 바로 사용할 수 있는 제목·메타데이터·섹션·표·작성란을 가진 빈 양식을 생성한다.
24. 제공되지 않은 사실을 만들면 안 되지만, 빈칸·작성란·placeholder를 만드는 것은 허용된다.
25. 반드시 JSON object 하나만 출력한다.
23. source_material에 명시된 날짜는 표기를 그대로 보존하며 다른 날짜로 변경하거나 추론하지 않는다.

사용 가능한 block type:
- heading
- paragraph
- key_value_table
- table
- bullet_list
- numbered_list
- callout
- signature
- page_break

출력 예시 구조:
{
  "title": "실제 문서 제목",
  "metadata": {
    "작성일": "",
    "작성자": ""
  },
  "blocks": [
    {
      "type": "heading",
      "content": "섹션 제목"
    },
    {
      "type": "paragraph",
      "content": "실제 본문"
    },
    {
      "type": "bullet_list",
      "items": [
        "항목 1",
        "항목 2"
      ]
    },
    {
      "type": "table",
      "rows": [
        ["항목", "내용"],
        ["예시", "예시"]
      ]
    }
  ]
}

규칙:
- 위 예시의 내용을 그대로 복사하지 않는다.
- DocumentPlan에 맞게 필요한 block만 사용한다.
- JSON 밖의 설명이나 Markdown 코드블록을 출력하지 않는다.
""".strip()

    user_prompt = (
        "[DocumentPlan]\n"
        f"{plan_text}\n\n"
        "[사용자 자료]\n"
        f"{source}"
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    try:
        tokenizer, model, device = load_hcx_runtime()

        inputs = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )

        inputs = inputs.to(device)

        with HCX_MODEL_LOCK:
            with torch.inference_mode():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=384,
                    do_sample=False,
                    eos_token_id=tokenizer.eos_token_id,
                    stop_strings=[
                        "<|endofturn|>",
                        "<|stop|>",
                    ],
                    tokenizer=tokenizer,
                )

        generated = outputs[0][
            inputs["input_ids"].shape[-1]:
        ]

        result = tokenizer.decode(
            generated,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        ).strip()

        data = _extract_json_object(result)

        document = _to_document_content(
            data,
            plan,
            source,
        )

        logger.info(
            "Document composer kind=%s blocks=%d",
            plan.document_kind,
            len(document.blocks),
        )

        return document

    except Exception as exc:
        raw_result = locals().get("result", "")

        logger.warning(
            "Document composer fallback: %s / raw=%r",
            exc,
            str(raw_result)[:1000],
        )

        return _fallback_content(
            plan,
            source,
        )
