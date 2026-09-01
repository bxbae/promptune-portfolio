from __future__ import annotations

import re
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
