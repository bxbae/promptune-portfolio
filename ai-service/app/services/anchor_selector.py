from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from app.services.validation.semantic_validator import calculate_similarities


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnchorSelection:
    """
    추천 문구를 삽입할 위치.

    sentence_index:
        0-based 문장 인덱스.
        문장이 없는 경우 -1.

    char_offset:
        원본 prompt 문자열 기준 삽입 위치.
        text[:char_offset] / text[char_offset:]에 그대로 사용할 수 있다.
    """

    sentence_index: int
    char_offset: int


ELEMENT_ANCHOR_DESCRIPTIONS: dict[str, str] = {
    "TASK": "AI가 무엇을 대상으로 어떤 작업을 수행해야 하는지 지정하는 조건",
    "AUDIENCE": "결과물을 누가 읽거나 검토하거나 받을지 지정하는 조건",
    "CONTEXT": "업무의 배경, 상황, 목적 또는 전제를 알려 주는 조건",
    "FORMAT": "결과물을 표, 목록, 문단, JSON 등 어떤 형태로 작성할지 지정하는 조건",
    "TONE": "결과물의 말투, 어조 또는 문체를 지정하는 조건",
    "LENGTH": "결과물의 분량, 길이 또는 개수를 지정하는 조건",
    "CONSTRAINT": "결과물이 반드시 지키거나 제외해야 하는 규칙과 제한 조건",
    "EXAMPLE": "원하는 결과의 형태나 내용을 참고할 수 있는 예시 또는 참고 조건",
}


_SENTENCE_PATTERN = re.compile(
    r"[^.!?。！？\n]+(?:[.!?。！？]+|(?=\n|$))"
)


def _sentence_spans(
    text: str,
) -> list[tuple[int, int, str]]:
    """
    원본 문자열에서 문장별 (start, end, sentence)를 반환한다.

    start/end는 반드시 원본 문자열 기준 offset이다.
    """

    spans: list[tuple[int, int, str]] = []

    for match in _SENTENCE_PATTERN.finditer(text):
        raw = match.group(0)

        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())

        start = match.start() + leading
        end = match.end() - trailing

        if start >= end:
            continue

        sentence = text[start:end]

        if sentence.strip():
            spans.append(
                (
                    start,
                    end,
                    sentence,
                )
            )

    return spans


def _fallback_last_sentence(
    spans: list[tuple[int, int, str]],
) -> AnchorSelection:
    if not spans:
        return AnchorSelection(
            sentence_index=-1,
            char_offset=0,
        )

    last_index = len(spans) - 1
    _, end, _ = spans[last_index]

    return AnchorSelection(
        sentence_index=last_index,
        char_offset=end,
    )


def select_anchor(
    text: str,
    element: str,
) -> AnchorSelection:
    """
    BGE-M3 의미 유사도를 이용해 missing element와
    가장 관련 있는 문장을 선택한다.

    BGE-M3는 '어느 문장인가'만 판단하고,
    실제 charOffset은 원본 문자열에서 deterministic하게 계산한다.

    BGE-M3 계산에 실패하면 서비스 전체를 실패시키지 않고
    마지막 문장 위치로 fail-safe 한다.
    """

    spans = _sentence_spans(text)

    if not spans:
        return AnchorSelection(
            sentence_index=-1,
            char_offset=len(text),
        )

    normalized_element = element.strip().upper()

    reference = ELEMENT_ANCHOR_DESCRIPTIONS.get(
        normalized_element
    )

    if reference is None:
        return _fallback_last_sentence(spans)

    sentences = [
        sentence
        for _, _, sentence in spans
    ]

    try:
        scores = calculate_similarities(
            reference=reference,
            candidates=sentences,
        )

    except Exception:
        logger.exception(
            "Anchor semantic scoring failed element=%s",
            normalized_element,
        )
        return _fallback_last_sentence(spans)

    if len(scores) != len(spans) or not scores:
        logger.warning(
            "Anchor semantic score count mismatch "
            "element=%s sentences=%s scores=%s",
            normalized_element,
            len(spans),
            len(scores),
        )
        return _fallback_last_sentence(spans)

    # 동일 점수라면 뒤쪽 문장을 선택한다.
    best_index = max(
        range(len(scores)),
        key=lambda index: (
            scores[index],
            index,
        ),
    )

    _, end, _ = spans[best_index]

    return AnchorSelection(
        sentence_index=best_index,
        char_offset=end,
    )