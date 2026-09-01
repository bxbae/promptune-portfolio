import unittest

from app.services.retrieval.search_query_cleanup import build_search_query


class BuildSearchQueryTest(unittest.TestCase):
    """
    2026-08-26: PrompTune의 8요소 다듬기 기능이 붙인 어조/분량/대상/제약
    지시문까지 그대로 Tavily 검색어로 보내면, 실제 검색에 필요 없는 문구가
    섞여 들어가 엉뚱한 결과가 상위로 올라오는 사례가 확인됨:
    - "이강인 축구선수" 검색에 무관한 하키/축구 프리뷰 기사가 섞여 들어옴
      (관련 기사 1건은 있었는데도 최종 답변은 그 기사와도 다른 오래된 정보를 냄)
    - "침착맨" 검색 결과가 전혀 무관한 정치 기사 1건뿐이었음
    검색어에서는 이런 상투구 절을 제거하고, 실제 질문 내용만 남겨야 한다.
    """

    def test_strips_audience_tone_length_context_constraint_example_clauses(self):
        # 2026-08-26: "축구선수에대해"처럼 검색 주체 명사에 "에대해"가 그대로
        # 들러붙어 있으면(patch 21 이전) Tavily 색인에 없는 조합 토큰이 되어
        # 관련성 낮은 결과로 밀려나는 사례가 확인돼, "에 대해/대하여/관해/
        # 관하여"는 검색어에서 제거하도록 고쳤다 - "이강인 축구선수"가 다른
        # 단어와 깨끗이 분리된 채로 남아야 한다.
        query = (
            "그럼 이강인 축구선수에대해 알려줘 지금 소속팀과 프로필 부탁해. "
            "요약해줘. 나에게. 최근 이슈와 관련해. 3문단으로. 친근하게. "
            "숫자는 꼭 포함해서"
        )
        self.assertEqual(
            build_search_query(query),
            "그럼 이강인 축구선수 알려줘 지금 소속팀과 프로필 부탁해",
        )

    def test_strips_trailing_directives_but_keeps_task_verb_in_first_clause(self):
        query = (
            "침착맨이라는 유튜버를 간략하게 요약해줘. 나에게. 최근 이슈와 "
            "관련해. 3문단으로. 친근하게. 전문용어는 빼고"
        )
        self.assertEqual(
            build_search_query(query),
            "침착맨이라는 유튜버를 간략하게 요약해줘",
        )

    def test_strips_directives_with_trailing_comma_before_period(self):
        query = (
            "오늘 삼성 주가를 안내해주고,. 3문단으로. 나에게. 이번 분기 "
            "상황에서. 전문적으로. 숫자는 꼭 포함해서. 기존 템플릿 기반으로"
        )
        self.assertEqual(
            build_search_query(query),
            "오늘 삼성 주가를 안내해주고",
        )

    def test_strips_directives_from_short_query(self):
        query = (
            "lg 트윈스 단장님의 이름과 약력을 안내해줘. 나에게. 최근 이슈와 "
            "관련해. 간단하게. 친근하게. 간결하게"
        )
        self.assertEqual(
            build_search_query(query),
            "lg 트윈스 단장님의 이름과 약력을 안내해줘",
        )

    def test_falls_back_to_original_when_entire_query_is_stock_phrases(self):
        # 극단적인 경우(질의 자체가 스타일 지시문 하나뿐)에도 검색어가 아예
        # 빈 문자열이 되면 안 된다 - 잡음이 섞이더라도 검색은 되는 편이 낫다.
        self.assertEqual(build_search_query("친근하게"), "친근하게")

    def test_query_without_periods_is_unchanged(self):
        self.assertEqual(build_search_query("오늘 날씨 어때"), "오늘 날씨 어때")

    def test_empty_query_is_left_unchanged(self):
        self.assertEqual(build_search_query(""), "")

    def test_strips_context_variant_with_edited_wording(self):
        # 2026-08-26: "최근 이슈와 관련해"를 사용자가 직접 "최근 골 소식과
        # 관련해서"로 고쳐 붙인 사례 - 검색어가 골/데뷔전 뉴스 쪽으로 쏠려서
        # 프로필(위키/나무위키) 결과가 안 나오고 답변이 부실해진 원인이었음.
        query = (
            "현제 이강인 소속과 프로필을 알려줘. 나에게. 요약해줘. 최근 골 "
            "소식과 관련해서. 3문단으로. 전문적으로. 숫자는 꼭 포함해서"
        )
        self.assertEqual(
            build_search_query(query),
            "현제 이강인 소속과 프로필을 알려줘",
        )

    def test_strips_additional_info_suggestion_line_joined_by_newline(self):
        # 2026-08-26: improve_prompt가 붙이는 "추가로 필요한 정보: 담당자에게"
        # 안내 문구가 마침표가 아니라 줄바꿈으로만 앞 절("숫자는 꼭 포함해서")과
        # 붙어 있어서, 정확매칭에 실패해 검색어에 그대로 남고 심지어 HCX가
        # 이 문구 자체를 질문으로 오인해 답변에 옮겨 적는 사례가 확인됨.
        query = (
            "현제 이강인 소속과 프로필을 알려줘. 나에게. 요약해줘. 최근 골 "
            "소식과 관련해서. 3문단으로. 전문적으로. 숫자는 꼭 포함해서\n"
            "추가로 필요한 정보: 담당자에게"
        )
        self.assertEqual(
            build_search_query(query),
            "현제 이강인 소속과 프로필을 알려줘",
        )

    def test_legitimate_multi_clause_content_is_preserved(self):
        query = "이강인 소식 알려줘. 최근에 이적했어? 어느 팀으로 갔어"
        self.assertEqual(
            build_search_query(query),
            "이강인 소식 알려줘 최근에 이적했어? 어느 팀으로 갔어",
        )

    def test_strips_about_subject_particle_glued_to_subject_noun(self):
        # 2026-08-26: ml_router.py(patch 20)가 "침착맨에대해. 요약해줘. ..."의
        # 라우팅은 external_or_realtime으로 고쳐서 search_web()이 호출되게
        # 만들었는데도, 여전히 완전히 지어낸 답이 나오는 회귀가 재현됨.
        # docker logs 대신 실제 UI에서 확인한 결과, "출처 더보기"에 침착맨과
        # 전혀 무관한 NFL 기사(Yahoo Sports, Ravens Wire 등)가 붙어 있었음 -
        # search_web()은 호출됐지만 검색어 자체가 "침착맨에대해"라는, 실제
        # 검색 주체("침착맨")에 조사+동사("에대해")가 띄어쓰기 없이 그대로
        # 들러붙은 이 앱에서만 존재하는 조합 토큰이라 Tavily가 제대로 된
        # 결과를 못 찾은 것으로 보임. 원문 그대로(docker logs에서 확인한
        # effective_query)를 고정 회귀 테스트로 남긴다.
        query = (
            "침착맨에대해. 요약해줘. 최근 이슈와 관련해. 9문단으로."
            "전문적으로. 숫자는 꼭 포함해서. 나에게"
        )
        self.assertEqual(build_search_query(query), "침착맨")

    def test_strips_context_and_constraint_variants_seen_in_production(self):
        # 2026-08-31: 실제 운영 로그(chat/108)에서 재현된 사례. "최근 일주일
        # 이전 기준으로"(CONTEXT)와 "전문용어는 꼭 포함해서"(CONSTRAINT의
        # "전문용어는 빼고" 반대 표현) 둘 다 상투구 집합에 없어서 검색어가
        # "이강인 소속과 프로필을 알려줘 최근 일주일 이전 기준으로 전문용어는
        # 꼭 포함해서"로 오염됐고, Tavily가 완전히 무관한 결과(G-DRAGON,
        # 감스트)를 반환해 HCX가 소속팀을 잘못 지어내는 결과로 이어졌다.
        query = (
            "이강인 소속과 프로필을 알려줘. 작성해줘. 나에게. 최근 일주일 "
            "이전 기준으로. 9문단으로. 전문적으로. 전문용어는 꼭 포함해서. "
            "첨부 샘플 참고해서"
        )
        self.assertEqual(
            build_search_query(query),
            "이강인 소속과 프로필을 알려줘",
        )

    def test_strips_about_subject_particle_with_space_before_ask_verb(self):
        for query, expected in (
            ("BTS에 대해 알려줘. 최근 이슈와 관련해", "BTS 알려줘"),
            ("이순신 장군에 대해 설명해줘", "이순신 장군 설명해줘"),
            ("리센느에 대하여 소개해줘", "리센느 소개해줘"),
        ):
            with self.subTest(query=query):
                self.assertEqual(build_search_query(query), expected)


if __name__ == "__main__":
    unittest.main()
