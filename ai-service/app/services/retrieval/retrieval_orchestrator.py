from __future__ import annotations

from app.services.action.action_resolver import resolve_action

import re

from app.schemas.models import (
    RetrievalExecuteRequest,
    RetrievalExecuteResponse,
    RetrieveRequest,
    WebSearchResult,
)

from app.services.retrieval.ml_router import (
    classify_ml_retrieval_route,
    resolve_strong_retrieval_route,
)
from app.services.retrieval.tavily_search import is_recency_query, search_web
from app.services.retrieval.conversation_context import resolve_conversation_retrieval
from app.services.retrieval.date_resolver import resolve_relative_dates
from app.services.retrieval.search_query_cleanup import build_search_query
from app.services.retrieval.search_plan import build_search_plan
from app.services.retrieval.evidence_selector import select_web_evidence

from app.services.retrieval.rag_retriever import (
    retrieve,
    retrieve_document_overview,
    retrieve_document_catalog,
    find_metadata_document_ids,
)


_OVERVIEW_MARKERS = (
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
    "각 항목",
    "각항목",
    "전체 항목",
    "항목들",
    "구성 항목",
    "목차",
)


_DOCUMENT_TRANSFORM_MARKERS = (
    "보고서로 만들어",
    "문서로 만들어",
    "파일로 만들어",
    "pdf로 만들어",
    "워드로 만들어",
    "word로 만들어",
    "docx로 만들어",
    "양식으로 만들어",
    "템플릿으로 만들어",
)


def _is_document_transform_query(query: str) -> bool:
    text = str(query or "").strip().lower()
    return any(
        marker in text
        for marker in _DOCUMENT_TRANSFORM_MARKERS
    )


def _is_document_overview_query(query: str) -> bool:
    text = str(query or "").strip().lower()
    return any(marker in text for marker in _OVERVIEW_MARKERS)


def _clean_document_followup_query(query: str) -> str:
    """특정 document_id가 확정된 뒤에는 지시대명사 노이즈를 최소화한다."""
    text = str(query or "").strip()

    replacements = (
        "거기서",
        "그 문서에서",
        "그 파일에서",
        "해당 문서에서",
        "해당 파일에서",
        "그 문서",
        "그 파일",
        "그 이력서",
        "그 보고서",
        "아까 문서",
        "아까 파일",
        "전에 올린 문서",
        "전에 올린 파일",
    )

    for marker in replacements:
        text = text.replace(marker, " ")

    text = re.sub(r"\s+", " ", text).strip()
    return text or query


_EXTERNAL_COMPARISON_MARKERS = (
    "비교해",
    "비교해줘",
    "비교해서",
    "맞는지",
    "맞아?",
    "맞나요",
    "검증해",
    "검증해줘",
    "확인해",
    "확인해줘",
    "검토해",
    "검토해줘",
)

_EXTERNAL_REFERENCE_MARKERS = (
    "현재",
    "지금",
    "최근",
    "최신",
    "오늘",
    "현행",
    "법률",
    "법",
    "법규",
    "노동법",
    "근로기준법",
    "정부 기준",
    "공식 기준",
    "시장",
    "시장가",
    "시장 가격",
    "시세",
    "환율",
    "주가",
    "최신 자료",
    "외부 자료",
    "웹",
    "인터넷",
    "뉴스",
    "실시간",
)


def _should_auto_use_web_with_internal(
    query: str,
    document_ids: list[int],
) -> bool:
    """
    확정된 내부/첨부 문서를 외부의 현재·공식 사실과
    비교/검증하는 요청일 때만 Web 검색을 함께 실행한다.

    단순 문서 요약/질의는 Web을 호출하지 않는다.
    """
    if not document_ids:
        return False

    text = str(query or "").strip().lower()

    if not text:
        return False

    has_comparison = any(
        marker in text
        for marker in _EXTERNAL_COMPARISON_MARKERS
    )

    has_external_reference = any(
        marker in text
        for marker in _EXTERNAL_REFERENCE_MARKERS
    )

    return has_comparison and has_external_reference



_DOCUMENT_CATALOG_PHRASES = (
    "내부문서에 뭐",
    "내부 문서에 뭐",
    "내부문서에는 뭐",
    "내부 문서에는 뭐",
    "내부문서 무슨 파일",
    "내부 문서 무슨 파일",
    "내부문서에는 무슨 파일",
    "내부 문서에는 무슨 파일",
    "사내문서에 뭐",
    "사내 문서에 뭐",
    "문서함에 뭐",
    "문서함에는 뭐",
)


def _is_document_catalog_query(
    query: str,
) -> bool:
    text = " ".join(
        str(query or "").lower().split()
    )

    compact = "".join(
        text.split()
    )

    if any(
        "".join(phrase.split()) in compact
        for phrase in _DOCUMENT_CATALOG_PHRASES
    ):
        return True

    has_internal_scope = any(
        marker in compact
        for marker in (
            "내부문서",
            "사내문서",
            "문서함",
        )
    )

    has_catalog_intent = any(
        marker in compact
        for marker in (
            "뭐있",
            "무슨파일",
            "목록",
            "리스트",
            "어떤문서",
        )
    )

    return (
        has_internal_scope
        and has_catalog_intent
    )


def execute_retrieval(
    req: RetrievalExecuteRequest,
) -> RetrievalExecuteResponse:
    document_ids = list(
        dict.fromkeys(
            int(x)
            for x in req.document_ids
            if x is not None and int(x) > 0
        )
    )

    # Backend가 현재 첨부/이전 첨부를 실제 document_id로 확정해서 보낸 경우에는
    # 대화 텍스트를 다시 HCX로 추정할 필요가 없다. ID가 가장 강한 사실(source of truth)이다.
    if document_ids:
        route = "internal_rag"
        effective_query = _clean_document_followup_query(req.query)
    else:
        conversation = resolve_conversation_retrieval(
            query=req.query,
            history=req.history,
        )
        effective_query = conversation.query
        if conversation.route_override is not None:
            route = conversation.route_override
            action_plan = None
        else:
            action_plan = resolve_action(
                effective_query,
                req.routing_user_context,
            )

            # 명시적인 내부 문서 범위, 실시간 사실, 외부 entity/profile 등
            # source가 확실한 deterministic signal은 ML Action보다 우선한다.
            strong_route = resolve_strong_retrieval_route(
                action_plan.routing_query
            )

            if strong_route is not None:
                route = strong_route
            elif action_plan.retrieval_route:
                route = action_plan.retrieval_route
            else:
                route = "no_retrieval"

            print(
                "[Action] "
                f"action={action_plan.action.value!r} "
                f"confidence={action_plan.confidence:.3f} "
                f"sources={action_plan.sources!r} "
                f"reason={action_plan.reason!r} "
                f"routing_query={action_plan.routing_query!r}"
            )

    print(f"[Retrieval] route={route!r} effective_query={effective_query!r}")

    documents = []
    web_results: list[WebSearchResult] = []

    used_internal_rag = False
    used_web_search = False

    # 1. 내부문서 검색
    if route == "internal_rag":
        if req.owner_user_id is None:
            raise ValueError(
                "internal_rag 검색에는 owner_user_id가 필요합니다."
            )

        if document_ids:
            # 이미 Backend가 실제 문서 ID를 확정해서 보냈다면
            # catalog/metadata discovery보다 이 ID가 가장 강한 source of truth다.
            if (
                _is_document_overview_query(req.query)
                or _is_document_transform_query(req.query)
            ):
                result = retrieve_document_overview(
                    owner_user_id=req.owner_user_id,
                    document_ids=document_ids,
                )
            else:
                retrieve_req = RetrieveRequest(
                    query=effective_query,
                    owner_user_id=req.owner_user_id,
                    top_k=req.top_k,
                    document_ids=document_ids,
                )

                result = retrieve(
                    retrieve_req
                )

        elif _is_document_catalog_query(req.query):
            # "내부문서에는 무슨 파일이 있어?"는 chunk 검색이 아니라
            # 접근 가능한 documents metadata 목록을 조회한다.
            result = retrieve_document_catalog(
                owner_user_id=req.owner_user_id,
            )

        else:
            # 명시적으로 선택된 document_id가 없으면 title/type/description을
            # 사용해 관련 내부문서 후보를 먼저 찾는다.
            metadata_document_ids = find_metadata_document_ids(
                owner_user_id=req.owner_user_id,
                query=effective_query,
                limit=5,
            )

            if metadata_document_ids:
                # 문서 자체가 특정된 경우에는 semantic Top-K 한 조각보다
                # 해당 문서의 실제 내용을 순서대로 읽는 편이 안전하다.
                result = retrieve_document_overview(
                    owner_user_id=req.owner_user_id,
                    document_ids=metadata_document_ids,
                )
            else:
                # metadata에서도 특정 문서를 찾지 못한 경우에만
                # 기존 BGE-M3 semantic retrieval로 fallback한다.
                retrieve_req = RetrieveRequest(
                    query=effective_query,
                    owner_user_id=req.owner_user_id,
                    top_k=req.top_k,
                    document_ids=[],
                )

                result = retrieve(
                    retrieve_req
                )

        documents = result.documents
        used_internal_rag = bool(documents)

    # 2. 웹 / 외부·실시간 검색
    # explicit use_web_search는 internal_rag와 동시에 실행될 수 있다.
    # 즉 특정 첨부문서를 읽으면서 최신 Web 근거를 함께 가져올 수 있다.
    should_use_web = (
        bool(req.use_web_search)
        or route in {"web_search", "external_or_realtime"}
        or _should_auto_use_web_with_internal(
            req.query,
            document_ids,
        )
    )

    if should_use_web:
        # 2026-08-26: "최근"/"최신" 같은 시점 표현은 search_query_cleanup.py의
        # 불용구 제거(패치 13, 예: "최근 골 소식과 관련해서" 전체를 stock
        # phrase로 지움) 이후에는 검색어에서 이미 사라져 있을 수 있다. 그래서
        # "최근 소식은 일주일 이내 기사로 한정" 판정은 정제 전 원문
        # effective_query에 대해 먼저 하고, 그 결과(time_range)만 정제된
        # 검색어와 함께 넘긴다.
        search_plan = build_search_plan(
            effective_query
        )

        recent_only = is_recency_query(
            effective_query
        )

        if search_plan.freshness == "DAY":
            time_range = "day"
        elif (
            search_plan.freshness == "WEEK"
            or recent_only
        ):
            time_range = "week"
        else:
            time_range = None

        search_query = resolve_relative_dates(
            build_search_query(effective_query)
        )

        # Tavily에서는 후보를 조금 넓게 가져온 뒤,
        # Evidence Selector가 실제 generation에 전달할 최대 3건만 고른다.
        final_web_top_k = min(
            max(int(req.top_k), 1),
            3,
        )
        candidate_web_top_k = max(
            final_web_top_k,
            5,
        )

        raw_results = search_web(
            search_query,
            max_results=candidate_web_top_k,
            time_range=time_range,
            search_intent=search_plan.intent,
            entity=search_plan.entity,
        )

        results = select_web_evidence(
            raw_results,
            query=effective_query,
            intent=search_plan.intent,
            entity=search_plan.entity,
            limit=final_web_top_k,
        )

        # 2026-08-26: "이강인 소속과 프로필" 질의가 검색어 정리(패치 13) 이후
        # 오히려 손흥민/조규성처럼 완전히 무관한 인물의 결과가 섞여 들어오는
        # 회귀가 재현됐는데, search_web()이 반환한 실제 title/url을 확인할
        # 방법이 로그에 전혀 없어서(이 파일에 로깅 자체가 없었음) 매번 답변
        # 텍스트만 보고 추측해야 했다. docker logs로 바로 원인을 볼 수 있게
        # route/검색어/실제 검색 결과를 남긴다 - 동작에는 영향 없음(순수 로깅).
        # 2026-08-26: "리센느" 검색 결과가 0건이었던 사례, "방탄소년단" 최근
        # 이슈 질의에 그래미 보이콧 기사가 안 붙은 사례가 확인됐는데, Tavily가
        # 실제로 그 기사를 찾긴 했지만 관련도 점수(score)가 낮아 뒤로 밀렸는지,
        # 애초에 검색 자체가 안 됐는지 로그만으로는 구분이 안 됐다. Tavily
        # 응답의 score 필드를 함께 남겨서 다음에 같은 문제가 재현되면 추측 없이
        # 바로 원인을 좁힐 수 있게 한다 - 동작에는 영향 없음(순수 로깅).
        print(
            f"[Retrieval] route={route!r} search_query={search_query!r} "
            f"search_intent={search_plan.intent!r} "
            f"entity={search_plan.entity!r} "
            f"time_range={time_range!r} "
            f"raw_results={[(r.get('title'), r.get('url'), r.get('score')) for r in raw_results]} "
            f"selected_results={[(r.get('title'), r.get('url'), r.get('score')) for r in results]}"
        )

        web_results = [
            WebSearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=float(
                    item.get("score") or 0.0
                ),
            )
            for item in results
        ]

        used_web_search = bool(web_results)

    return RetrievalExecuteResponse(
        route=route,
        documents=documents,
        web_results=web_results,
        used_internal_rag=used_internal_rag,
        used_web_search=used_web_search,
    )
