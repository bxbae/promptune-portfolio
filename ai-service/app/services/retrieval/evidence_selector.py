from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse


_TOKEN_RE = re.compile(
    r"[가-힣A-Za-z0-9]+"
)

_STOPWORDS = {
    "알려줘",
    "알려",
    "설명해줘",
    "설명",
    "검색해줘",
    "검색",
    "찾아줘",
    "찾아봐",
    "대해",
    "대한",
    "관련",
    "최근",
    "최신",
    "현재",
    "오늘",
    "지금",
    "뉴스",
    "소식",
}


def _normalize(text: str) -> str:
    return re.sub(
        r"\s+",
        "",
        str(text or "").lower(),
    )


def _domain(url: str) -> str:
    try:
        return (
            urlparse(url)
            .netloc
            .lower()
            .removeprefix("www.")
        )
    except Exception:
        return ""


def _query_tokens(query: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(
            str(query or "")
        )
        if len(token) >= 2
        and token.lower() not in _STOPWORDS
    }


def _authority_bonus(
    url: str,
    intent: str,
) -> float:
    domain = _domain(url)
    intent = str(intent or "").upper()

    if not domain:
        return 0.0

    if intent == "PROFILE":
        if (
            "wikipedia.org" in domain
            or "namu.wiki" in domain
        ):
            return 0.15

    if intent == "RESEARCH":
        if (
            domain.endswith(".go.kr")
            or ".go.kr" in domain
            or domain.endswith(".gov")
            or ".gov." in domain
            or domain.endswith(".ac.kr")
            or ".ac.kr" in domain
            or domain.endswith(".edu")
            or ".edu." in domain
            or domain.endswith(".re.kr")
            or ".re.kr" in domain
        ):
            return 0.18

    return 0.0


# 2026-09-02: "이강인 선수에 대해 알려줘"처럼 "최근"/"최신"/"오늘" 같은 시점
# 표현이 없는 프로필 질의는 search_plan.py가 freshness="NONE"으로 분류하고,
# 그래도 tavily_search.py의 PROFILE 경로가 소속 변경 같은 최신 사실을
# 놓치지 않도록 최근 1주일 뉴스를 보조로 함께 가져오게 고쳤다(그 커밋의
# tavily_search.py 변경 참고). 하지만 여기 점수 계산이 발행일을 전혀
# 보지 않으면, 그렇게 붙여온 최신 뉴스가 위키백과 권위 가산점(PROFILE +0.15,
# 위 _authority_bonus)이나 우연히 높은 Tavily score를 받은 오래된 위키
# 스냅샷에 밀려 최종 3건 안에 못 들 수 있다. 발행일이 최근(기본 30일
# 이내)이면 소폭 가산점을 줘서 이런 역전을 줄인다.
#
# published_date 필드 자체가 없는 결과(위키백과/나무위키 문서 대부분,
# 그리고 이 필드를 채우지 않는 기존 테스트 픽스처)는 영향받지 않는다 -
# 즉 이 로직은 "발행일이 있고 최근일 때"만 개입하고, "발행일을 모를 때"는
# 예전처럼 그대로 둔다(하위 호환).
_FRESHNESS_BONUS = 0.10
_FRESHNESS_WINDOW_DAYS = 30

_PUBLISHED_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _freshness_bonus(item: dict) -> float:
    raw = item.get("published_date") or item.get("publishedDate")

    if not raw:
        return 0.0

    match = _PUBLISHED_DATE_RE.search(str(raw))

    if not match:
        return 0.0

    try:
        published = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return 0.0

    age_days = (
        datetime.now(timezone.utc) - published
    ).days

    if 0 <= age_days <= _FRESHNESS_WINDOW_DAYS:
        return _FRESHNESS_BONUS

    return 0.0


def _contains_entity(
    item: dict,
    entity: str | None,
) -> bool:
    if not entity:
        return True

    normalized_entity = _normalize(entity)

    if not normalized_entity:
        return True

    haystack = _normalize(
        " ".join([
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("url") or ""),
        ])
    )

    return normalized_entity in haystack


def _score_result(
    item: dict,
    *,
    query: str,
    intent: str,
    entity: str | None,
) -> float:
    tavily_score = float(
        item.get("score") or 0.0
    )

    title = str(
        item.get("title") or ""
    )
    content = str(
        item.get("content") or ""
    )
    combined = f"{title} {content}"

    final_score = tavily_score

    if entity:
        normalized_entity = _normalize(entity)
        normalized_result = _normalize(combined)

        if (
            normalized_entity
            and normalized_entity
            in normalized_result
        ):
            final_score += 0.20
        else:
            final_score -= 0.08

    tokens = _query_tokens(query)

    if tokens:
        lowered = combined.lower()
        matched = sum(
            1
            for token in tokens
            if token in lowered
        )

        final_score += min(
            matched * 0.03,
            0.15,
        )

    final_score += _authority_bonus(
        str(item.get("url") or ""),
        intent,
    )

    final_score += _freshness_bonus(item)

    return final_score


def select_web_evidence(
    results: list[dict],
    *,
    query: str,
    intent: str,
    entity: str | None,
    limit: int = 3,
) -> list[dict]:
    if limit <= 0:
        return []

    unique = []
    seen_urls = set()
    seen_titles = set()

    for item in results:
        url_key = _normalize(
            item.get("url", "")
        )
        title_key = _normalize(
            item.get("title", "")
        )

        if (
            url_key
            and url_key in seen_urls
        ):
            continue

        if (
            title_key
            and title_key in seen_titles
        ):
            continue

        if url_key:
            seen_urls.add(url_key)

        if title_key:
            seen_titles.add(title_key)

        unique.append(item)

    # PROFILE 질의는 대상 인물/조직이 틀린 evidence를 사용할 수 없다.
    #
    # 예:
    #   query="손흥민 이력서 알려줘", entity="손흥민"
    #   홍명보/김연경/정몽규 문서는 Tavily score가 높더라도 제거한다.
    #
    # GENERAL/RESEARCH는 간접적으로 관련된 문서가 유효할 수 있으므로
    # hard filtering을 적용하지 않는다.
    if intent == "PROFILE" and entity:
        unique = [
            item
            for item in unique
            if _contains_entity(item, entity)
        ]

    ranked = sorted(
        unique,
        key=lambda item: _score_result(
            item,
            query=query,
            intent=intent,
            entity=entity,
        ),
        reverse=True,
    )

    return ranked[:limit]
