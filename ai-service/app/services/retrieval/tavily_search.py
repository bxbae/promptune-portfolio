import os
import re
from tavily import TavilyClient

# 2026-08-26: "침착맨 몇살이야?" 같은 질의에서 관련성 약한 결과(예: 은퇴 준비
# 나이를 다루는 완전히 무관한 영문 기사)가 섞여 들어와 HCX가 근거 없는
# 생년월일을 지어내는 사례가 확인됨. Tavily의 include_domains로 신뢰할 수
# 있는 뉴스 도메인만 검색되게 제한하면, 검색 폭(topic="news") 안에서도
# 출처 품질을 통제할 수 있음. 팀이 코드 배포 없이 도메인 목록을 조정할 수
# 있도록 환경변수로 뺐고, 값이 없으면 네이버뉴스 기본값을 씀(요청대로
# "네이버 뉴스로 한정").
_DEFAULT_TRUSTED_DOMAINS = ["news.naver.com", "ytn.co.kr", "imnews.imbc.com"]

# 2026-08-26: 위 도메인 제한을 배포한 직후 "오늘 삼성 주가"에 실제와 전혀
# 다른 가격(약 90,000원, 실제로는 261,500원)을 자신 있게 답하는 회귀가
# 확인됨. news.naver.com은 시세 숫자가 실시간으로 박혀 있는 페이지가 아니라
# 일반 보도 기사 위주라, 도메인을 여기로만 좁히면 정작 "오늘 종가가 몇
# 원인지" 같은 구체적 숫자를 담은 자료를 못 찾고 HCX가 숫자를 지어내는
# 쪽으로 후퇴함(반대로 예전엔 Reuters/CNBC 등 시세를 직접 인용하는 기사가
# 걸려서 정확했음). 시세류 질의는 Tavily의 전용 topic="finance"를 쓰고,
# 이 경우엔 news.naver.com 제한도 적용하지 않는다 - 신뢰 도메인 제한의
# 원래 목적(무관한 기사 혼입 방지)과 별개로 애초에 topic="finance"
# 자체가 금융 데이터 소스로 좁혀 나오므로 추가 제한이 오히려 결과 자체를
# 0건으로 만들 위험이 큼.
#
# 2026-08-26: 뉴스 경로가 news.naver.com 하나로만 좁혀져 있어서 "방탄소년단
# 최근 이슈"(그래미 보이콧 관련 기사가 안 붙음), "침착맨"/"리센느" 요약
# 요청(관련 기사가 아예 없거나 무관한 내용으로 답함) 같은 사례가 확인됨 -
# 사용자가 직접 "YTN 뉴스나 MBC 뉴스도 링크에 포함해달라"고 요청함. 신뢰
# 도메인을 늘리면 같은 인물/이슈를 다루는 기사를 찾을 확률이 올라간다.
_FINANCE_MARKERS = [
    "주가", "주식", "환율", "시세", "지수", "코스피", "코스닥",
    "비트코인", "종가", "시가총액", "증시",
]


def _is_finance_query(query: str) -> bool:
    text = query.lower()
    return any(marker in text for marker in _FINANCE_MARKERS)


# 2026-08-26: "이강인 축구선수 프로필/소속" 질의가 검색어 정제(0009) 이후로는
# 관련 있는 기사를 찾긴 하는데도, 정작 답변은 나무위키의 오래된 문단(발렌시아
# CF 시절)이나 근거 없는 수치(체중 90kg, 생년월일 2003년 등 - 실제는 66kg,
# 2001년생)를 섞어 냄. 사용자가 직접 "선수는 올림픽 사이트, 가수/배우는
# 그래미 사이트를 기준으로" 요청함 - 위키백과/나무위키처럼 최신 정보가
# 계속 갱신되는 백과사전류 + 종목별 공식/권위 사이트를 신뢰 도메인으로 쓰면
# news.naver.com류 개별 보도 기사보다 최신 프로필 정보가 안정적으로 잡힌다.
_PROFILE_MARKERS = [
    "프로필", "약력", "소속", "선수", "감독", "가수", "배우", "인물",
    "유튜버", "단장", "코치", "아이돌", "뮤지션",
    # 2026-08-26: "정치인"/"인플루언서"류 인물 요청도 프로필 경로(위키백과/
    # 나무위키 등 최신 정보가 갱신되는 백과사전 소스)를 타야 한다는 사용자
    # 요청에 따라 추가.
    "정치인", "인플루언서", "크리에이터", "코미디언", "국회의원",
]

# 2026-08-26: 처음엔 "선수/축구/올림픽" 같은 키워드가 있을 때만 olympics.com을,
# "가수/배우" 등이 있을 때만 grammy.com을 추가하는 방식이었는데, "이강인
# 소속과 프로필을 알려줘"처럼 인물의 직업을 나타내는 단어가 아예 없는(이름 +
# "소속"/"프로필"뿐인) 질의가 흔해서 olympics.com이 빠지고 결과가 부실해지는
# 사례가 반복 확인됨. 문구가 조금만 달라져도(예: "3문단으로" -> "3문장으로",
# "최근 이슈" -> "최근 골 소식") 키워드 매칭이 계속 깨지는 패턴이 이번 세션
# 내내 반복됐던 걸 보면, 카테고리를 문구로 추측하는 방식 자체가 근본적으로
# 약함. include_domains는 "이 안에서만 찾아라"는 제약일 뿐이라 관련 없는
# 도메인을 넣어도 결과가 나빠지지 않으므로(그 도메인에 해당 인물 문서가
# 없으면 그냥 안 나올 뿐), 프로필 질의면 카테고리 추측 없이 항상 4개
# 도메인을 전부 후보에 넣는다.
_PROFILE_BASE_DOMAINS = [
    "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
]

# 2026-08-26: "다른 유튜버를 검색해보니 검색 결과가 음악인으로 잘못 나온다"는
# 사용자 리포트가 확인됨 - 위 문단의 "항상 4개 도메인 전부"는 카테고리를
# 모를 때(마커가 전혀 없을 때)는 여전히 맞지만, 질의에 "유튜버"/"정치인"/
# "인플루언서"처럼 음악인·체육인이 아니라는 게 명시된 경우까지 grammy.com/
# olympics.com을 검색 후보에 넣으면, 이름이 일부만 겹치는 무관한 음악인/
# 체육인 문서가 섞여 들어와 모델이 인물을 혼동하는 사례가 생긴다. 이런
# 명시적 비-음악/비-체육 인물은 사용자가 요청한 대로 "언론사 인터뷰 +
# 위키백과"를 근거로 삼는다 - grammy/olympics 대신 신뢰 뉴스 도메인
# (_trusted_domains(), 환경변수로 조정 가능)을 후보에 넣는다.
_NON_MUSIC_SPORTS_PROFILE_MARKERS = [
    "유튜버", "정치인", "인플루언서", "크리에이터", "코미디언",
    "국회의원", "시장", "장관", "대통령", "아나운서", "기자",
]

# 2026-08-26: namu.wiki 검색 결과 제목이 "이강인 (r444 판)"처럼 특정 리비전
# 번호를 달고 오는 경우가 확인됨 - 발렌시아 CF 시절 등 예전 스냅샷이라 현재
# 소속(아틀레티코 마드리드)이 반영 안 된 문서였음. 최신 문서 대신 이런 과거
# 리비전 스냅샷이 섞여 들어오면 답변이 다시 오래된 정보로 후퇴하므로,
# 이런 리비전 스냅샷 결과는 아예 제외하고(현재 페이지가 따로 있으면 그걸
# 쓰고, 없으면 아래 "0건이면 무제한 재시도" 폴백이 대신 처리한다).
_STALE_WIKI_REVISION_TITLE_RE = re.compile(r"\(r\d+\s*판\)")


def _is_stale_wiki_revision(item: dict) -> bool:
    return bool(
        _STALE_WIKI_REVISION_TITLE_RE.search(item.get("title") or "")
    )


def _is_profile_query(query: str) -> bool:
    text = query.lower()
    return any(marker in text for marker in _PROFILE_MARKERS)


def _is_non_music_sports_profile_query(query: str) -> bool:
    text = query.lower()
    return any(marker in text for marker in _NON_MUSIC_SPORTS_PROFILE_MARKERS)


def _profile_domains(query: str) -> list[str]:
    # 2026-08-27: "위키백과 링크만 나오는데, YTN/MBC/올림픽/그래미 사이트에도
    # 검색 결과가 있으면 신뢰도를 높이기 위해 같이 넣어달라"는 사용자 요청이
    # 확인됨. 기존에는 음악/체육인 프로필이면 위키+올림픽+그래미만, 비-음악/
    # 체육 인물이면 위키+신뢰뉴스만 - 즉 둘 중 하나만 후보에 넣었어서, 예를
    # 들어 아이돌 그룹처럼 grammy.com/olympics.com에 문서가 없는 음악인은
    # 신뢰뉴스 도메인이 아예 후보에 없어 위키 링크만 나올 수밖에 없었다.
    # include_domains는 "이 안에서만 찾아라"는 제약일 뿐이고 관련 없는
    # 도메인을 넣어도 결과가 나빠지지 않으므로(그 도메인에 해당 인물 문서가
    # 없으면 그냥 안 나올 뿐), 신뢰 뉴스 도메인을 항상 함께 후보에 넣어서
    # Tavily가 실제로 찾은 도메인이면 어디든 결과에 섞여 나올 수 있게 한다.
    if _is_non_music_sports_profile_query(query):
        return list(
            dict.fromkeys(["ko.wikipedia.org", "namu.wiki"] + _trusted_domains())
        )
    return list(
        dict.fromkeys(_PROFILE_BASE_DOMAINS + _trusted_domains())
    )


# 2026-08-26: "최근 골 소식과 관련해서" 같은 요청에 몇 달~몇 년 전 기사가 섞여
# 나와도 검색 결과 개수만 맞으면 그대로 근거로 쓰이는 문제가 확인됨 - 사용자가
# 명시적으로 "최근 소식은 오늘 기준 일주일 이내 기사로 한정해달라"고 요청함.
# Tavily search()의 time_range 파라미터('day'|'week'|'month'|'year')로 결과
# 자체를 그 기간 안으로 제한할 수 있다. 이 마커는 search_query_cleanup.py가
# 검색어를 정제(불용구 제거)하기 전의 원문 질의(effective_query)에 대해
# retrieval_orchestrator.py에서 판정해야 한다 - 정제 이후에는 "최근 골 소식과
# 관련해서" 같은 문구 자체가 이미 지워져 있어 여기서 판정하면 항상 False가 된다.
_RECENCY_MARKERS = [
    "오늘", "어제", "지금", "현재", "최근", "최신", "요즘", "방금",
]


def is_recency_query(query: str) -> bool:
    text = (query or "").lower()
    return any(marker in text for marker in _RECENCY_MARKERS)


def _trusted_domains() -> list[str]:
    raw = os.getenv("TAVILY_TRUSTED_DOMAINS")
    if raw is None:
        # 환경변수 자체가 없으면(.env.production에 아직 안 넣었으면) 기본값 사용
        return _DEFAULT_TRUSTED_DOMAINS
    # 환경변수를 일부러 빈 값/공백으로 설정하면 도메인 제한 없이 검색
    # (TAVILY_TRUSTED_DOMAINS= 처럼 값 없이 등록한 경우)
    domains = [d.strip() for d in raw.split(",") if d.strip()]
    return domains


# 2026-08-26: patch 21로 "침착맨에대해" 같은 검색어를 "침착맨" 단일 토큰으로
# 정리한 뒤에도 완전히 지어낸 답변이 재현됨. docker logs로 실제 Tavily
# 응답을 확인한 결과, 신뢰 도메인 제한(topic="news", time_range="week")
# 검색이 "0건"이 아니라 "결과는 있지만 관련성 점수(score)가 0.12/0.046으로
# 사실상 무관한" 기사(YTN 오늘의 운세, 무관한 감독 인터뷰)를 반환했음 -
# topic="news"는 도메인/기간 제약 안에서 진짜 매칭이 없어도 빈 리스트 대신
# "그나마 가장 가까운" 기사를 돌려주는 것으로 보인다. 그래서 기존 "결과가
# 0건이면 다음 단계로" 폴백 조건(if not results)이 트리거되지 않고, 정답이
# 있는 위키백과 폴백까지 도달하지 못했다. Tavily 응답의 score 필드(이미
# [Retrieval] 로그에 쓰고 있음)로 "사실상 무관함"을 판정해서, 그런 경우도
# 다음 단계로 넘어가게 한다.
#
# score 필드가 아예 없는 응답(테스트 픽스처 등 - 실제 Tavily 응답에는
# 항상 있음)은 이 판정에서 제외해 기존 동작을 그대로 보존한다 - 즉 이
# 검사는 "score가 있는데 낮을 때"만 개입하고, "score를 모를 때"는 예전
# 처럼 결과를 그대로 신뢰한다.
_LOW_RELEVANCE_SCORE_THRESHOLD = 0.3


def _has_low_relevance_score(item: dict) -> bool:
    score = item.get("score")
    return isinstance(score, (int, float)) and score < _LOW_RELEVANCE_SCORE_THRESHOLD


def _all_low_relevance(results: list) -> bool:
    return bool(results) and all(_has_low_relevance_score(r) for r in results)


def _run_search(client, query, max_results, topic, include_domains, time_range=None):
    search_kwargs = dict(
        query=query,
        search_depth="basic",
        topic=topic,
        max_results=max_results,
        include_answer=False,
        include_raw_content=False,
    )

    if include_domains:
        search_kwargs["include_domains"] = include_domains

    if time_range:
        search_kwargs["time_range"] = time_range

    response = client.search(**search_kwargs)
    results = response.get("results", [])

    return [r for r in results if not _is_stale_wiki_revision(r)]


def search_web(
    query,
    max_results=5,
    time_range=None,
    search_intent=None,
    entity=None,
):
    if not query.strip():
        raise ValueError("검색어가 비어 있습니다.")

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY가 없습니다.")

    client = TavilyClient(api_key=api_key)
    query = query.strip()

    intent = str(
        search_intent or ""
    ).strip().upper()

    use_finance_policy = (
        intent == "FINANCE"
        or (
            not intent
            and _is_finance_query(query)
        )
    )

    use_profile_policy = (
        intent == "PROFILE"
        or (
            not intent
            and _is_profile_query(query)
        )
    )

    if use_finance_policy:
        # 시세류 질의는 항상 "오늘/지금" 기준 최신값이 필요하므로 time_range를
        # 별도로 받지 않는다 - topic="finance" 자체가 이미 최신 시세 데이터
        # 소스로 좁혀져 있어 추가 제한이 오히려 결과를 0건으로 만들 위험이 크다.
        return _run_search(
            client, query, max_results,
            topic="finance",
            include_domains=None,
        )

    if use_profile_policy:
        # topic="news"가 아니라 "general"을 쓴다 - 위키백과/나무위키 문서는
        # Tavily 기준 "뉴스" 콘텐츠가 아니라서, topic="news"로 두면
        # include_domains에 넣어도 결과 자체가 안 나올 위험이 있다.
        profile_domains = _profile_domains(query)

        results = _run_search(
            client, query, max_results,
            topic="general",
            include_domains=profile_domains,
            time_range=time_range,
        )

        # 위키백과/나무위키/종목별 공식 사이트에 아예 문서가 없는 인물일 수도
        # 있으므로(예: 인지도가 낮은 인물), 결과가 0건이면 도메인 제한 없이
        # 한 번 더 시도한다 - 아래 뉴스 경로의 폴백과 동일한 원칙.
        if not results:
            results = _run_search(
                client, query, max_results,
                topic="general",
                include_domains=None,
                time_range=time_range,
            )

        return results

    # 2026-08-25(원 커밋): 스포츠 경기 결과처럼 시간에 민감한 질의에서
    # "프리뷰/예측" 기사가 "결과" 기사보다 검색어와 더 유사하다는 이유로
    # 상위에 올라와, 실제 스코어가 없는 기사를 근거로 모델이 결과를 잘못
    # 답하는 사례가 확인됨(예: 경기 전 프리뷰 기사가 상위 노출). topic="news"는
    # 최신 뉴스/발행일 기준으로 결과를 우선하도록 Tavily에 알려줘서, 예측성
    # 기사보다 실제 보도(결과) 기사가 뽑힐 확률을 높인다.
    trusted_domains = _trusted_domains()

    results = _run_search(
        client, query, max_results,
        topic="news",
        include_domains=trusted_domains,
        time_range=time_range,
    )

    # 2026-08-26: "LG 트윈스 단장님의 이름과 약력을 안내해줘" 같은 질의에서
    # news.naver.com 하나로 제한한 결과가 0건이 되면서, 웹 검색 결과가
    # 아예 없는 채로 생성이 진행돼 HCX가 "제공할 수 없습니다"로 답변을
    # 회피하는 사례가 확인됨. 신뢰 도메인 제한의 목적(무관한 기사 혼입
    # 방지)은 결과가 여러 개 있을 때 그중 나쁜 걸 거르는 것이지, 결과
    # 자체를 아예 없애려는 게 아니므로 - 제한된 검색이 0건이면 제한 없이
    # 한 번 더 시도한다.
    if (not results or _all_low_relevance(results)) and trusted_domains:
        results = _run_search(
            client, query, max_results,
            topic="news",
            include_domains=None,
            time_range=time_range,
        )

    # 2026-08-26: "침착맨에 대해 요약해줘"(프로필/유튜버/정치인 같은 마커가
    # 전혀 없는 인물 요약 요청)가 위 뉴스 경로로 들어왔는데, topic="news" +
    # time_range="week" 제한 안에 해당 인물을 다루는 최근 보도가 하나도
    # 없어서 웹 검색 결과 0건인 채로 생성이 진행되고, HCX가 완전히 지어낸
    # 인물 정보(실제와 무관한 데뷔 연도·오디션 우승 이력 등)로 답하는 사례가
    # 확인됨. "유튜버"/"인플루언서"/"정치인"처럼 사용자가 카테고리를 직접
    # 말해줘도 질의 문장 자체엔 그 단어가 없는 경우가 흔해서("침착맨에 대해
    # 요약해줘"에는 "유튜버"가 없음) 마커 목록을 아무리 늘려도 이 경우를 다
    # 잡을 수 없다 - 대신 "최근 뉴스가 없다"는 사실 자체를 신호로 삼는다.
    # 최신 보도가 없다고 해서 위키백과/나무위키 같은 기본 인물 정보까지
    # 없는 건 아니므로, 뉴스 경로가 완전히 빈손이면 마지막으로 프로필
    # 도메인(위키백과/나무위키 + 신뢰 뉴스)으로 한 번 더 시도한다.
    # time_range는 여기서 빼는데, 인물 개요/약력 자체는 "최근 1주일"에
    # 얽매일 이유가 없고 오히려 결과를 0건으로 만들 위험만 커지기 때문이다.
    if not results or _all_low_relevance(results):
        results = _run_search(
            client, query, max_results,
            topic="general",
            include_domains=list(
                dict.fromkeys(["ko.wikipedia.org", "namu.wiki"] + trusted_domains)
            ),
        )

    return results
