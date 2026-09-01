from __future__ import annotations

import logging
import re
from datetime import datetime

import torch

from app.schemas.models import GenerateRequest, GenerateResponse
from app.services.hcx_runtime import hcx_lock, load_hcx_runtime
from app.services.conversation_memory import (
    build_recall_evidence,
    select_relevant_history,
)
from app.services.context_budget import (
    MAX_RECALL_EVIDENCE_CHARS,
    budget_history,
    truncate_context_text,
)
from app.services.retrieval.date_resolver import KST
from app.services.retrieval.retrieval_context import build_internal_context


logger = logging.getLogger(__name__)


def _build_internal_context(
    req: GenerateRequest,
) -> str:
    return build_internal_context(req.documents)


_WEB_FACT_MARKERS = (
    "본명",
    "실명",
    "생년월일",
    "출생",
    "소속",
    "직책",
    "등번호",
    "경력",
    "프로필",
)


def _compact_web_content(
    content: str,
    *,
    max_chars: int = 700,
) -> str:
    """
    검색 결과의 첫 N자만 자르면 프로필의 본명/소속 같은 핵심 사실이
    뒤쪽에 있을 때 HCX가 실제 evidence를 보지 못한다.

    전체 본문을 넣어 context를 폭증시키지 않고,
    첫 부분 + 중요 사실 marker 주변 snippet만 보존한다.
    """
    text = str(content or "").strip()

    if len(text) <= max_chars:
        return text

    segments = [text[:260]]
    seen = {segments[0]}

    for marker in _WEB_FACT_MARKERS:
        position = text.find(marker)

        if position < 0:
            continue

        start = max(
            0,
            position - 80,
        )
        end = min(
            len(text),
            position + 220,
        )

        snippet = text[start:end].strip()

        if snippet and snippet not in seen:
            segments.append(snippet)
            seen.add(snippet)

    compact = "\n...\n".join(segments)

    return compact[:max_chars]


def _build_web_context(web_results: list[dict]) -> str:
    if not web_results:
        return "없음"

    parts: list[str] = []

    for index, item in enumerate(web_results, start=1):
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        content = str(item.get("content", "")).strip()

        # 2026-08-25: 1200자였을 때 검색결과 3개(top_k=3)까지 합쳐 최대 3600자+가
        # 프롬프트에 통째로 들어가면서 t3.large CPU에서 generate() 한 번에 9분
        # 가까이 걸리는 문제가 있어(nginx 5분 타임아웃 초과) top_k를 1로,
        # 결과당 본문도 400자로 축소했었음.
        #
        # 2026-08-26: 그런데 결과가 1개뿐이면 검색엔진이 상위에 올린 기사가
        # 실제 "결과" 기사가 아니라 "프리뷰/예측" 기사인 경우에도 그 하나를
        # 그대로 근거로 써야 해서, 스코어가 없는 기사를 보고 모델이 결과를
        # 잘못 답하는 사례가 확인됨(예: 어제 LG-NC전 승패를 반대로 답함).
        # GPU 인스턴스로 전환(2026-08-26)하면서 t3.large 시절의 CPU 지연
        # 문제는 더 이상 해당되지 않으므로, top_k를 3으로 되돌리고(백엔드
        # PipelineController.java) 결과당 본문도 600자로 다시 늘림 -
        # 3개 x 600자 = 최대 1800자로, 문제가 됐던 3600자보다는 여전히
        # 작게 유지해 안전 마진을 둠.
        content = _compact_web_content(
            content
        )

        parts.append(
            f"[웹 검색 결과 {index}]\n"
            f"제목: {title}\n"
            f"URL: {url}\n"
            f"내용: {content}"
        )
    return "\n\n".join(parts)


def _build_user_context(user_context: dict[str, str]) -> str:
    if not user_context:
        return "없음"

    labels = {
        "displayName": "이름",
        "companyName": "회사",
        "department": "부서",
        "jobTitle": "직급/직책",
        "mail": "이메일",
    }

    parts = []
    for key, value in user_context.items():
        value = str(value or "").strip()
        if value:
            parts.append(f"{labels.get(key, key)}: {value}")

    return "\n".join(parts) if parts else "없음"



def _build_preference_context(preference: dict[str, str]) -> str:
    if not preference:
        return "없음"

    labels = {
        "speed": "속도",
        "detail": "설명 분량",
        "preserve": "원문 존중도",
        "receiverTone": "수신자 존댓말 수위",
    }

    value_labels = {
        "fast": "빠르게",
        "accurate": "정확하게",
        "brief": "간결하게",
        "detailed": "자세하게",
        "keep": "원문 최대한 유지",
        "improve": "적극적으로 보완",
    }

    parts: list[str] = []

    for key, value in preference.items():
        value = str(value or "").strip()

        if value:
            label = labels.get(key, key)
            value_label = value_labels.get(value, value)
            parts.append(f"{label}: {value_label}")

    return "\n".join(parts) if parts else "없음"



def _build_recent_user_evidence(
    req: GenerateRequest,
) -> str:
    evidence = build_recall_evidence(
        req.prompt,
        req.history or [],
    )

    if evidence == "없음":
        return evidence

    return truncate_context_text(
        evidence,
        MAX_RECALL_EVIDENCE_CHARS,
    )


def _build_effective_user_prompt(req: GenerateRequest) -> str:
    """
    Retrieval에서는 원본 사용자 요청을 사용하고,
    Generation에서는 이미 검색된 문서의 파일명(locator)을 제거해
    실제 수행할 요청만 HCX에 전달한다.
    """
    original = req.prompt.strip()

    if not original or not req.documents:
        return original

    titles = sorted(
        {
            document.title.strip()
            for document in req.documents
            if document.title and document.title.strip()
        },
        key=len,
        reverse=True,
    )

    normalized = original
    matched_title = False

    for title in titles:
        candidates = [
            title + "의 ",
            title + "에서 ",
            title + "을 ",
            title + "를 ",
            title + "으로 ",
            title + "로 ",
            title,
        ]

        for candidate in candidates:
            if candidate in normalized:
                normalized = normalized.replace(candidate, "", 1)
                matched_title = True
                break

    if not matched_title:
        return original

    prefixes = [
        "내부 문서에서 ",
        "내부문서에서 ",
        "사내 문서에서 ",
        "사내문서에서 ",
        "회사 문서에서 ",
        "회사문서에서 ",
    ]

    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break

    normalized = " ".join(normalized.split()).strip()

    if not normalized:
        normalized = "핵심 내용을 알려줘"

    return "제공된 내부 문서에서 " + normalized



_DOCUMENT_OVERVIEW_MARKERS = (
    "무슨 내용",
    "어떤 내용",
    "내용이야",
    "내용 알려",
    "전체 내용",
    "전체내용",
    "전체 요약",
    "전체요약",
    "문서 요약",
    "파일 요약",
    "요약해줘",
    "요약해 줘",
    "읽어줘",
    "읽어 줘",
    "불러와줘",
    "불러와 줘",
    "불러줘",
    "불러 줘",
    "열어줘",
    "열어 줘",
    "핵심 내용",
    "핵심내용",
)

_PREVIOUS_ANSWER_DEPENDENT_MARKERS = (
    "방금 답변",
    "앞 답변",
    "이전 답변",
    "앞에서 말한",
    "위에서 말한",
    "그 부분",
    "그 항목",
    "그 설명",
    "첫 번째",
    "두 번째",
    "세 번째",
    "더 자세",
    "좀 더",
    "이어서",
    "계속 설명",
)


def _is_document_overview_request(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    return any(marker in text for marker in _DOCUMENT_OVERVIEW_MARKERS)


def _document_titles(req: GenerateRequest) -> list[str]:
    return list(
        dict.fromkeys(
            document.title.strip()
            for document in req.documents
            if document.title and document.title.strip()
        )
    )


def _needs_previous_answer_context(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    return any(marker in text for marker in _PREVIOUS_ANSWER_DEPENDENT_MARKERS)


def _build_overview_evidence(req: GenerateRequest) -> str:
    """Build a compact, broad evidence view for document overview questions.

    A small instruction model can over-focus on one part of a long document.  For an
    overview, surface the beginning of every retrieved chunk in addition to the full
    context so the model sees multiple sections/roles/features before it starts
    summarising.  The text is copied from the source; nothing is inferred here.
    """
    if not req.documents:
        return "없음"

    chunks = sorted(
        req.documents,
        key=lambda item: (
            item.document_id is None,
            item.document_id if item.document_id is not None else 10**18,
            item.chunk_index is None,
            item.chunk_index if item.chunk_index is not None else 10**9,
        ),
    )

    excerpts: list[str] = []
    total = 0

    for chunk in chunks:
        content = re.sub(r"\s+", " ", (chunk.content or "").strip())
        if not content:
            continue

        excerpt = content[:520].strip()
        if not excerpt:
            continue

        label = (
            f"chunk {chunk.chunk_index}"
            if chunk.chunk_index is not None
            else "chunk"
        )
        excerpts.append(f"- [{label}] {excerpt}")
        total += len(excerpt)

        if len(excerpts) >= 8 or total >= 3200:
            break

    return "\n".join(excerpts) if excerpts else "없음"


def _select_generation_history(req: GenerateRequest):
    """Select and budget only history needed for the current answer."""
    if not req.documents:
        selected = select_relevant_history(
            req.prompt,
            req.history or [],
        )

        return budget_history(
            selected
        )

    if not _needs_previous_answer_context(
        req.prompt
    ):
        return []

    selected = [
        message
        for message in req.history[-2:]
        if message.content.strip()
    ]

    return budget_history(
        selected
    )


def _build_generation_user_prompt(
    req: GenerateRequest,
    web_results: list[dict] | None = None,
) -> str:
    """Put the resolved document and source evidence in the final user turn."""
    user_prompt = _build_effective_user_prompt(req)
    overview = _is_document_overview_request(
        req.prompt
    )

    internal_context = (
        _build_overview_evidence(req)
        if overview
        else _build_internal_context(req)
    )

    web_context = _build_web_context(
        web_results or []
    )

    if internal_context == "없음":
        recent_user_evidence = _build_recent_user_evidence(req)

        if recent_user_evidence == "없음":
            return user_prompt

        return "\n".join([
            "[최근 대화에서 사용자가 직접 말한 내용]",
            recent_user_evidence,
            "",
            "[현재 사용자 요청]",
            user_prompt,
            "",
            "[대화 문맥 규칙]",
            "- 위 내용은 assistant의 추측이 아니라 사용자가 직접 말한 내용이다.",
            "- 현재 질문이 이전에 사용자가 말한 사실을 묻는 경우 위 내용을 우선 근거로 답한다.",
            "- 사용자가 직접 지정한 이름, 프로젝트명, 명칭, 값은 임의의 일반적인 예시로 바꾸지 않는다.",
            "- 위 내용에 답이 있으면 새 값을 추측하거나 만들어내지 않는다.",
        ])

    titles = _document_titles(req)
    title_text = ", ".join(f'"{title}"' for title in titles) or "현재 내부 문서"

    parts = [
        "[현재 문서 제목]",
        title_text,
        "",
    ]

    source_rules = [
        "- 과거 대화의 다른 파일명이나 다른 문서 내용을 현재 문서와 섞지 않는다.",
        "- 본문에 없는 소유관계·제작주체·회사관계·인과관계를 추론하지 않는다.",
        "- 문서의 고유명사, 사람/역할, 기술명, 기능, 수치처럼 출처에 있는 구체적 표현을 가능한 한 보존한다.",
    ]

    if web_context != "없음":
        source_rules.extend([
            "- 현재 문서는 내부/사내 사실의 최우선 근거로 사용한다.",
            "- 웹 검색 결과는 현재·외부 사실을 확인하거나 내부 문서와 비교하는 근거로만 사용한다.",
            "- 내부 문서의 내용을 웹 검색 결과로 덮어쓰지 않는다.",
            "- 현재 문서의 내용과 외부 사실을 구분해서 비교한다.",
            "- 두 근거가 다르면 내부 문서의 내용과 외부 근거의 내용을 각각 구분해 설명한다.",
        ])
    else:
        source_rules.insert(
            0,
            "- 현재 문서만 답변 근거로 사용한다.",
        )

    parts.extend([
        "[현재 문서 본문]",
        internal_context,
        "",
    ])

    if web_context != "없음":
        parts.extend([
            "[외부 웹 근거 - 현재/공식 사실 비교용]",
            web_context,
            "",
        ])

    parts.extend([
        "[현재 사용자 요청]",
        user_prompt,
        "",
        "[반드시 지킬 것]",
        *source_rules,
    ])

    if overview:
        parts.extend([
            "- 이 요청은 문서 개요 요청이다. 문서의 한 부분만 요약하지 말고 여러 섹션을 고르게 반영한다.",
            "- 1~2문장 개요 뒤에 4~6개의 주요 내용을 제시한다.",
            "- 주요 내용의 각 항목에는 본문에 실제 등장하는 구체적 사실이나 용어를 최소 1개 포함한다.",
            "- '프롬프트 관련 문서입니다'처럼 범주만 말하고 끝내지 않는다.",
            "- 현재 문서의 정확한 제목은 서버가 답변 앞에 별도로 붙이므로, 제목을 추측하거나 다른 소유관계로 바꾸지 않는다.",
        ])

    parts.extend([
        "",
        "위 자료를 읽고 현재 요청에 바로 답한다.",
    ])

    return "\n".join(parts)


def _build_document_system_prompt(req: GenerateRequest) -> str:
    """Short, specialised system prompt for document-grounded turns.

    The 1.5B model follows a focused contract more reliably than the full generic
    conversation policy when a concrete document has already been resolved.
    """
    preference_context = _build_preference_context(req.preference)

    parts = [
        "너는 PrompTune의 문서 분석 어시스턴트다.",
        "현재 문서는 Retrieval 단계에서 이미 확정되었다. 문서 선택을 다시 추측하지 않는다.",
        "제공된 현재 문서의 실제 본문에 근거해 정확하고 구체적으로 답한다.",
        "본문에 없는 사실이나 관계를 추가하지 않는다.",
        "사용자의 '이거', '그 문서', '그 파일', '거기서'는 현재 문서를 가리킨다.",
        "이전 대화가 현재 문서와 충돌하면 현재 문서를 따른다.",
        "사용자가 명시한 출력 형식, 분량, 제외 조건을 지켜 답한다.",
        "단, 문서 근거성과 이 시스템 프롬프트의 더 구체적인 규칙이 충돌하면 더 구체적인 규칙을 우선한다.",
    ]

    if preference_context != "없음":
        parts.extend([
            "",
            "[응답 스타일 선호도]",
            preference_context,
        ])

    return "\n".join(parts)


def _format_document_result(req: GenerateRequest, result: str) -> str:
    """Guarantee deterministic document identity for overview answers."""
    result = (result or "").strip()
    if not result or not req.documents or not _is_document_overview_request(req.prompt):
        return result

    titles = _document_titles(req)
    if len(titles) != 1:
        return result

    title = titles[0]
    # The title is system-known metadata.  Prefixing it prevents the language model
    # from inventing a different file identity or ownership relationship.
    return f'현재 문서: "{title}"\n\n{result}'


def _build_prompt(
    req: GenerateRequest,
    web_results: list[dict],
) -> str:
    internal_context = _build_internal_context(req)
    web_context = _build_web_context(web_results)
    user_context = _build_user_context(req.user_context)
    preference_context = _build_preference_context(req.preference)
    user_prompt = _build_effective_user_prompt(req)

    parts = [
        "너는 업무용 AI 어시스턴트다.",
        "사용자의 요청과 실제로 제공된 참고자료를 바탕으로 직접 답변해.",
        "",
        "규칙:",
        "1. 참고자료에 없는 사실을 임의로 만들어내지 마.",
        "2. 내부 문서가 제공되면 내부 문서의 관련 내용을 최우선 근거로 사용해.",
        "3. 내부 문서가 제공된 경우 '문서를 확인할 수 없다'거나 '자료가 없다'고 답하지 마.",
        "4. 사용자가 내부 문서의 핵심 내용이나 요약을 요청하면 내부 문서의 실제 내용을 구체적으로 요약해.",
        "5. 웹 검색 결과는 실제로 제공된 경우에만 활용해.",
        "6. 웹 검색 결과가 제공되지 않은 경우 그 사실을 답변에서 언급하지 마.",
        "7. 사용자 프로필은 실제로 제공된 경우에만 활용해.",
        "8. 최종 답변만 출력하고 분석 과정은 출력하지 마.",
        "9. 사용자 선호도가 제공된 경우, 그 스타일(속도/설명 분량/원문 존중도)에 맞춰 답변을 조정해.",
        "10. 사용자가 요청하지 않은 링크, URL, 유튜브/영상 링크, 첨부파일, 참고자료 항목을 임의로 추가하지 마.",
        "11. '[링크 삽입]', '[URL]', '[첨부파일]' 같은 placeholder를 임의로 생성하지 마.",
        "12. 수신자 존댓말 수위가 제공된 경우, 답변의 높임말 수준을 그 기준에 맞춰 조정해.",
        "",
        f"[업무 유형]\n{req.task_type}",
        "",
        f"[사용자 요청]\n{user_prompt}",
    ]

    if internal_context != "없음":
        parts.extend([
            "",
            "[내부 문서 - 아래 내용을 반드시 답변 근거로 활용]",
            internal_context,
        ])

    if web_context != "없음":
        parts.extend([
            "",
            "[웹 검색 결과]",
            web_context,
        ])

    if user_context != "없음":
        parts.extend([
            "",
            "[사용자 프로필]",
            user_context,
        ])

    if preference_context != "없음":
        parts.extend([
            "",
            "[사용자 선호도]",
            preference_context,
        ])

    parts.extend([
        "",
        "[최종 답변]",
    ])

    return "\n".join(parts)


def _build_system_prompt(
    req: GenerateRequest,
    web_results: list[dict],
    now: datetime | None = None,
) -> str:
    # 2026-08-26: "이강인 프로필" 질의 답변에 "2024년 2월 기준"처럼 실제 오늘
    # 날짜(2026년)와 무관한 임의의 연도가 등장하는 사례가 확인됨. 시스템
    # 프롬프트 어디에도 오늘 날짜를 알려주는 부분이 없어서, 모델이 사전 지식에
    # 남아있는 훈련 데이터 시점의 날짜를 "기준 시점"으로 잘못 골라 쓴 것으로
    # 보임. date_resolver.py의 KST/now 패턴을 그대로 재사용해 실제 날짜를
    # 프롬프트에 명시하고, 테스트에서 결정론적으로 검증할 수 있도록 now를
    # 주입 가능한 파라미터로 둔다(date_resolver.resolve_relative_dates와 동일 패턴).
    if now is None:
        now = datetime.now(KST)

    today_str = f"{now.year}년 {now.month}월 {now.day}일"

    web_context = _build_web_context(web_results)
    user_context = _build_user_context(req.user_context)
    preference_context = _build_preference_context(req.preference)

    parts = [
        "너는 PrompTune의 대화형 업무 AI 어시스턴트다.",
        "현재 사용자의 의도를 가장 우선해서 수행한다.",
        "",
        f"오늘 날짜는 {today_str}이다. '오늘'/'최근'/'현재'/'지금'처럼 시점을 나타내는 "
        "표현은 이 날짜를 기준으로 판단하라. 사전 지식에 남아있는 다른 연도나 날짜를 "
        "임의로 '기준 시점'이라고 답하지 마라.",
        "",
        "대화 규칙:",
        "1. 사용자가 직접 제공한 사실은 이 대화의 사실로 받아들여라.",
        "2. 사용자가 '코드명은 X', '담당자는 Y'처럼 새로 정의한 이름은 외부의 동명 대상과 연결하지 마라.",
        "3. 사용자가 '기억해줘'라고 하면 새로운 정보를 검색하거나 추측하지 말고, 제공한 사실을 간단히 확인하라.",
        "4. 사용자가 이전 답변을 수정하거나 반박하면 최신 사용자 메시지를 이전 assistant 답변보다 우선하라.",
        "5. 이전 assistant 답변에는 오류가 있을 수 있으므로 사용자가 제공한 사실과 충돌하면 사용자의 말을 따른다.",
        "6. 내부 문서가 실제 제공된 경우에만 내부 문서 내용을 근거로 사용한다.",
        "7. 웹 검색 결과가 실제 제공된 경우에만 웹 검색 결과를 사용한다.",
        "8. 웹 검색 결과가 없으면 검색했다고 주장하지 마라.",
        "9. 사용자가 요청하지 않은 배경설명, 링크, 외부 프로젝트, 회사, 인물 정보를 임의로 추가하지 마라.",
        "10. 사용자의 질문에 필요한 범위만 답하고 관련 없는 내용을 확장하지 마라.",
        "11. 현재 요청에 내부 문서가 제공되면 그 문서가 현재 활성 문서다. 이전 대화에 다른 파일명이 있어도 현재 문서를 우선하라.",
        "12. 사용자가 문서의 내용/요약을 물었으면 제목·문서유형·설명만 반복하는 답변은 금지한다. 반드시 [본문]의 실제 사실, 항목, 섹션을 구체적으로 요약하라.",
        "13. 내부 문서 본문이 제공된 경우 '어떤 파일인지 알려달라', '파일을 다시 업로드해달라'고 묻지 마라.",
        "14. 웹 검색 결과가 실제로 질문 대상(사람/팀/제품 등)에 대한 내용인지 확인하라. 검색 결과 제목·내용에 질문 대상이 나오지 않으면 그 결과는 무관한 것으로 보고 사용하지 마라.",
        "15. 소속팀/직책/현재 상태처럼 시간이 지나면 바뀌는 사실은 너의 사전 지식보다 실제로 제공된 웹 검색 결과/내부 문서를 우선하라. 사전 지식과 참고자료가 다르면 참고자료를 따르고, 참고자료에 그 사실이 없으면 확인할 수 없다고 답하라.",
        "16. 참고자료에 구체적인 사실이 없으면, 사실이 없다는 것을 솔직히 답하라. '관심이 높아지고 있다', '중요한 시기를 맞이했다', '기대를 모으고 있다'처럼 실제 정보 없이 분량만 채우는 문장을 쓰지 마라.",
        "17. 사용자가 인물의 프로필/소속/약력을 요청하면, 문단형 설명 대신 다음 구조로 정리해서 답하라: '개요'(누구인지 1~2문장 요약) -> '기본 프로필'(이름/생년월일/출신지/신체정보/포지션 또는 직업/소속 등 항목별 나열) -> '경력'(과거~현재 소속/활동 이력을 시간순으로) -> '주요 특징'(참고자료에 실제로 있는 대표 기록·수상 등, 있는 경우만). 각 섹션은 참고자료에서 실제로 확인된 항목만 채우고, 확인되는 내용이 전혀 없는 섹션은 통째로 생략하라. 사용자가 '3문단으로'처럼 문단 수를 함께 요청했더라도, 프로필 요청에는 이 구조를 우선하라 - 문단 수 지시문은 '개요' 같은 설명 문단에만 적용한다.",
        "18. 프로필 항목을 정리할 때는 참고자료에 있는 사실을 최대한 빠짐없이 반영하라 - 이름/소속만 짧게 쓰고 끝내지 말고, 참고자료에 나온 생년월일/출신지/신체정보/등번호/이전 소속 이력/최근 활동 등 확인 가능한 모든 항목을 포함하라. 참고자료에 없는 항목만 생략하고, 있는 항목을 임의로 생략해 답을 짧게 만들지 마라.",
        "19. 참고자료에 없는 항목은 아예 언급하지 마라 - 빈칸을 채우려고 추측하지 마라.",
        "20. 프로필처럼 여러 참고자료를 종합해 답할 때는, 문장이나 항목 끝에 그 사실이 어느 출처에서 나왔는지 '[숫자](출처 URL)' 형식으로 표시하라. 여러 출처가 같은 사실을 뒷받침하면 쉼표로 여러 개를 나열해도 된다. [웹 검색 결과]에 실제로 있는 URL만 쓰고, 없는 URL을 지어내지 마라.",
        f"21. '최근', '최신', '요즘' 소식을 요청받으면 위에서 알려준 오늘 날짜({today_str}) 기준으로 판단하라. [웹 검색 결과]가 실제로 오늘 날짜에 가까운 내용인지 확인할 수 없다면 임의의 과거 시점을 '기준'이라고 못 박지 말고, 참고자료에 날짜가 명시된 경우에만 그 날짜를 인용하라.",
        "22. 현재 질문이 이전 사용자 발화를 확인하거나 회상하는 질문이면, 사용자가 직접 말한 명칭과 값을 그대로 우선 사용하라. 일반적인 예시명이나 너의 추측으로 대체하지 마라.",
        "23. 현재 요청이 독립적인 새 주제라면 이전 대화의 사람·회사·프로젝트·문서·사실을 답변에 끌어오지 마라. 과거 대화는 현재 요청이 명시적으로 참조할 때만 사용한다.",
        "24. 사용자가 표, 목록, 문단, JSON 등 출력 형식을 명시하면 그 형식을 따라라. 단, 이 시스템 프롬프트에 더 구체적인 형식 규칙이 있는 경우 그 규칙을 우선한다.",
        "25. 사용자가 글자 수, 문장 수, 줄 수, 항목 수 등 분량을 명시하면 가능한 한 정확히 지켜라. 단, 더 구체적인 시스템 규칙과 충돌하면 시스템 규칙을 우선한다.",
        "26. 사용자가 '반드시', '제외', '포함하지 마', '하지 마' 등 명시적인 제약 조건을 주면 답변에서 반드시 준수하라.",
    ]

    if web_context != "없음":
        parts.extend([
            "",
            "[웹 검색 결과]",
            web_context,
        ])

    if user_context != "없음":
        parts.extend([
            "",
            "[사용자 프로필]",
            user_context,
        ])

    if preference_context != "없음":
        parts.extend([
            "",
            "[응답 스타일 선호도]",
            preference_context,
        ])

    return "\n".join(parts)

def generate(
    req: GenerateRequest,
    web_results=None,
    used_web_search: bool = False,
) -> GenerateResponse:
    web_results = web_results or []

    tokenizer, model, device = load_hcx_runtime()

    system_prompt = (
        _build_document_system_prompt(req)
        if req.documents
        else _build_system_prompt(
            req=req,
            web_results=web_results,
        )
    )

    user_prompt = _build_generation_user_prompt(
        req,
        web_results=web_results,
    )
    selected_history = _select_generation_history(req)

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    messages.extend(
        {
            "role": message.role,
            "content": message.content.strip(),
        }
        for message in selected_history
    )

    messages.append(
        {
            "role": "user",
            "content": user_prompt,
        }
    )

    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    )

    inputs = inputs.to(device)

    logger.info(
        "HCX prompt mode=%s documents=%d history_in=%d history_used=%d input_tokens=%d",
        "document_grounded" if req.documents else "conversation",
        len(req.documents),
        len(req.history),
        len(selected_history),
        inputs["input_ids"].shape[1],
    )

    with hcx_lock(timeout=120):
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                # 2026-08-25: 768→512로 낮춰봤지만 체감 대기시간이 260초→240초로
                # 거의 안 줄었음(약 8%) — 실측해보니 생성 시간의 대부분이 토큰 수가
                # 아니라 동시 요청들이 HCX_MODEL_LOCK을 순서대로 기다리는 큐잉
                # 시간(다른 요청의 생성이 끝날 때까지 대기)에서 나오는 것으로 확인됨.
                # 토큰 상한을 줄여도 체감 속도는 거의 개선되지 않으면서 답변만 짧아지는
                # 손해였으므로, 답변 완성도를 우선해 750으로 원복.
                # (락 자체는 hcx_lock(timeout=120)이 이미 처리 — 대기가 길어지면
                # 조용히 멈추는 대신 명확한 503을 반환함.)
                max_new_tokens=750,
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

    result = _format_document_result(req, result)

    logger.info(
        "HCX final generation task_type=%s web=%s documents=%d",
        req.task_type,
        used_web_search,
        len(req.documents),
    )

    return GenerateResponse(
        result=result,
        used_web_search=used_web_search,
    )
