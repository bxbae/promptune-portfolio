"""
"어제"/"오늘" 같은 상대 날짜 표현을 실제 캘린더 날짜로 보정해서
웹 검색(Tavily) 쿼리에 붙여주는 유틸.

2026-08-26: "어제 잠실 lg 트윈스 승리여부 알려줘" 같은 요청이 web_search
라우트로는 정확히 분류되는데(ml_router는 문제 없음), 정작 Tavily에
넘어가는 검색어에는 "어제"라는 단어가 그대로 남아있어서 어느 날짜인지
검색엔진이 특정할 방법이 없었음 - 그 결과 실제로는 다른 날짜/다른 상대팀
경기(LG-두산전처럼 검색량이 많은 소재) 내용이 섞여 들어와서, 모델이
스코어도 못 대고 애매하게 답하거나 사실과 다른 답을 하는 문제가 있었음.
파이프라인 어디에도 상대 날짜 -> 절대 날짜 변환이 없어서(grep으로 확인),
검색 직전에만 이 보정을 넣는다.

라우팅 분류(classify_ml_retrieval_route)에는 원문을 그대로 써야 한다 -
routing_train_242.json 학습 데이터의 패턴이 "어제"/"오늘" 같은 원문 단어
기준이라, 여기서 치환된 문자열을 라우팅에도 같이 쓰면 분류가 흔들릴 수
있음. 그래서 이 함수는 검색어를 만들 때만 쓰고, 원문 자체(effective_query)는
그대로 보존한다.

KST는 서머타임이 없어서(연중 UTC+9 고정) tzdata 없이 고정 오프셋으로
처리해도 항상 정확함 - 컨테이너 이미지에 IANA tzdata가 없어도(zoneinfo가
못 찾는 상황) 안전하게 동작하도록 timezone(timedelta(hours=9))를 쓴다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 단어 -> 오늘(KST) 기준 며칠 전/후인지
_RELATIVE_DATE_OFFSETS: dict[str, int] = {
    "그저께": -2,
    "그제": -2,
    "어제": -1,
    "작일": -1,
    "오늘": 0,
    "금일": 0,
    "내일": 1,
    "명일": 1,
    "모레": 2,
}


def resolve_relative_dates(query: str, now: datetime | None = None) -> str:
    """검색어에 들어있는 상대 날짜 단어 뒤에 실제 날짜를 괄호로 덧붙인다.

    예: "어제 lg 트윈스 경기 결과" (오늘이 2026-08-26이면)
        -> "어제(2026-08-25) lg 트윈스 경기 결과"

    단어 자체는 지우지 않고 뒤에 날짜만 덧붙이므로, 검색엔진이 날짜 문맥은
    얻으면서도 원래 표현의 의미(자연스러운 한국어 질의)는 그대로 유지된다.
    """
    if not query:
        return query

    if now is None:
        now = datetime.now(KST)

    resolved = query
    for term, offset_days in _RELATIVE_DATE_OFFSETS.items():
        if term in resolved:
            target_date = (now + timedelta(days=offset_days)).strftime("%Y-%m-%d")
            resolved = resolved.replace(term, f"{term}({target_date})")

    return resolved
