import unittest

from app.services.retrieval.ml_router import (
    classify_ml_retrieval_route,
    resolve_strong_retrieval_route,
)


class ClassifyMlRetrievalRouteTest(unittest.TestCase):
    """
    2026-08-26: "어제 잠실 경기장의 날씨를 안내해주고 lg 트윈스의 승리여부를
    안내해줘." 가 no_retrieval로 잘못 분류돼(routing_train_242.json에
    스포츠 경기 결과 카테고리가 아예 없었음) 웹검색 없이 모델이 완전히
    지어낸 답을 내놓는 문제가 있었음. 학습 데이터 보강 + _is_likely_realtime_fact
    사전 필터로 고친 뒤, 회귀 방지용으로 이 케이스들을 고정한다.
    """

    def test_sports_result_query_routes_to_realtime_search(self):
        route = classify_ml_retrieval_route(
            "어제 잠실 경기장의 날씨를 안내해주고  lg 트윈스의 승리여부를 안내해줘."
        )
        self.assertIn(route, {"external_or_realtime", "web_search"})

    def test_sports_result_query_with_tone_suffix_still_routes_to_search(self):
        # 확장 프로그램이 사용자 질문 뒤에 톤/포맷 지시문을 붙여도(예:
        # "3문단으로", "친근하게") 라우팅이 no_retrieval로 뒤집히면 안 됨.
        query = (
            "어제 잠실 경기장의 날씨를 안내해주고  lg 트윈스의 승리여부를 안내해줘.\n"
            "추가로 필요한 정보: 고객님께, 최근 이슈와 관련해, 3문단으로, "
            "친근하게, 간결하게, 전문용어는 빼고, 기존 템플릿 기반으로"
        )
        route = classify_ml_retrieval_route(query)
        self.assertIn(route, {"external_or_realtime", "web_search"})

    def test_weather_and_stock_queries_still_route_to_realtime_search(self):
        for query in (
            "오늘 서울 날씨 알려줘",
            "지금 삼성전자 주가 얼마야",
            "오늘 원달러 환율 알려줘",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_ml_retrieval_route(query), "external_or_realtime"
                )

    def test_internal_and_conversational_queries_are_unaffected(self):
        self.assertEqual(
            classify_ml_retrieval_route("회사 연차 규정 알려줘"), "internal_rag"
        )
        self.assertEqual(
            classify_ml_retrieval_route("겹치는 문장을 제거해서 자연스럽게 만들어줘"),
            "no_retrieval",
        )

    def test_stock_queries_route_to_realtime_search(self):
        # 2026-08-26: 이 카테고리는 원래 학습 데이터에도 있어서 이전부터
        # 잘 되고 있었음 - 회귀 방지용으로 고정.
        for query in ("지금 삼성전자 주가 알려줘", "삼성전자 주가 알려줘"):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_ml_retrieval_route(query), "external_or_realtime"
                )

    def test_third_party_profile_query_routes_to_realtime_search(self):
        # 2026-08-26: "이강인 소속과 프로필을 알려줘"가 user_context로 잘못
        # 분류돼(학습 데이터의 "프로필"/"소속" 예시가 전부 "내 프로필"류라서
        # char n-gram이 "이강인 프로필"까지 같은 카테고리로 끌고 감) 웹검색을
        # 아예 안 하고, HCX가 근거 없이 완전히 지어낸 답(PSG 소속, 1996년생
        # 등 - 실제로는 아틀레티코 마드리드, 2001년생)을 내놓은 사례가
        # 재현 확인됨. 출처 링크도 당연히 안 붙었음.
        for query in (
            "이강인 소속과 프로필을 알려줘",
            "이강인 선수의 프로필을 안내해줘",
            "침착맨 프로필 알려줘",
            (
                "현제 이강인 소속과 프로필을 알려줘. 나에게. 요약해줘. "
                "최근 골 소식과 관련해서. 3문단으로. 전문적으로. "
                "숫자는 꼭 포함해서"
            ),
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_ml_retrieval_route(query), "external_or_realtime"
                )

    def test_self_profile_query_still_routes_to_user_context(self):
        # 위 수정이 진짜 "내 프로필/소속" 질의까지 웹검색으로 돌려버리는
        # 회귀를 만들지 않았는지 확인 - 학습 데이터의 39개 user_context
        # 예시를 대표하는 케이스들을 고정한다.
        for query in (
            "내 소속 알려줘",
            "내 프로필의 부서 알려줘",
            "내 계정의 소속 알려줘",
            "현재 내 계정의 회사와 부서 알려줘",
            "내 회사 프로필에서 소속 팀 확인해줘",
            "제 프로필 좀 알려줘",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_ml_retrieval_route(query), "user_context"
                )

    def test_external_subject_summary_query_routes_to_realtime_search(self):
        # 2026-08-26: "침착맨에대해. 요약해줘. 최근 이슈와 관련해..."가
        # no_retrieval로 잘못 분류돼(patch 19의 위키 폴백은 search_web()이
        # 아예 호출 안 되니 무용지물이었음) 웹검색 없이 HCX가 완전히 지어낸
        # 인물 정보(가짜 데뷔 연도, 없는 앨범 등)로 답한 사례가 docker logs의
        # [Retrieval] route='no_retrieval' 로그로 재현 확인됨. 원인은
        # routing_train_242.json의 no_retrieval 학습 예시(43개)가 전부 "이
        # 문장을/이 내용을 + 요약해줘"류(프롬프트에 이미 주어진 텍스트를
        # 다듬는 요청)뿐이고, "OO에 대해 요약해줘"처럼 "~에 대해" 구문으로
        # 특정 대상을 지칭하는 예시가 학습 데이터 267개 전체에 하나도 없어서
        # (직접 검증함) char n-gram 모델이 "~을 요약해줘"라는 표면적 겹침만
        # 보고 이 구문을 no_retrieval로 잘못 분류한 것으로 보임.
        for query in (
            "침착맨에대해. 요약해줘. 최근 이슈와 관련해. 9문단으로."
            "전문적으로. 숫자는 꼭 포함해서. 나에게",
            "BTS에 대해 알려줘. 최근 이슈와 관련해",
            "이순신 장군에 대해 설명해줘",
            "리센느에 대하여 소개해줘",
        ):
            with self.subTest(query=query):
                # ML이 no_retrieval/user_context로 잘못 예측한 경우는 결정적
                # 규칙이 external_or_realtime으로 보정하고, ML이 애초에
                # web_search로 (올바르게) 예측한 경우는 그대로 둔다 - 두 라벨
                # 모두 retrieval_orchestrator.py에서 동일하게 search_web()을
                # 호출하므로(route in {"web_search", "external_or_realtime"})
                # 실제 동작에는 차이가 없다.
                self.assertIn(
                    classify_ml_retrieval_route(query),
                    {"external_or_realtime", "web_search"},
                )

    def test_given_text_summary_requests_still_route_to_no_retrieval(self):
        # 회귀 방지: "이 문장을/이 내용을 요약해줘"류(실제 no_retrieval
        # 학습 예시, "~에 대해" 구문이 없음)는 여전히 no_retrieval을 유지해야
        # 한다 - 이미 프롬프트에 주어진 텍스트를 다듬는 요청이라 검색이
        # 필요 없기 때문.
        for query in (
            "이 문장을 요약해줘",
            "이 내용을 다듬어줘",
            "아래 글을 번역해줘",
            "겹치는 문장을 제거해서 자연스럽게 만들어줘",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_ml_retrieval_route(query), "no_retrieval"
                )

    def test_self_referential_about_query_still_routes_to_user_context(self):
        # "내 프로필에 대해 알려줘"처럼 1인칭 자기참조 질의까지 외부 검색으로
        # 돌리면 안 된다 - _is_third_party_profile_query와 동일한 원칙.
        self.assertEqual(
            classify_ml_retrieval_route("내 프로필에 대해 알려줘"),
            "user_context",
        )

    def test_internal_topic_about_query_still_routes_to_internal_rag(self):
        # "우리 회사 정책에 대해 알려줘"처럼 내부 문서를 찾아야 하는 질의까지
        # 외부 검색으로 돌리면 안 된다.
        self.assertEqual(
            classify_ml_retrieval_route("우리 회사 정책에 대해 알려줘"),
            "internal_rag",
        )

    def test_real_estate_query_does_not_fall_back_to_internal_rag(self):
        # 2026-08-26: "요즘 뜨는 부동산 정책 알려줘"가 internal_rag로
        # 잘못 분류돼(학습 데이터에 부동산 카테고리가 아예 없었음) 사내
        # 문서에서만 찾다가 아무것도 못 찾고 끝나는 문제가 있었음 - 스포츠
        # 경기결과와 동일한 부류의 버그.
        for query in (
            "요즘 뜨는 부동산 정책 알려줘",
            "오늘 강남 아파트 시세 알려줘",
            "최근 집값 동향 알려줘",
            "현재 전세 시세 얼마야",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_ml_retrieval_route(query), "external_or_realtime"
                )


class ResolveStrongRetrievalRouteTest(unittest.TestCase):
    """
    2026-08-31: PR #207(action-aware retrieval 리팩터) 이후, 실제 운영 라우팅
    경로(retrieval_orchestrator.execute_retrieval)는 classify_ml_retrieval_route가
    아니라 resolve_action(ActionClassifier) + resolve_strong_retrieval_route만
    거친다. 그런데 "OO에 대해 알려줘/소개해줘/설명해줘" 패턴을 결정적으로
    external_or_realtime으로 보내던 _is_external_subject_summary_query 규칙이
    resolve_strong_retrieval_route로 옮겨지지 않아서, ActionClassifier가 낮은
    confidence를 내는 질의(예: "고마워!"처럼 학습 데이터에 거의 없는 문구가 앞에
    붙은 경우)에서 검색이 아예 스킵되는 회귀가 발생했다. 도커 로그로 재현 확인:
    [Action] action='WEB_FACT' confidence=0.239 sources=() reason=
    'low_confidence_needs_strong_signal' routing_query='고마워! 리센느 걸그룹에
    대해 알려줘.' / [Retrieval] route='no_retrieval' - 결과적으로 HCX가 리센느
    멤버 구성과 존재하지 않는 NFT 사업 모델을 지어내는 답을 내놓았고, sources가
    비어 있어 "출처 더보기"도 뜨지 않았다.
    """

    def test_greeting_prefixed_about_query_routes_to_realtime_search(self):
        # 실제 운영에서 재현된 질의 그대로 - ActionClassifier의 confidence와
        # 무관하게 결정적으로 external_or_realtime이 나와야 한다.
        self.assertEqual(
            resolve_strong_retrieval_route(
                "고마워! 리센느 걸그룹에 대해 알려줘."
            ),
            "external_or_realtime",
        )

    def test_external_subject_summary_query_is_a_strong_route_directly(self):
        for query in (
            "BTS에 대해 알려줘. 최근 이슈와 관련해",
            "이순신 장군에 대해 설명해줘",
            "리센느에 대하여 소개해줘",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    resolve_strong_retrieval_route(query),
                    "external_or_realtime",
                )

    def test_self_referential_about_query_is_not_a_strong_route(self):
        # "내 프로필에 대해 알려줘"까지 결정적으로 external_or_realtime으로
        # 보내면 안 된다 - 이건 여전히 user_context/ML 판단에 맡긴다.
        self.assertIsNone(
            resolve_strong_retrieval_route("내 프로필에 대해 알려줘")
        )

    def test_internal_topic_about_query_is_not_a_strong_external_route(self):
        self.assertEqual(
            resolve_strong_retrieval_route("우리 회사 정책에 대해 알려줘"),
            "internal_rag",
        )


if __name__ == "__main__":
    unittest.main()
