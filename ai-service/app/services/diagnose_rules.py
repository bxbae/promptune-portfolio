"""
5번 통합 진단에서 모델과 별도로 사용하는 규칙 로직.

KcELECTRA:
- 8요소 누락 여부만 담당

Rule:
- 업무 유형(task_type)
- 고신뢰 오탈자 보정
- 내부문서 필요 여부
"""
import re

from app.schemas.models import Typo
from app.services.typo_models import DetectedTypo, TypoRule


TASK_TYPE_HINTS = {
    "application": ["신청", "휴가", "경비", "구매"],
    "report_internal": ["내규", "규정", "정책 보고"],
    "notice_internal": ["정책 공지", "내부 공지"],
    "report": [
    "보고서",
    "주간보고",
    "실적",
    "피치",
    "회의록",
    "회의 내용 정리",
    "회의 내용을 정리",
    "회의 정리",
    "회의 요약",
    "회의 내용을 요약",
],
    "notice": [
        "공지",
        "안내문",
        "이벤트",
        "채팅방에",
        "메신저로",
        "슬랙에",
        "팀즈에",
        "Teams에",
],
    "support": ["사과", "고객", "응대", "불만"],
    "email": ["메일", "이메일"],
}

def should_force_missing_audience(text: str, task_type: str) -> bool:
    """
    명시적인 메일 작성 요청인데 수신 대상이 없는 경우
    AUDIENCE 누락을 고신뢰 규칙으로 보정한다.

    KcELECTRA의 일반 8요소 판단을 대체하지 않고,
    명백한 메일 수신자 누락 케이스에만 적용한다.
    """

    if task_type != "email":
        return False

    if not any(hint in text for hint in ("메일", "이메일")):
        return False

    recipient_patterns = (
        r"\S+\s*(?:에게|께|한테)",
        r"\S+\s*(?:을|를)\s*대상으로",
        r"수신자\s*(?:는|는\s*:|:)",
    )

    return not any(
        re.search(pattern, text)
        for pattern in recipient_patterns
    )

TYPO_RULES = (
    # ------------------------------------------------------------
    # 빠른 입력 / 키보드형 오타
    # ------------------------------------------------------------
    TypoRule(
        wrong="요약해조",
        correct="요약해줘",
        category="keyboard_typo",
        priority=100,
    ),
    TypoRule(
        wrong="정리헤줘",
        correct="정리해줘",
        category="keyboard_typo",
        priority=100,
    ),
    TypoRule(
        wrong="작성헤줘",
        correct="작성해줘",
        category="keyboard_typo",
        priority=100,
    ),
    TypoRule(
        wrong="검토헤줘",
        correct="검토해줘",
        category="keyboard_typo",
        priority=100,
    ),
    TypoRule(
        wrong="보내주새요",
        correct="보내 주세요",
        category="keyboard_typo",
        priority=100,
    ),

    # ------------------------------------------------------------
    # 조사 / 어미 오타
    # ------------------------------------------------------------
    TypoRule(
        wrong="부탁드림니다",
        correct="부탁드립니다",
        category="ending_typo",
        priority=110,
    ),
    TypoRule(
        wrong="드림니다",
        correct="드립니다",
        category="ending_typo",
        priority=100,
    ),
    TypoRule(
        wrong="해줄레",
        correct="해줄래",
        category="ending_typo",
        priority=95,
    ),
    TypoRule(
        wrong="한태",
        correct="한테",
        category="particle_typo",
        priority=95,
    ),

    # ------------------------------------------------------------
    # 자주 발생하는 맞춤법 오류
    # Bareun도 잡을 수 있지만, 교정이 명확한 표현만 보조 Rule로 유지
    # ------------------------------------------------------------
    TypoRule(
        wrong="됬습니다",
        correct="됐습니다",
        category="spelling",
        priority=90,
    ),
    TypoRule(
        wrong="됬어요",
        correct="됐어요",
        category="spelling",
        priority=90,
    ),
    TypoRule(
        wrong="되요",
        correct="돼요",
        category="spelling",
        priority=90,
    ),
    TypoRule(
        wrong="몇일",
        correct="며칠",
        category="spelling",
        priority=90,
    ),
)


def detect_task_type(text: str) -> str:
    for task_type, hints in TASK_TYPE_HINTS.items():
        if any(hint in text for hint in hints):
            return task_type

    return "email"


def _ranges_overlap(
    start_a: int,
    end_a: int,
    start_b: int,
    end_b: int,
) -> bool:
    """
    두 문자열 범위가 실제로 겹치는지 확인한다.

    범위는 Python slice 방식인 [start, end)를 사용한다.
    """
    return start_a < end_b and start_b < end_a


def detect_typos_detailed(text: str) -> list[DetectedTypo]:
    """
    Rule Engine의 상세 탐지 결과를 반환한다.

    특징:
    - priority가 높은 Rule 우선
    - 같은 priority에서는 긴 표현 우선
    - 실제 start/end 위치 보존
    - 중첩된 Rule 중복 탐지 방지
    - 동일 오타가 문장에 여러 번 등장하면 각각 위치를 보존
    """

    found: list[DetectedTypo] = []

    sorted_rules = sorted(
        TYPO_RULES,
        key=lambda rule: (
            -rule.priority,
            -len(rule.wrong),
        ),
    )

    for rule in sorted_rules:
        search_from = 0

        while True:
            start = text.find(
                rule.wrong,
                search_from,
            )

            if start == -1:
                break

            end = start + len(rule.wrong)

            overlaps_existing = any(
                _ranges_overlap(
                    start,
                    end,
                    detected.start,
                    detected.end,
                )
                for detected in found
            )

            if not overlaps_existing:
                found.append(
                    DetectedTypo(
                        span=rule.wrong,
                        suggest=rule.correct,
                        start=start,
                        end=end,
                        source="rule",
                        category=rule.category,
                        priority=rule.priority,
                    )
                )

            search_from = start + 1

    found.sort(
        key=lambda detected: (
            detected.start,
            -detected.priority,
            -(detected.end - detected.start),
        )
    )

    return found


def detect_typos(text: str) -> list[Typo]:
    """
    기존 DiagnoseResponse와의 호환성을 위한 API용 함수.

    내부에서는 DetectedTypo를 사용하지만,
    외부에는 기존 Typo(span, suggest) 형식을 그대로 반환한다.
    """

    results: list[Typo] = []
    seen: set[tuple[str, str]] = set()

    for detected in detect_typos_detailed(text):
        key = (
            detected.span,
            detected.suggest,
        )

        if key in seen:
            continue

        seen.add(key)

        results.append(
            Typo(
                span=detected.span,
                suggest=detected.suggest,
            )
        )

    return results


def needs_internal_docs(task_type: str) -> bool:
    return (
        task_type.endswith("_internal")
        or task_type == "application"
    )