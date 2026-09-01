from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocumentBlueprint:
    key: str
    description: str
    metadata_fields: list[str] = field(default_factory=list)
    section_roles: list[str] = field(default_factory=list)
    recommended_blocks: list[str] = field(default_factory=list)


BLUEPRINTS: dict[str, DocumentBlueprint] = {
    "MEETING": DocumentBlueprint(
        key="MEETING",
        description="회의, 미팅, 협의 내용을 기록하는 문서",
        metadata_fields=[
            "회의명",
            "일시",
            "참석자",
            "작성자",
        ],
        section_roles=[
            "회의 목적",
            "주요 안건",
            "논의 내용",
            "결정 사항",
            "Action Items",
            "향후 일정",
        ],
        recommended_blocks=[
            "key_value_table",
            "bullet_list",
            "paragraph",
            "callout",
            "table",
        ],
    ),
    "REPORT": DocumentBlueprint(
        key="REPORT",
        description="업무 현황, 결과, 분석 내용을 보고하는 문서",
        metadata_fields=[
            "문서명",
            "작성일",
            "작성부서",
            "작성자",
            "보고대상",
        ],
        section_roles=[
            "보고 목적",
            "배경",
            "주요 내용",
            "현황 및 문제점",
            "검토 및 분석",
            "조치 계획",
            "결론 및 요청사항",
        ],
        recommended_blocks=[
            "key_value_table",
            "paragraph",
            "table",
            "bullet_list",
            "callout",
        ],
    ),
    "PROPOSAL": DocumentBlueprint(
        key="PROPOSAL",
        description="서비스, 정책, 프로젝트 등의 도입이나 개선을 제안하는 문서",
        metadata_fields=[
            "제안명",
            "작성일",
            "작성자",
            "대상",
        ],
        section_roles=[
            "제안 배경",
            "문제 정의",
            "제안 내용",
            "실행 방안",
            "기대 효과",
            "일정 및 비용",
            "요청 사항",
        ],
        recommended_blocks=[
            "key_value_table",
            "paragraph",
            "bullet_list",
            "table",
            "callout",
        ],
    ),
    "PLAN": DocumentBlueprint(
        key="PLAN",
        description="프로젝트나 업무의 실행 계획을 정리하는 문서",
        metadata_fields=[
            "계획명",
            "작성일",
            "담당자",
            "기간",
        ],
        section_roles=[
            "목표",
            "범위",
            "추진 일정",
            "역할 및 담당",
            "실행 계획",
            "리스크 및 대응",
            "완료 기준",
        ],
        recommended_blocks=[
            "key_value_table",
            "bullet_list",
            "table",
            "numbered_list",
            "callout",
        ],
    ),
    "INCIDENT": DocumentBlueprint(
        key="INCIDENT",
        description="장애, 사고, 문제 발생 경위와 조치를 기록하는 문서",
        metadata_fields=[
            "사건명",
            "발생일시",
            "작성자",
            "관련부서",
        ],
        section_roles=[
            "발생 개요",
            "발생 경위",
            "원인",
            "영향 범위",
            "즉시 조치",
            "후속 조치",
            "재발 방지 대책",
        ],
        recommended_blocks=[
            "key_value_table",
            "paragraph",
            "numbered_list",
            "table",
            "callout",
        ],
    ),
    "NOTICE": DocumentBlueprint(
        key="NOTICE",
        description="구성원에게 일정, 정책, 변경사항 등을 안내하는 문서",
        metadata_fields=[
            "제목",
            "작성일",
            "대상",
        ],
        section_roles=[
            "안내 목적",
            "주요 내용",
            "적용 대상",
            "일정",
            "유의 사항",
            "문의 안내",
        ],
        recommended_blocks=[
            "paragraph",
            "bullet_list",
            "callout",
        ],
    ),
    "HANDOVER": DocumentBlueprint(
        key="HANDOVER",
        description="업무 인수인계 내용을 체계적으로 전달하는 문서",
        metadata_fields=[
            "업무명",
            "인계자",
            "인수자",
            "인계일",
        ],
        section_roles=[
            "업무 개요",
            "현재 진행 상황",
            "정기 업무",
            "주요 자료 및 위치",
            "미결 사항",
            "주의 사항",
            "연락 및 담당자",
        ],
        recommended_blocks=[
            "key_value_table",
            "table",
            "bullet_list",
            "callout",
        ],
    ),
    "FORMAL_STATEMENT": DocumentBlueprint(
        key="FORMAL_STATEMENT",
        description="경위서, 사유서, 시말서 등 공식 사실관계 설명 문서",
        metadata_fields=[
            "문서명",
            "작성일",
            "소속",
            "작성자",
        ],
        section_roles=[
            "발생 사실",
            "경위",
            "원인 및 사유",
            "조치 내용",
            "재발 방지 계획",
        ],
        recommended_blocks=[
            "key_value_table",
            "paragraph",
            "numbered_list",
            "signature",
        ],
    ),
    "SUMMARY": DocumentBlueprint(
        key="SUMMARY",
        description="긴 내용을 핵심 위주로 요약하는 문서",
        metadata_fields=[
            "제목",
            "작성일",
        ],
        section_roles=[
            "개요",
            "핵심 내용",
            "주요 결정 및 시사점",
            "다음 단계",
        ],
        recommended_blocks=[
            "paragraph",
            "bullet_list",
            "callout",
        ],
    ),
    "FREEFORM": DocumentBlueprint(
        key="FREEFORM",
        description="정해진 대표 유형에 맞지 않아 AI가 목적에 맞게 구조를 설계하는 문서",
        metadata_fields=[],
        section_roles=[],
        recommended_blocks=[
            "heading",
            "paragraph",
            "bullet_list",
            "table",
            "callout",
        ],
    ),
}


def get_blueprint(key: str | None) -> DocumentBlueprint:
    normalized = str(key or "").strip().upper()

    return BLUEPRINTS.get(
        normalized,
        BLUEPRINTS["FREEFORM"],
    )


def list_blueprints() -> list[DocumentBlueprint]:
    return list(BLUEPRINTS.values())
