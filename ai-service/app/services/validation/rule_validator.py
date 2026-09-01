from __future__ import annotations

import re
from dataclasses import dataclass, field


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

def extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


_MAX_LENGTH_RE = re.compile(
    r"(?P<count>\d+)\s*(?:자|글자)\s*(?:이내|이하)"
)

_ITEM_COUNT_RE = re.compile(
    r"(?P<count>\d+)"
    r"(?:\s*~\s*(?P<max_count>\d+))?"
    r"\s*(?:"
    r"개(?:의)?\s*(?:항목|내용|포인트)"
    r"|개\s*(?:로|으로)\s*(?:정리|작성|제시|요약)"
    r"|가지(?:의)?\s*(?:항목|내용|포인트)"
    r"|가지\s*(?:로|으로)\s*(?:정리|작성|제시|요약)"
    r")"
)

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)]\s+)",
    re.MULTILINE,
)

# 2026-08-26: PrompTune 8요소(FORMAT/LENGTH) 다듬기 지시문에 붙는 숫자
# ("3문단으로", "3~4줄로", "5문장 이내로" 등)가 "반드시 결과에 그대로
# 남아있어야 하는 사실"로 오인되어, 모델이 정확히 그 형식으로 답해도
# 본문에 그 숫자 토큰 자체가 없으면(당연히 없어도 됨) facts_preserved가
# False로 판정되는 사례가 확인됨 — "2026년 8월 26일 기준으로 이강인 선수의
# 프로필을 안내해줘...3문단으로..." 질의에서 generate→validate가 재시도까지
# 두 번 다 이 오탐으로 실패해 "검증을 통과하는 답변을 생성하지 못했습니다"
# 503으로 노출된 사례로 재현 확인됨.
#
# 같은 문제가 2026-08-25에 pipeline_mock.validate()에서도 한 번 확인되어
# 거기엔 이미 제외 처리(_FORMAT_INSTRUCTION_NUM_RE)가 있었지만, 실제
# USE_REAL_VALIDATION=true일 때 쓰이는 이 모듈(rule_validator)에는 그 수정이
# 반영되지 않아 회귀가 재발했음 — 여기서도 같은 취지로 제외 처리를 추가한다.
#
# "개"/"가지"는 건드리지 않는다 — 이미 _ITEM_COUNT_RE가 "N개 항목"류만 정확히
# 서식 지시로 구분하고 있고, "사과 3개"처럼 실제 수량 사실인 경우와 구분해야
# 하기 때문(아래 test_product_quantity_is_treated_as_fact_number 참고).
# "자/글자"도 이미 _MAX_LENGTH_RE가 처리한다.
_FORMAT_DIRECTIVE_NUMBER_RE = re.compile(
    r"\d+(?:~\d+)?\s*(?:문단|문장|줄|번째|단어|페이지|포인트|배|위|점)"
    r"\s*(?:이내로|이내|이상|이하|으로|로)?"
)

_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


@dataclass
class RuleValidationResult:
    length_ok: bool = True
    item_count_ok: bool = True
    format_ok: bool = True
    facts_preserved: bool = True
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.length_ok
            and self.item_count_ok
            and self.format_ok
            and self.facts_preserved
        )


def _validate_length(
    original: str,
    generated: str,
    issues: list[str],
) -> bool:
    match = _MAX_LENGTH_RE.search(original)

    if match is None:
        return True

    max_length = int(match.group("count"))
    actual_length = len(generated)

    if actual_length <= max_length:
        return True

    issues.append(
        f"길이 조건 위반: 최대 {max_length}자, 실제 {actual_length}자"
    )
    return False


def _validate_item_count(
    original: str,
    generated: str,
    issues: list[str],
) -> bool:
    match = _ITEM_COUNT_RE.search(original)

    if match is None:
        return True

    min_count = int(match.group("count"))
    max_count_text = match.group("max_count")
    max_count = (
        int(max_count_text)
        if max_count_text is not None
        else min_count
    )

    if max_count < min_count:
        min_count, max_count = max_count, min_count

    actual_count = len(_LIST_ITEM_RE.findall(generated))

    if min_count <= actual_count <= max_count:
        return True

    requested = (
        f"{min_count}개"
        if min_count == max_count
        else f"{min_count}~{max_count}개"
    )
    issues.append(
        f"항목 개수 조건 위반: 요청 {requested}, 실제 {actual_count}개"
    )
    return False


def _table_requested(original: str) -> bool:
    return (
        "표 형식" in original
        or "표형식" in original
        or "표로" in original
    )


def _has_markdown_table(generated: str) -> bool:
    lines = [
        line.strip()
        for line in generated.splitlines()
        if line.strip()
    ]

    if len(lines) < 2:
        return False

    for index in range(1, len(lines)):
        if not _MARKDOWN_TABLE_SEPARATOR_RE.match(lines[index]):
            continue

        previous_line = lines[index - 1]

        if "|" in previous_line:
            return True

    return False


def _validate_format(
    original: str,
    generated: str,
    issues: list[str],
) -> bool:
    if not _table_requested(original):
        return True

    if _has_markdown_table(generated):
        return True

    issues.append("형식 조건 위반: 표 형식이 요청되었지만 표가 없습니다.")
    return False


def _constraint_number_spans(original: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []

    for pattern in (_MAX_LENGTH_RE, _ITEM_COUNT_RE):
        for match in pattern.finditer(original):
            number_start = match.start("count")
            number_end = match.end("count")
            spans.append((number_start, number_end))

            # "2~3가지로 정리"처럼 범위형 항목 수 조건에서는
            # 상한 숫자도 사실 숫자가 아니라 출력 제약 숫자다.
            if "max_count" in match.groupdict():
                max_count = match.group("max_count")
                if max_count is not None:
                    spans.append(
                        (
                            match.start("max_count"),
                            match.end("max_count"),
                        )
                    )

    # 전체 매치 구간을 그대로 쓴다 (named group이 없고, "3~4줄"처럼 숫자가
    # 둘 이상 붙는 범위 표현도 통째로 제외해야 하므로).
    for match in _FORMAT_DIRECTIVE_NUMBER_RE.finditer(original):
        spans.append(match.span())

    return spans


def _fact_numbers(original: str) -> set[str]:
    constraint_spans = _constraint_number_spans(original)
    facts: set[str] = set()

    for match in _NUMBER_RE.finditer(original):
        start, end = match.span()

        is_constraint_number = any(
            start >= span_start and end <= span_end
            for span_start, span_end in constraint_spans
        )

        if not is_constraint_number:
            facts.add(match.group())

    return facts


def _validate_fact_numbers(
    original: str,
    generated: str,
    issues: list[str],
) -> bool:
    original_numbers = _fact_numbers(original)

    if not original_numbers:
        return True

    generated_numbers = set(_NUMBER_RE.findall(generated))
    missing_numbers = original_numbers - generated_numbers

    if not missing_numbers:
        return True

    issues.append(
        "원문 숫자 누락: " + ", ".join(sorted(missing_numbers))
    )
    return False


def validate_rules(
    original: str,
    generated: str,
) -> RuleValidationResult:
    issues: list[str] = []

    length_ok = _validate_length(original, generated, issues)
    item_count_ok = _validate_item_count(original, generated, issues)
    format_ok = _validate_format(original, generated, issues)
    facts_preserved = _validate_fact_numbers(
        original,
        generated,
        issues,
    )

    return RuleValidationResult(
        length_ok=length_ok,
        item_count_ok=item_count_ok,
        format_ok=format_ok,
        facts_preserved=facts_preserved,
        issues=issues,
    )