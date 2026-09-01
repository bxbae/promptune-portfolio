from __future__ import annotations

import json
import logging
import re


from app.services.documents.blueprint_registry import (
    BLUEPRINTS,
    get_blueprint,
)
from app.services.documents.document_content import DocumentPlan


logger = logging.getLogger(__name__)


def _fallback_plan(user_request: str) -> DocumentPlan:
    request = user_request.strip()

    return DocumentPlan(
        document_kind="generic",
        title="업무 문서",
        purpose=request[:300],
        audience="",
        metadata_fields=[],
        section_hints=[
            "개요",
            "주요 내용",
            "결론 및 다음 단계",
        ],
        layout_hint="standard",
        blueprint_key="FREEFORM",
        style_profile="corporate_clean",
    )


def _extract_json(text: str) -> dict:
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
        raise ValueError("HCX 응답에서 JSON 객체를 찾지 못했습니다.")

    value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("DocumentPlan 응답이 JSON object가 아닙니다.")

    return value


def _clean_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []

    result: list[str] = []

    for item in value:
        text = str(item or "").strip()

        if text and text not in result:
            result.append(text)

    return result


def _normalize_blueprint_key(value) -> str:
    key = str(value or "").strip().upper()

    if key in BLUEPRINTS:
        return key

    return "FREEFORM"


def _normalize_style_profile(value) -> str:
    style = str(value or "").strip().lower()

    allowed = {
        "corporate_clean",
        "formal_korean",
        "executive_report",
        "compact_memo",
        "modern_project",
        "minimal",
    }

    if style in allowed:
        return style

    return "corporate_clean"


def _to_document_plan(
    data: dict,
    user_request: str,
) -> DocumentPlan:
    fallback = _fallback_plan(user_request)

    document_kind = str(
        data.get("document_kind") or ""
    ).strip()

    invalid_document_kinds = {
        "",
        "generic",
        "document_kind",
        "문서 종류",
        "문서 종류 식별자",
        "자유로운 문서 종류 식별자",
        "standard",
        "formal",
        "compact",
        "table_focused",
        "freeform",
    }

    if document_kind.lower() in invalid_document_kinds:
        document_kind = fallback.document_kind

    title = str(
        data.get("title") or ""
    ).strip() or fallback.title

    purpose = str(
        data.get("purpose") or ""
    ).strip() or fallback.purpose

    audience = str(
        data.get("audience") or ""
    ).strip()

    metadata_fields = _clean_string_list(
        data.get("metadata_fields")
    )

    section_hints = _clean_string_list(
        data.get("section_hints")
        or data.get("section_hint")
        or data.get("sections")
        or data.get("section_titles")
    )

    if not section_hints:
        section_hints = fallback.section_hints

    metadata_fields = [
        field
        for field in metadata_fields
        if "본문" not in field
    ]

    raw_layout_hint = str(
        data.get("layout_hint") or ""
    ).strip().lower()

    layout_aliases = {
        "자유로운 문서 형식": "freeform",
        "자유 형식": "freeform",
        "자유형식": "freeform",
        "정형": "formal",
        "공식": "formal",
        "간결": "compact",
        "표 중심": "table_focused",
        "표 형식": "table_focused",
    }

    layout_hint = layout_aliases.get(
        raw_layout_hint,
        raw_layout_hint,
    )

    allowed_layouts = {
        "standard",
        "formal",
        "compact",
        "table_focused",
        "freeform",
    }

    if layout_hint not in allowed_layouts:
        layout_hint = "standard"

    blueprint_key = _normalize_blueprint_key(
        data.get("blueprint_key")
        or data.get("blueprint")
    )

    style_profile = _normalize_style_profile(
        data.get("style_profile")
        or data.get("style")
    )

    blueprint = get_blueprint(blueprint_key)

    if not metadata_fields and blueprint.metadata_fields:
        metadata_fields = list(
            blueprint.metadata_fields
        )

    if (
        len(section_hints) < 3
        and blueprint.section_roles
    ):
        section_hints = list(
            blueprint.section_roles
        )

    return DocumentPlan(
        document_kind=document_kind,
        title=title,
        purpose=purpose,
        audience=audience,
        metadata_fields=metadata_fields[:12],
        section_hints=section_hints[:15],
        layout_hint=layout_hint,
        blueprint_key=blueprint_key,
        style_profile=style_profile,
    )


def build_document_plan(
    user_request: str,
) -> DocumentPlan:
    import torch
    from app.services.hcx_runtime import (
        HCX_MODEL_LOCK,
        load_hcx_runtime,
    )
    request = user_request.strip()

    if not request:
        return _fallback_plan(request)

    system_prompt = """
너는 기업용 문서 작성 시스템의 Document Planner다.

사용자의 요청을 읽고 실제 문서를 작성하기 전에
그 요청에 가장 적합한 문서의 종류와 구조를 설계한다.

중요:
- 문서 종류는 고정 enum이 아니다.
- 사용자의 목적에 맞는 실제 문서 종류를 자유롭게 판단한다.
- 처음 보는 문서 요청도 가장 자연스러운 업무 문서 형태를 설계한다.
- 사용자가 특정 양식이나 항목을 요구하면 그 요구를 우선한다.
- 회사 제출용 요청에서 사용자의 실수, 지각, 과실, 사고, 문제 발생 경위와 재발 방지를 설명해야 한다면 자기계발 문서가 아니라 경위서, 시말서, 사유서 등 공식 소명 문서 성격으로 판단한다.
- 문서 종류는 사용자의 실제 업무 목적과 제출 상황을 가장 우선하여 판단한다.
- 여기서는 본문을 작성하지 않고 문서 구조만 설계한다.

각 필드의 의미:

document_kind
- 실제 문서의 종류 이름이다.
- 예: "회의록", "서비스 도입 제안서", "시말서", "프로젝트 진행 현황", "업무 정리 문서"
- "formal", "standard", "freeform" 같은 레이아웃 이름을 넣으면 안 된다.
- "자유로운 문서 종류 식별자", "문서 종류" 같은 설명문을 그대로 출력하면 안 된다.

title
- 실제 문서에 표시할 자연스러운 제목이다.
- 너무 길게 만들지 않는다.

purpose
- 이 문서를 왜 만드는지 한 문장으로 설명한다.

audience
- 실제 열람자, 제출 대상 또는 공유 대상을 적는다.
- 알 수 없으면 빈 문자열로 둔다.

metadata_fields
- 문서 상단의 짧은 기본 정보 필드만 넣는다.
- 예: 작성일, 작성자, 부서, 회의일시, 참석자, 제출대상, 문서번호
- 본문의 주제나 설명은 넣지 않는다.
- "프롬프트 보정", "업무 효율성 향상", "서비스 기능", "회의록 본문" 같은 본문 내용은 metadata가 아니다.

section_hints
- 실제 문서 본문을 구성할 목차 또는 주요 섹션 제목이다.
- 사용자의 요청에 맞게 2~8개 정도 설계한다.
- 사용자가 언급한 핵심 내용이 있으면 해당 내용이 자연스럽게 포함되도록 한다.
- 무조건 "개요/주요 내용/결론"만 반복하지 말고 문서 목적에 맞게 구체적으로 설계한다.

blueprint_key
- 문서 구조 설계에 참고할 soft blueprint다.
- 반드시 다음 중 가장 가까운 하나를 선택한다:
  MEETING
  REPORT
  PROPOSAL
  PLAN
  INCIDENT
  NOTICE
  HANDOVER
  FORMAL_STATEMENT
  SUMMARY
  FREEFORM
- 정확히 맞는 유형이 없으면 FREEFORM을 사용한다.
- blueprint는 문서 종류 자체가 아니며 document_kind를 대체하지 않는다.

style_profile
- 문서의 시각적 표현 방향이다.
- 반드시 다음 중 하나를 사용한다:
  corporate_clean
  formal_korean
  executive_report
  compact_memo
  modern_project
  minimal

layout_hint
- 반드시 다음 중 하나만 사용한다:
  standard
  formal
  compact
  table_focused
  freeform

예시 1:
사용자 요청:
"오늘 프로젝트 회의 내용을 팀원들과 공유할 회의 문서로 정리"

좋은 결과:
{
  "document_kind": "프로젝트 회의록",
  "title": "프로젝트 회의록",
  "purpose": "프로젝트 회의 논의 및 결정 사항 공유",
  "audience": "프로젝트 팀원",
  "metadata_fields": ["회의일시", "참석자", "작성자"],
  "section_hints": ["회의 목적", "주요 논의 사항", "결정 사항", "Action Items", "향후 일정"],
  "layout_hint": "table_focused",
  "blueprint_key": "MEETING",
  "style_profile": "modern_project"
}

예시 2:
사용자 요청:
"AI 업무 서비스를 경영진에게 제안하는 문서를 작성"

좋은 결과:
{
  "document_kind": "서비스 도입 제안서",
  "title": "AI 업무 지원 서비스 도입 제안서",
  "purpose": "AI 업무 지원 서비스의 도입 필요성과 기대 효과 제안",
  "audience": "경영진",
  "metadata_fields": ["작성일", "작성자", "제안부서"],
  "section_hints": ["제안 배경", "현재 문제점", "서비스 개요", "주요 기능", "기대 효과", "도입 방안"],
  "layout_hint": "formal",
  "blueprint_key": "PROPOSAL",
  "style_profile": "executive_report"
}

예시 3:
사용자 요청:
"특별한 양식 없이 이번 주 개발 작업과 다음 할 일을 보기 좋게 정리"

좋은 결과:
{
  "document_kind": "주간 개발 진행 현황",
  "title": "주간 개발 진행 현황",
  "purpose": "이번 주 개발 진행 상황과 다음 작업 공유",
  "audience": "팀원",
  "metadata_fields": ["작성일", "작성자"],
  "section_hints": ["이번 주 주요 작업", "완료 사항", "진행 중인 사항", "이슈 및 검토 사항", "다음 할 일"],
  "layout_hint": "standard",
  "blueprint_key": "REPORT",
  "style_profile": "corporate_clean"
}

출력 규칙:
1. 반드시 JSON object 하나만 출력한다.
2. Markdown 코드블록을 사용하지 않는다.
3. JSON 앞뒤에 설명을 붙이지 않는다.
4. 위 예시를 복사하지 말고 현재 사용자 요청에 맞게 새로 판단한다.
""".strip()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": request,
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

        data = _extract_json(result)

        plan = _to_document_plan(
            data,
            request,
        )

        logger.info(
            "Document planner kind=%s title=%s sections=%d",
            plan.document_kind,
            plan.title,
            len(plan.section_hints),
        )

        return plan

    except Exception as exc:
        logger.warning(
            "Document planner fallback: %s",
            exc,
        )
        return _fallback_plan(request)
