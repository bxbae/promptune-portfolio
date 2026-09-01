"""
바른(Bareun) 맞춤법 검사 API 연동.

역할:
- 사용자 프롬프트의 맞춤법/띄어쓰기/표준어/오탈자 등을 검사
- 바른 API의 revisedBlocks를 PrompTune의 Typo(span, suggest) 형식으로 변환

주의:
- API Key는 코드에 직접 작성하지 않는다.
- BAREUN_API_KEY 환경변수에서 읽는다.
"""

import json
import logging
import os
from urllib import error, request

from app.schemas.models import Typo
from app.services.diagnose_rules import detect_typos_detailed
from app.services.typo_models import DetectedTypo

logger = logging.getLogger(__name__)

DEFAULT_BAREUN_API_URL = "https://api.bareun.ai"
CORRECT_ERROR_PATH = "/bareun.RevisionService/CorrectError"

BAREUN_CATEGORY_PRIORITY = {
    "TYPO": 80,
    "GRAMMER": 70,
    "STANDARD": 65,
    "SPACING": 60,
}

DEFAULT_BAREUN_PRIORITY = 50

def _extract_detected_typos(
    response_data: dict,
) -> list[DetectedTypo]:
    """
    Bareun revisedBlocks를 내부 DetectedTypo 형식으로 변환한다.

    보존 정보:
    - span / suggest
    - beginOffset -> start
    - length -> end
    - category
    - source
    - 내부 priority

    정책:
    - 단순 구두점 교정은 제외한다.
    - helpId가 Merged이고 nested가 있으면
      부모 결과 대신 세부 nested 결과를 사용한다.
    """

    results: list[DetectedTypo] = []

    seen: set[
        tuple[int, int, str, str]
    ] = set()

    blocks = response_data.get(
        "revisedBlocks",
        response_data.get("revised_blocks", []),
    )

    def add_block(block: dict) -> None:
        revisions = block.get("revisions", [])
        nested = block.get("nested") or []

        is_merged = any(
            revision.get("helpId") == "Merged"
            for revision in revisions
        )

        if is_merged and nested:
            for child in nested:
                add_block(child)

            return

        # 단순 구두점 교정은 PrompTune 오탈자 표시에서 제외
        if revisions and all(
            revision.get("helpId") == "구두점"
            for revision in revisions
        ):
            return

        origin = block.get("origin") or {}

        span = str(
            origin.get("content", "")
        )

        suggest = str(
            block.get("revised", "")
        )

        if not span or not suggest:
            return

        if span == suggest:
            return

        try:
            start = int(
                origin.get("beginOffset", -1)
            )

            length = int(
                origin.get("length", 0)
            )

        except (TypeError, ValueError):
            return

        if start < 0 or length <= 0:
            return

        end = start + length

        categories = [
            str(revision.get("category", "UNKNOWN"))
            for revision in revisions
            if revision.get("category")
        ]

        if categories:
            category = max(
                categories,
                key=lambda value: (
                    BAREUN_CATEGORY_PRIORITY.get(
                        value,
                        DEFAULT_BAREUN_PRIORITY,
                    )
                ),
            )
        else:
            category = "UNKNOWN"

        priority = BAREUN_CATEGORY_PRIORITY.get(
            category,
            DEFAULT_BAREUN_PRIORITY,
        )

        key = (
            start,
            end,
            span,
            suggest,
        )

        if key in seen:
            return

        seen.add(key)

        results.append(
            DetectedTypo(
                span=span,
                suggest=suggest,
                start=start,
                end=end,
                source="bareun",
                category=category,
                priority=priority,
            )
        )

    for block in blocks:
        add_block(block)

    results.sort(
        key=lambda detected: (
            detected.start,
            -(detected.end - detected.start),
            -detected.priority,
        )
    )

    return results


def _extract_typos(
    response_data: dict,
) -> list[Typo]:
    """
    기존 check_spelling() 인터페이스 호환용 변환 함수.
    """

    results: list[Typo] = []
    seen: set[tuple[str, str]] = set()

    for detected in _extract_detected_typos(
        response_data
    ):
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


def _request_bareun(text: str) -> dict:
    """
    Bareun CorrectError API를 호출하고
    원본 JSON 응답을 반환한다.
    """

    api_key = os.getenv(
        "BAREUN_API_KEY",
        "",
    ).strip()

    base_url = os.getenv(
        "BAREUN_API_URL",
        DEFAULT_BAREUN_API_URL,
    ).strip()

    if not api_key:
        raise RuntimeError(
            "BAREUN_API_KEY 환경변수가 설정되어 있지 않습니다."
        )

    url = (
        base_url.rstrip("/")
        + CORRECT_ERROR_PATH
    )

    payload = {
        "document": {
            "content": text,
            "language": "ko-KR",
        },
        "encoding_type": "UTF32",
    }

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(
            req,
            timeout=5,
        ) as response:
            response_body = (
                response
                .read()
                .decode("utf-8")
            )

    except error.HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        logger.error(
            "Bareun API HTTP error: "
            "status=%s body=%s",
            exc.code,
            error_body[:500],
        )

        raise RuntimeError(
            f"Bareun API 호출 실패: HTTP {exc.code}"
        ) from exc

    except error.URLError as exc:
        logger.error(
            "Bareun API network error: %s",
            exc.reason,
        )

        raise RuntimeError(
            "Bareun API 네트워크 연결에 실패했습니다."
        ) from exc

    try:
        return json.loads(
            response_body
        )

    except json.JSONDecodeError as exc:
        logger.error(
            "Bareun API invalid JSON response: %s",
            response_body[:500],
        )

        raise RuntimeError(
            "Bareun API 응답을 JSON으로 해석할 수 없습니다."
        ) from exc


def check_spelling_detailed(
    text: str,
) -> list[DetectedTypo]:
    """
    Bareun 상세 검사 결과를 반환한다.

    Merge Engine 내부에서 사용하는 함수.
    """

    if not text.strip():
        return []

    response_data = _request_bareun(text)

    return _extract_detected_typos(
        response_data
    )


def check_spelling(
    text: str,
) -> list[Typo]:
    """
    기존 코드와의 호환성을 위한 맞춤법 검사 함수.

    외부에는 기존 Typo(span, suggest) 구조를 유지한다.
    """

    if not text.strip():
        return []

    response_data = _request_bareun(text)

    return _extract_typos(
        response_data
    )

def _ranges_overlap(
    a: DetectedTypo,
    b: DetectedTypo,
) -> bool:
    """
    두 교정 범위가 실제 입력 문장에서 겹치는지 확인한다.

    범위는 [start, end) 방식이다.
    """
    return (
        a.start < b.end
        and b.start < a.end
    )


def _contains_range(
    outer: DetectedTypo,
    inner: DetectedTypo,
) -> bool:
    """
    outer가 inner의 전체 범위를 포함하는지 확인한다.
    """
    return (
        outer.start <= inner.start
        and outer.end >= inner.end
    )

def merge_detected_typos(
    text: str,
    rule_typos: list[DetectedTypo],
    bareun_typos: list[DetectedTypo],
) -> list[DetectedTypo]:
    """
    Rule + Bareun 상세 결과를 위치 기반으로 병합한다.

    원칙:
    1. 고신뢰 Rule이 Bareun보다 우선한다.
    2. 겹침 판단은 문자열 포함이 아니라 start/end 위치를 사용한다.
    3. Bareun의 넓은 띄어쓰기 교정 안에 Rule 교정이 포함되면
       가능한 경우 두 결과를 하나로 합친다.
    4. 동일 영역에서 서로 다른 방식으로 수정하면
       priority가 높은 Rule을 사용한다.
    5. Bareun 내부의 더 높은 priority 교정도
       넓은 Bareun 결과에 안전하게 합칠 수 있으면 합친다.
    """

    del text  # 현재는 위치가 각 DetectedTypo에 이미 저장되어 있음

    results: list[DetectedTypo] = []

    sorted_rules = sorted(
        rule_typos,
        key=lambda item: (
            -item.priority,
            item.start,
            -(item.end - item.start),
        ),
    )

    sorted_bareun = sorted(
        bareun_typos,
        key=lambda item: (
            item.start,
            -(item.end - item.start),
            -item.priority,
        ),
    )

    covered_rule_ids: set[int] = set()

    for bareun in sorted_bareun:
        suggestion = bareun.suggest
        conflicting = False
        applied_rule_ids: list[int] = []

        # --------------------------------------------------------
        # 1. Bareun 결과와 겹치는 Rule 처리
        # --------------------------------------------------------
        for rule_index, rule in enumerate(sorted_rules):
            if not _ranges_overlap(
                bareun,
                rule,
            ):
                continue

            # Bareun의 더 넓은 범위 안에 Rule이 포함된 경우
            if _contains_range(
                bareun,
                rule,
            ):
                # Bareun 교정 이후에도 Rule 원문이 남아 있으면
                # Rule 교정을 Bareun suggestion에 추가 적용
                if rule.span in suggestion:
                    suggestion = suggestion.replace(
                        rule.span,
                        rule.suggest,
                        1,
                    )

                    applied_rule_ids.append(
                        rule_index
                    )

                    continue

                # 이미 Bareun이 같은 영역을 다른 형태로 바꿨다면
                # 더 높은 priority인 Rule을 우선한다.
                if rule.priority > bareun.priority:
                    conflicting = True
                    break

            # Rule이 Bareun 전체 범위를 포함하거나
            # 서로 일부만 겹치는 경우
            elif rule.priority >= bareun.priority:
                conflicting = True
                break

        if conflicting:
            continue

        # --------------------------------------------------------
        # 2. 같은 Bareun 결과 안의 더 높은 priority 교정을 흡수
        #
        # 예:
        # 회의록정리헤줘 → 회의록 정리헤줘 (SPACING 60)
        # 헤줘 → 해줘                       (TYPO 80)
        # --------------------------------------------------------
        for inner in sorted_bareun:
            if inner is bareun:
                continue

            if inner.priority <= bareun.priority:
                continue

            if not _contains_range(
                bareun,
                inner,
            ):
                continue

            if inner.span not in suggestion:
                continue

            suggestion = suggestion.replace(
                inner.span,
                inner.suggest,
                1,
            )

        # 이미 채택한 더 넓은 결과와 겹치면 중복 표시하지 않는다.
        if any(
            _ranges_overlap(
                accepted,
                bareun,
            )
            for accepted in results
        ):
            continue

        results.append(
            DetectedTypo(
                span=bareun.span,
                suggest=suggestion,
                start=bareun.start,
                end=bareun.end,
                source="hybrid",
                category=bareun.category,
                priority=bareun.priority,
            )
        )

        covered_rule_ids.update(
            applied_rule_ids
        )

    # ------------------------------------------------------------
    # 3. Bareun에 흡수되지 않은 Rule 추가
    # ------------------------------------------------------------
    for rule_index, rule in enumerate(sorted_rules):
        if rule_index in covered_rule_ids:
            continue

        overlaps_existing = any(
            _ranges_overlap(
                accepted,
                rule,
            )
            for accepted in results
        )

        if overlaps_existing:
            # 기존 결과가 Rule보다 낮은 우선순위라면 교체
            overlapping_indexes = [
                index
                for index, accepted in enumerate(results)
                if _ranges_overlap(
                    accepted,
                    rule,
                )
            ]

            higher_or_equal_exists = any(
                results[index].priority
                >= rule.priority
                for index in overlapping_indexes
            )

            if higher_or_equal_exists:
                continue

            results = [
                accepted
                for accepted in results
                if not _ranges_overlap(
                    accepted,
                    rule,
                )
            ]

        results.append(rule)

    results.sort(
        key=lambda item: (
            item.start,
            -item.priority,
            -(item.end - item.start),
        )
    )

    return results

def _remove_whitespace(text: str) -> str:
    return "".join(text.split())


def _is_spacing_only_correction(
    detected: DetectedTypo,
) -> bool:
    """
    Bareun의 순수 띄어쓰기 교정인지 판단한다.

    예:
    정리해줘 -> 정리해 줘
    => True

    회의록정리헤줘 -> 회의록 정리해줘
    => False
       (띄어쓰기뿐 아니라 '헤줘 -> 해줘'도 변경됨)
    """

    return (
        detected.category == "SPACING"
        and _remove_whitespace(detected.span)
        == _remove_whitespace(detected.suggest)
    )

def _to_api_typos(
    detected_typos: list[DetectedTypo],
) -> list[Typo]:
    """
    내부 DetectedTypo 결과를 기존 API Typo 형식으로 변환한다.

    Backend / Frontend 계약은 변경하지 않는다.

    순수 띄어쓰기 교정은 Promptune의 오탈자 후보에서 제외한다.
    단, 띄어쓰기와 실제 오타가 함께 수정된 결과는 유지한다.
    """

    results: list[Typo] = []
    seen: set[tuple[str, str]] = set()

    for detected in detected_typos:
        if _is_spacing_only_correction(detected):
            continue

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

def check_spelling_hybrid(
    text: str,
) -> list[Typo]:
    """
    Rule + Bareun Hybrid 맞춤법 검사.

    - Rule Engine: 고신뢰 비정형 오타
    - Bareun: 일반 맞춤법/띄어쓰기/문법
    - Merge: start/end + priority 기반
    """

    rule_typos = detect_typos_detailed(
        text
    )

    try:
        bareun_typos = check_spelling_detailed(
            text
        )

    except (RuntimeError, OSError):
        # Bareun API 오류, 네트워크 오류, timeout 등이 발생해도
        # 프롬프트 전체 진단은 실패시키지 않는다.
        # Rule Engine 결과만 사용해서 fail-open 한다.
        return _to_api_typos(
            rule_typos
        )

    merged = merge_detected_typos(
        text=text,
        rule_typos=rule_typos,
        bareun_typos=bareun_typos,
    )

    return _to_api_typos(
        merged
    )