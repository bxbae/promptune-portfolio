from __future__ import annotations

import re
import unicodedata
from typing import Literal

from app.schemas.models import ConversationMessage


ConversationContextMode = Literal[
    "standalone",
    "immediate_followup",
    "memory_recall",
]


_MEMORY_SET_MARKERS = (
    "기억해줘",
    "기억해 줘",
    "기억해둬",
    "기억해 둬",
    "기억해 두자",
)

_RECALL_MARKERS = (
    "뭐라고",
    "뭐였",
    "누구였",
    "어디였",
    "기억나",
    "전에 말한",
    "이전에 말한",
    "말했던",
    "내가 말한",
    "우리가 말한",
    "라고 했",
    "라고 말했",
    "정했지",
)

_IMMEDIATE_FOLLOWUP_MARKERS = (
    "그거",
    "그걸",
    "그것",
    "그 사람",
    "그 회사",
    "그 프로젝트",
    "그 답변",
    "그 부분",
    "그 항목",
    "방금",
    "아까",
    "앞에서",
    "앞서",
    "이어서",
    "계속",
    "더 자세",
    "좀 더",
    "다시 설명",
    "다시 해",
    "수정해",
    "바꿔줘",
    "그대로",
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

_REQUEST_MARKERS = (
    "알려줘",
    "알려주세요",
    "찾아줘",
    "찾아봐",
    "검색해",
    "작성해",
    "만들어",
    "요약해",
    "설명해",
    "보여줘",
    "해줘",
    "해주세요",
    "누구야",
    "뭐야",
    "어때",
    "할까",
)

_STOPWORDS = {
    "뭐라고",
    "뭐였지",
    "뭐였",
    "누구였지",
    "누구였",
    "어디였지",
    "어디였",
    "내가",
    "우리가",
    "말했지",
    "했지",
    "기억나",
    "알려줘",
    "알려주세요",
    "그거",
    "그걸",
    "그것",
    "방금",
    "아까",
    "다시",
    "현재",
    "지금",
}

_PARTICLE_SUFFIXES = (
    "으로부터",
    "에서부터",
    "이라고",
    "라고",
    "에서",
    "에게",
    "한테",
    "으로",
    "부터",
    "까지",
    "이나",
    "는",
    "은",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "로",
    "도",
    "만",
)


def _normalize(text: str) -> str:
    return unicodedata.normalize(
        "NFKC",
        str(text or ""),
    ).strip().lower()


def is_memory_set_request(prompt: str) -> bool:
    text = _normalize(prompt)
    return any(
        marker in text
        for marker in _MEMORY_SET_MARKERS
    )


def _history_supports_recall(
    prompt: str,
    history: list[ConversationMessage] | None,
) -> bool:
    if not history:
        return False

    query_keywords = _extract_keywords(prompt)

    if not query_keywords:
        return False

    for message in reversed(history[-12:]):
        if message.role != "user":
            continue

        content = message.content.strip()

        if not content:
            continue

        history_keywords = _extract_keywords(content)
        overlap = query_keywords & history_keywords

        if not overlap:
            continue

        # 짧고 흔한 단어 하나가 우연히 겹친 경우는 memory 근거로 삼지 않는다.
        strong_overlap = {
            token
            for token in overlap
            if len(token) >= 4
        }

        if strong_overlap or len(overlap) >= 2:
            return True

    return False


def classify_conversation_context(
    prompt: str,
    history: list[ConversationMessage] | None = None,
) -> ConversationContextMode:
    text = _normalize(prompt)

    if not text:
        return "standalone"

    # 새 사실 저장 요청.
    if is_memory_set_request(text):
        return "standalone"

    # "그 사람", "그거", "방금", "좀 더"처럼
    # 직전 문맥을 가리키는 표현이 가장 우선한다.
    if any(
        marker in text
        for marker in _IMMEDIATE_FOLLOWUP_MARKERS
    ):
        return "immediate_followup"

    explicit_memory_markers = (
        "전에 말한",
        "이전에 말한",
        "내가 말한",
        "우리가 말한",
        "말했던",
        "전에 정한",
        "내가 정한",
        "우리가 정한",
        "기억나",
        "기억하지",
    )

    # 사용자가 명시적으로 이전 대화를 가리킨다.
    if any(
        marker in text
        for marker in explicit_memory_markers
    ):
        return "memory_recall"

    words = text.split()
    first_word = words[0] if words else ""

    first_person = first_word in {
        "내",
        "내가",
        "나",
        "우리",
        "우리가",
        "제",
        "제가",
        "저",
    }

    recall_question = any(
        marker in text
        for marker in (
            "뭐라고",
            "뭐였지",
            "누구였지",
            "어디였지",
        )
    )

    # "내 프로젝트 명이 뭐라고?"처럼 개인 대화 회상처럼 보이는 질문도
    # 실제 history에 관련 근거가 있을 때만 memory로 취급한다.
    if (
        first_person
        and recall_question
        and _history_supports_recall(text, history)
    ):
        return "memory_recall"

    ambiguous_recall = any(
        marker in text
        for marker in (
            "뭐였지",
            "누구였지",
            "어디였지",
            "뭐라고 했지",
            "뭐라고 말했지",
        )
    )

    # "프로젝트명 뭐라고 했지?"처럼 주어가 생략된 경우도
    # history에 실제 같은 대상이 있을 때만 회상으로 인정한다.
    if (
        ambiguous_recall
        and _history_supports_recall(text, history)
    ):
        return "memory_recall"

    return "standalone"


def _extract_keywords(text: str) -> set[str]:
    normalized = _normalize(text)

    raw_tokens = re.findall(
        r"[0-9a-z가-힣_+\-]{2,}",
        normalized,
    )

    keywords: set[str] = set()

    for raw in raw_tokens:
        token = raw

        for suffix in _PARTICLE_SUFFIXES:
            if (
                token.endswith(suffix)
                and len(token) - len(suffix) >= 2
            ):
                token = token[:-len(suffix)]
                break

        if len(token) < 2 or token in _STOPWORDS:
            continue

        keywords.add(token)

        # "프로젝트명" ↔ "프로젝트"도 연결.
        if token.endswith("명") and len(token) >= 4:
            keywords.add(token[:-1])

    return keywords


def _looks_like_request(text: str) -> bool:
    normalized = _normalize(text)

    if is_memory_set_request(normalized):
        return False

    return any(
        marker in normalized
        for marker in _REQUEST_MARKERS
    )


def _memory_candidate_score(
    query_keywords: set[str],
    content: str,
) -> int:
    normalized = _normalize(content)

    score = 0

    if is_memory_set_request(normalized):
        score += 5

    for keyword in query_keywords:
        if keyword in normalized:
            score += 3

    if (
        _looks_like_request(normalized)
        and not is_memory_set_request(normalized)
    ):
        score -= 4

    return score


def build_recall_evidence(
    prompt: str,
    history: list[ConversationMessage],
) -> str:
    if (
        classify_conversation_context(prompt, history)
        != "memory_recall"
    ):
        return "없음"

    user_messages = [
        (index, message.content.strip())
        for index, message in enumerate(history)
        if (
            message.role == "user"
            and message.content.strip()
        )
    ]

    if not user_messages:
        return "없음"

    query_keywords = _extract_keywords(prompt)

    # "내가 방금 뭐라고 했지?"처럼 대상 keyword가 없는 경우에는
    # 가장 최근 사용자 발화를 그대로 사용한다.
    if not query_keywords:
        remembered = [
            item
            for item in user_messages
            if is_memory_set_request(item[1])
        ]

        selected = (
            remembered[-1]
            if remembered
            else user_messages[-1]
        )

        return f"- {selected[1]}"

    ranked: list[tuple[int, int, str]] = []

    for index, content in user_messages:
        score = _memory_candidate_score(
            query_keywords,
            content,
        )

        if score >= 2:
            ranked.append(
                (
                    score,
                    index,
                    content,
                )
            )

    if not ranked:
        return "없음"

    # relevance 우선, 같은 relevance면 최신 발화 우선.
    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    top_score = ranked[0][0]

    # 최고점과 크게 차이 나는 과거 발화는 버린다.
    selected = [
        item
        for item in ranked
        if item[0] >= max(2, top_score - 1)
    ][:3]

    # 최종 prompt에는 원래 대화 순서로 배치.
    selected.sort(key=lambda item: item[1])

    return "\n".join(
        f"- {content}"
        for _, _, content in selected
    )


def select_relevant_history(
    prompt: str,
    history: list[ConversationMessage],
) -> list[ConversationMessage]:
    mode = classify_conversation_context(prompt, history)

    if mode == "standalone":
        return []

    # memory recall은 assistant 과거 오답을 evidence로 쓰지 않는다.
    # 관련 user 사실은 build_recall_evidence()가 따로 선택한다.
    if mode == "memory_recall":
        return []

    # "그거 좀 더 자세히", "방금 답변 수정해줘" 같은 경우만
    # 직전 2개 대화쌍 정도를 유지한다.
    non_empty = [
        message
        for message in history
        if message.content.strip()
    ]

    return non_empty[-4:]
