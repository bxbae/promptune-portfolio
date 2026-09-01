from __future__ import annotations

import re
from dataclasses import dataclass


from app.schemas.models import ConversationMessage
from app.services.retrieval.query_intent import extract_external_entity_subject
from app.services.conversation_memory import (
    classify_conversation_context,
    is_memory_set_request,
)


@dataclass(frozen=True)
class ConversationRetrievalContext:
    query: str
    route_override: str | None
    used_history: bool


_SENSITIVE_MARKERS = (
    "주민등록번호",
    "주민번호",
    "비밀번호",
    "카드번호",
    "결제번호",
    "계좌번호",
    "계좌 잔액",
    "은행 거래",
    "금융정보",
    "금융 내역",
    "신용정보",
    "인증 코드",
    "인증정보",
    "인증서 비밀번호",
    "신분증 번호",
    "집 주소",
)


def _contains_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


_VERIFICATION_MARKERS = (
    "확실해",
    "확실한가",
    "맞아",
    "맞나요",
    "진짜야",
    "정말이야",
    "근거 있어",
    "근거있어",
    "출처 맞아",
    "출처가 맞아",
    "다시 확인",
    "재확인",
)


def _is_verification_followup(text: str) -> bool:
    lowered = str(text or "").strip().lower()

    return any(
        marker in lowered
        for marker in _VERIFICATION_MARKERS
    )


def _find_previous_substantive_user_query(
    history: list[ConversationMessage],
) -> str:
    for message in reversed(history):
        if message.role != "user":
            continue

        content = message.content.strip()

        if not content:
            continue

        if _is_verification_followup(content):
            continue

        return content

    return ""


def _find_recent_document_reference(
    history: list[ConversationMessage],
) -> str | None:
    attachment_pattern = re.compile(
        r"title=([^/\n]+?\.(?:pdf|docx|doc|xlsx|xls|pptx|txt|md))",
        flags=re.IGNORECASE,
    )
    generic_pattern = re.compile(
        r'([^\s"\'<>]+?\.(?:pdf|docx|doc|xlsx|xls|pptx|txt|md))',
        flags=re.IGNORECASE,
    )

    for message in reversed(history):
        content = message.content.strip()

        if not content:
            continue

        attachment_matches = attachment_pattern.findall(content)

        if attachment_matches:
            return attachment_matches[-1].rstrip(".,!?)]}").strip()

        generic_matches = generic_pattern.findall(content)

        if generic_matches:
            return generic_matches[-1].rstrip(".,!?)]}").strip()

    return None


def _replace_document_reference(
    query: str,
    document_name: str,
) -> str:
    markers = (
        "그 문서",
        "그 파일",
        "그 이력서",
        "그 보고서",
        "거기서",
        "해당 문서",
        "해당 파일",
        "아까 문서",
        "아까 파일",
        "전에 본 문서",
        "전에 본 파일",
    )

    for marker in markers:
        if marker in query:
            return query.replace(marker, document_name, 1)

    return query


_ABOUT_PREVIOUS_SUBJECT_RE = re.compile(
    r"^\s*(?P<subject>.+?)"
    r"\s*에\s*(?:대|관)(?:해|하여)"
)

_FOLLOWUP_ENTITY_MARKERS = (
    "그 회사",
    "그 사람",
    "그분",
    "그 팀",
    "그 그룹",
    "그 프로젝트",
    "그 서비스",
    "그 제품",
    "그거",
    "그걸",
)


def _extract_previous_focus(
    query: str,
) -> str | None:
    """
    직전 사용자 질문에서 명시적인 외부 대상을 가볍게 복원한다.

    LLM을 사용하지 않는다.
    """
    text = str(query or "").strip()

    if not text:
        return None

    entity = extract_external_entity_subject(
        text
    )

    if entity:
        return entity

    match = _ABOUT_PREVIOUS_SUBJECT_RE.match(
        text
    )

    if match:
        subject = (
            match.group("subject")
            .strip(" ,.!?")
        )

        if 2 <= len(subject) <= 80:
            return subject

    return None


def _resolve_followup_query_without_hcx(
    query: str,
    history: list[ConversationMessage],
) -> str:
    """
    검색용 follow-up query를 HCX 없이 복원한다.

    1. 현재 문장에 지시대명사가 있으면 직전 사용자 질문의 명시적
       subject를 추출해 치환한다.
    2. subject를 안전하게 추출하지 못하면 이전 사용자 질문과 현재
       요청을 함께 전달한다.
    3. 지시대명사가 없으면 현재 query를 그대로 유지한다.
    """
    current = str(query or "").strip()

    if not current:
        return current

    has_reference = any(
        marker in current
        for marker in _FOLLOWUP_ENTITY_MARKERS
    )

    if not has_reference:
        return current

    previous_query = (
        _find_previous_substantive_user_query(
            history
        )
    )

    if not previous_query:
        return current

    focus = _extract_previous_focus(
        previous_query
    )

    if focus:
        rewritten = current

        for marker in _FOLLOWUP_ENTITY_MARKERS:
            if marker in rewritten:
                rewritten = rewritten.replace(
                    marker,
                    focus,
                    1,
                )
                break

        return rewritten

    return (
        f"{previous_query} / "
        f"현재 요청: {current}"
    )


def resolve_conversation_retrieval(
    query: str,
    history: list[ConversationMessage],
) -> ConversationRetrievalContext:
    original = query.strip()

    if not original:
        return ConversationRetrievalContext(
            query=original,
            route_override=None,
            used_history=False,
        )

    # 사용자가 새 사실을 "기억해줘/기억해둬"라고 저장하는 요청은
    # 검색이나 RAG 대상이 아니다.
    if is_memory_set_request(original):
        return ConversationRetrievalContext(
            query=original,
            route_override="no_retrieval",
            used_history=False,
        )

    if not history:
        return ConversationRetrievalContext(
            query=original,
            route_override=None,
            used_history=False,
        )

    if _contains_sensitive_text(original):
        return ConversationRetrievalContext(
            query=original,
            route_override=None,
            used_history=False,
        )

    text = original.lower()
    context_mode = classify_conversation_context(original, history)

    # "확실해?", "맞아?", "근거 있어?"처럼 직전 답변의 사실 확인을
    # 요청하는 발화는 그 짧은 문장 자체를 검색어로 사용하지 않는다.
    # 직전의 실질적인 사용자 질문을 그대로 재사용해서 동일 대상을
    # 다시 Retrieval 하도록 한다. HCX query rewrite는 사용하지 않는다.
    if _is_verification_followup(original):
        previous_query = _find_previous_substantive_user_query(
            history
        )

        if previous_query:
            return ConversationRetrievalContext(
                query=previous_query,
                route_override=None,
                used_history=True,
            )

    # "내 프로젝트명이 뭐라고?", "전에 말한 담당자 누구였지?"처럼
    # 사용자가 과거에 직접 말한 사실을 회상하는 질문은 Web/BGE 검색 대상이 아니다.
    # 실제 답변 근거 선택은 generate_hcx의 build_recall_evidence가 담당한다.
    if context_mode == "memory_recall":
        return ConversationRetrievalContext(
            query=original,
            route_override="no_retrieval",
            used_history=True,
        )

    contextual_internal_markers = (
        "그 문서",
        "그 파일",
        "그 이력서",
        "그 보고서",
        "거기서",
        "해당 문서",
        "해당 파일",
        "아까 문서",
        "아까 파일",
        "전에 본 문서",
        "전에 본 파일",
    )

    explicit_internal_markers = (
        "내부 문서",
        "내부문서",
        "업로드한 문서",
        "업로드 문서",
        "업로드한 파일",
        "사내 문서",
        "회사 문서",
        "첨부 문서",
        "첨부파일",
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".txt",
        ".md",
    )

    external_markers = (
        "웹 검색",
        "웹검색",
        "인터넷 검색",
        "검색해",
        "검색해서",
        "찾아봐",
        "최신 뉴스",
        "최신 정보",
        "실시간",
        "오늘 뉴스",
        "현재 환율",
        "오늘 환율",
        "현재 주가",
        "오늘 주가",
        "오늘 날씨",
        "현재 날씨",
    )

    followup_markers = (
        "거기서",
        "무슨 내용",
        "내용이야",
        "내용 알려",
        "프로젝트만",
        "경력만",
        "그거",
        "그걸",
        "그것",
        "그 내용",
        "그 프로젝트",
        "그 사람",
        "그 회사",
        "그 답변",
        "방금",
        "아까",
        "앞에서",
        "앞서",
        "전에 말한",
        "이전에 말한",
        "말했던",
        "말한",
        "작성한",
        "만든",
        "다시",
        "이어서",
        "계속",
        "뭐였",
        "누구였",
        "어디였",
    )

    has_contextual_internal = any(
        marker in text
        for marker in contextual_internal_markers
    )

    has_explicit_internal = any(
        marker in text
        for marker in explicit_internal_markers
    )

    has_external = any(
        marker in text
        for marker in external_markers
    )

    marker_followup = any(
        marker in text
        for marker in followup_markers
    )

    entity_reference_followup = any(
        marker in original
        for marker in _FOLLOWUP_ENTITY_MARKERS
    )

    is_followup = (
        context_mode == "immediate_followup"
        or marker_followup
        or entity_reference_followup
    )

    # "누구였지/뭐였지/어디였지" 자체는 대화 참조의 증거가 아니다.
    # classifier가 standalone으로 판단했다면 기존 broad marker가
    # history를 다시 끌어오지 못하게 한다.
    if (
        context_mode == "standalone"
        and any(
            marker in text
            for marker in (
                "누구였",
                "뭐였",
                "어디였",
                "뭐라고 했",
            )
        )
    ):
        is_followup = False

    if has_contextual_internal:
        document_name = _find_recent_document_reference(history)

        if document_name:
            rewritten = _replace_document_reference(
                original,
                document_name,
            )
        else:
            previous_user = next(
                (
                    message.content.strip()
                    for message in reversed(history)
                    if message.role == "user"
                    and message.content.strip()
                ),
                "",
            )

            rewritten = (
                f"{previous_user} / 현재 요청: {original}"
                if previous_user
                else original
            )

        return ConversationRetrievalContext(
            query=rewritten,
            route_override="internal_rag",
            used_history=True,
        )

    if has_explicit_internal:
        rewritten = (
            _resolve_followup_query_without_hcx(
                original,
                history,
            )
            if is_followup
            else original
        )

        return ConversationRetrievalContext(
            query=rewritten,
            route_override="internal_rag",
            used_history=is_followup,
        )

    if has_external:
        rewritten = (
            _resolve_followup_query_without_hcx(
                original,
                history,
            )
            if is_followup
            else original
        )

        return ConversationRetrievalContext(
            query=rewritten,
            route_override=None,
            used_history=is_followup,
        )

    if is_followup:
        return ConversationRetrievalContext(
            query=original,
            route_override="no_retrieval",
            used_history=True,
        )

    return ConversationRetrievalContext(
        query=original,
        route_override=None,
        used_history=False,
    )
