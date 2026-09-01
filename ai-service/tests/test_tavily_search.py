import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.retrieval.tavily_search import (
    _trusted_domains,
    is_recency_query,
    search_web,
)


class TrustedDomainsTest(unittest.TestCase):
    """
    2026-08-26: "침착맨 몇살이야?" 질의에서 은퇴 준비 나이를 다루는 완전히
    무관한 영문 기사가 검색 결과에 섞여 들어와 HCX가 근거 없는 생년월일을
    지어내는 사례가 확인됨. include_domains로 신뢰 도메인(기본값: 네이버
    뉴스)만 검색하도록 제한한 뒤, 이 동작을 고정한다.
    """

    def setUp(self):
        self._original = os.environ.get("TAVILY_TRUSTED_DOMAINS")

    def tearDown(self):
        if self._original is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original

    def test_defaults_to_naver_ytn_mbc_news_when_unset(self):
        # 2026-08-26: 사용자가 "YTN 뉴스나 MBC 뉴스도 링크에 포함해달라"고
        # 요청함 - 네이버뉴스 하나로만 좁혔을 때 방탄소년단 최근 이슈(그래미
        # 보이콧)/침착맨/리센느 같은 질의의 관련 기사를 놓치는 사례가 확인됨.
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        self.assertEqual(
            _trusted_domains(),
            ["news.naver.com", "ytn.co.kr", "imnews.imbc.com"],
        )

    def test_reads_comma_separated_custom_list(self):
        os.environ["TAVILY_TRUSTED_DOMAINS"] = "news.naver.com, reuters.com , cnbc.com"
        self.assertEqual(
            _trusted_domains(), ["news.naver.com", "reuters.com", "cnbc.com"]
        )

    def test_explicit_blank_value_disables_restriction(self):
        os.environ["TAVILY_TRUSTED_DOMAINS"] = "   "
        self.assertEqual(_trusted_domains(), [])


class SearchWebTest(unittest.TestCase):

    def setUp(self):
        self._original_key = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"
        self._original_domains = os.environ.get("TAVILY_TRUSTED_DOMAINS")

    def tearDown(self):
        if self._original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original_key
        if self._original_domains is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original_domains

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_passes_default_trusted_domains_to_tavily(self, mock_client_cls):
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": [{"title": "t", "url": "u", "content": "c"}]}
        mock_client_cls.return_value = mock_client

        results = search_web("침착맨 몇살이야", max_results=3)

        self.assertEqual(results, [{"title": "t", "url": "u", "content": "c"}])
        _, kwargs = mock_client.search.call_args
        self.assertEqual(
            kwargs["include_domains"],
            ["news.naver.com", "ytn.co.kr", "imnews.imbc.com"],
        )
        self.assertEqual(kwargs["topic"], "news")
        self.assertEqual(kwargs["max_results"], 3)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_no_include_domains_when_restriction_disabled(self, mock_client_cls):
        os.environ["TAVILY_TRUSTED_DOMAINS"] = ""
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_client_cls.return_value = mock_client

        search_web("아무 질의", max_results=3)

        # 신뢰 도메인 제한이 꺼져 있으면 첫 번째(뉴스 경로) 호출에는
        # include_domains가 아예 안 붙어야 한다 - 결과가 끝까지 0건이면
        # 아래(NewsPathWikiFallbackTest)에서 검증하는 위키 폴백으로 이어진다.
        first_kwargs = mock_client.search.call_args_list[0].kwargs
        self.assertNotIn("include_domains", first_kwargs)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_finance_query_uses_finance_topic_without_domain_restriction(
        self, mock_client_cls
    ):
        """
        2026-08-26: 신뢰 도메인을 news.naver.com 하나로 제한한 직후 "오늘
        삼성 주가"에 실제(261,500원)와 전혀 다른 가격(약 90,000원)을 답하는
        회귀가 확인됨 - news.naver.com은 시세 숫자가 박힌 페이지가 아니라
        일반 보도 위주라 구체적인 오늘자 가격을 못 찾고 지어낸 것으로 보임.
        시세류 질의는 Tavily 전용 topic="finance"를 쓰고 도메인 제한도
        걸지 않아야 한다.
        """
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "261,500원"}]
        }
        mock_client_cls.return_value = mock_client

        results = search_web("오늘 삼성 주가를 안내해주고 3문단으로", max_results=3)

        self.assertEqual(
            results, [{"title": "t", "url": "u", "content": "261,500원"}]
        )
        _, kwargs = mock_client.search.call_args
        self.assertEqual(kwargs["topic"], "finance")
        self.assertNotIn("include_domains", kwargs)
        self.assertEqual(mock_client.search.call_count, 1)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_falls_back_to_unrestricted_when_restricted_search_is_empty(
        self, mock_client_cls
    ):
        """
        2026-08-26: "어제 lg 트윈스 경기 결과 알려줘" 처럼 인물 프로필이
        아닌 뉴스성 질의에서 news.naver.com 제한 검색이 0건이 되면 웹 검색
        결과 없이 생성이 진행돼, HCX가 회피 답변을 내는 사례가 확인됨.
        제한된 검색이 0건이면 제한 없이 한 번 더 시도해야 한다.
        (인물 프로필류 질의의 도메인 제한/폴백은 ProfileQueryDomainsTest 참고 -
        "단장"/"약력" 같은 단어가 있으면 이제 이 뉴스 경로가 아니라 위키백과/
        나무위키 등 프로필 전용 경로를 탄다.)
        """
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {"results": []},
            {"results": [{"title": "t2", "url": "u2", "content": "c2"}]},
        ]
        mock_client_cls.return_value = mock_client

        results = search_web("어제 lg 트윈스 경기 결과 알려줘", max_results=3)

        self.assertEqual(
            results, [{"title": "t2", "url": "u2", "content": "c2"}]
        )
        self.assertEqual(mock_client.search.call_count, 2)

        first_kwargs = mock_client.search.call_args_list[0].kwargs
        second_kwargs = mock_client.search.call_args_list[1].kwargs
        self.assertEqual(
            first_kwargs["include_domains"],
            ["news.naver.com", "ytn.co.kr", "imnews.imbc.com"],
        )
        self.assertNotIn("include_domains", second_kwargs)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_no_fallback_call_when_restricted_search_has_results(
        self, mock_client_cls
    ):
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("아무 뉴스 질의", max_results=3)

        self.assertEqual(mock_client.search.call_count, 1)


class NewsPathWikiFallbackTest(unittest.TestCase):
    """
    2026-08-26: "침착맨에 대해 요약해줘"처럼 프로필 마커(프로필/약력/소속/
    유튜버/정치인 등)가 전혀 없는 인물 요약 요청이 뉴스 경로로 들어왔는데,
    topic="news" 제한(신뢰 도메인 + time_range) 안에 그 인물을 다루는 최근
    보도가 하나도 없어서 웹 검색 결과 0건인 채로 생성이 진행되고, HCX가
    완전히 지어낸 인물 정보로 답하는 사례가 확인됨. 최신 뉴스가 없다고
    위키백과/나무위키 같은 기본 정보까지 없는 건 아니므로, 뉴스 경로의
    모든 시도가 0건이면 마지막으로 위키백과/나무위키 + 신뢰 뉴스로 한 번 더
    시도한다.
    """

    def setUp(self):
        self._original_key = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"
        self._original_domains = os.environ.get("TAVILY_TRUSTED_DOMAINS")
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)

    def tearDown(self):
        if self._original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original_key
        if self._original_domains is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original_domains

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_falls_back_to_wikipedia_when_all_news_attempts_are_empty(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {"results": []},  # 1차: 뉴스 + 신뢰 도메인
            {"results": []},  # 2차: 뉴스 + 무제한
            {"results": [{"title": "침착맨 - 나무위키", "url": "u3", "content": "c3"}]},
        ]
        mock_client_cls.return_value = mock_client

        results = search_web("침착맨에대해 요약해줘 최근 이슈와 관련해", max_results=3)

        self.assertEqual(
            results,
            [{"title": "침착맨 - 나무위키", "url": "u3", "content": "c3"}],
        )
        self.assertEqual(mock_client.search.call_count, 3)

        third_kwargs = mock_client.search.call_args_list[2].kwargs
        self.assertEqual(third_kwargs["topic"], "general")
        self.assertEqual(
            third_kwargs["include_domains"],
            ["ko.wikipedia.org", "namu.wiki", "news.naver.com", "ytn.co.kr", "imnews.imbc.com"],
        )
        self.assertNotIn("time_range", third_kwargs)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_no_wiki_fallback_call_when_news_path_has_results(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어제 lg 트윈스 경기 결과 알려줘", max_results=3)

        self.assertEqual(mock_client.search.call_count, 1)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_still_empty_after_wiki_fallback_returns_empty_list(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_client_cls.return_value = mock_client

        results = search_web("정말 아무 정보도 없는 질의", max_results=3)

        self.assertEqual(results, [])
        self.assertEqual(mock_client.search.call_count, 3)


class LowRelevanceScoreFallbackTest(unittest.TestCase):
    """
    2026-08-26: patch 21이 검색어를 "침착맨" 단일 토큰으로 정리한 뒤에도
    완전히 지어낸 답변이 재현됨. docker logs로 실제 Tavily 응답을 확인한
    결과, 신뢰 도메인 제한 검색이 "0건"이 아니라 "결과는 2건 있지만
    관련성 점수(score)가 0.12/0.046으로 사실상 무관한" 기사(YTN 오늘의
    운세, 무관한 감독 인터뷰)를 반환했음 - 기존 "0건이면 다음 단계로"
    폴백 조건(if not results)이 트리거되지 않아서, 정답이 있는 위키백과
    폴백까지 도달하지 못했다. score 필드로 "사실상 무관함"을 판정해서
    이런 경우도 다음 단계로 넘어가게 한 동작을 고정한다.
    """

    def setUp(self):
        self._original_key = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"
        self._original_domains = os.environ.get("TAVILY_TRUSTED_DOMAINS")
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)

    def tearDown(self):
        if self._original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original_key
        if self._original_domains is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original_domains

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_low_score_results_fall_through_to_wikipedia(self, mock_client_cls):
        # 실제 프로덕션 docker logs에서 확인한 원문 점수(0.1213/0.0457)를
        # 그대로 재현한다.
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {
                "results": [
                    {
                        "title": "[오늘의 운세]2026년 08월 26일 띠별 운세",
                        "url": "u1",
                        "content": "c1",
                        "score": 0.12130033,
                    },
                    {
                        "title": "[인터뷰] 류승룡 감독...",
                        "url": "u2",
                        "content": "c2",
                        "score": 0.04574752,
                    },
                ]
            },
            {"results": []},  # 무제한 재시도도 여전히 무관함(단순화를 위해 0건으로)
            {
                "results": [
                    {
                        "title": "이말년 - 위키백과",
                        "url": "https://ko.wikipedia.org/wiki/이말년",
                        "content": "침착맨이라는 활동명으로...",
                        "score": 0.87,
                    }
                ]
            },
        ]
        mock_client_cls.return_value = mock_client

        results = search_web("침착맨", max_results=3, time_range="week")

        self.assertEqual(
            results,
            [
                {
                    "title": "이말년 - 위키백과",
                    "url": "https://ko.wikipedia.org/wiki/이말년",
                    "content": "침착맨이라는 활동명으로...",
                    "score": 0.87,
                }
            ],
        )
        self.assertEqual(mock_client.search.call_count, 3)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_high_score_result_does_not_trigger_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "침착맨 관련 기사", "url": "u", "content": "c", "score": 0.65}
            ]
        }
        mock_client_cls.return_value = mock_client

        results = search_web("침착맨", max_results=3)

        self.assertEqual(
            results,
            [{"title": "침착맨 관련 기사", "url": "u", "content": "c", "score": 0.65}],
        )
        self.assertEqual(mock_client.search.call_count, 1)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_mixed_scores_with_one_relevant_result_do_not_trigger_fallback(
        self, mock_client_cls
    ):
        # 여러 결과 중 하나라도 충분히 관련 있으면(score가 임계값 이상)
        # 그 결과를 근거로 삼을 수 있으므로 다음 단계로 넘어가지 않는다.
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "무관한 기사", "url": "u1", "content": "c1", "score": 0.05},
                {"title": "침착맨 관련 기사", "url": "u2", "content": "c2", "score": 0.6},
            ]
        }
        mock_client_cls.return_value = mock_client

        search_web("침착맨", max_results=3)

        self.assertEqual(mock_client.search.call_count, 1)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_missing_score_field_is_trusted_as_before(self, mock_client_cls):
        # score 필드가 없는 응답(기존 테스트 픽스처 등)은 이 판정에서 제외돼
        # 예전처럼 그대로 신뢰해야 한다 - 실제 Tavily 응답에는 항상 score가
        # 있으므로 이 검사는 실전에서는 영향이 없고, 기존 테스트 스위트의
        # 나머지 부분(score를 안 쓰는 모든 픽스처)이 회귀 없이 그대로
        # 통과해야 한다.
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("아무 질의", max_results=3)

        self.assertEqual(mock_client.search.call_count, 1)


class ProfileQueryDomainsTest(unittest.TestCase):
    """
    2026-08-26: "이강인 축구선수 프로필/소속" 질의가 (검색어 정제 이후로는)
    관련 있는 기사를 찾긴 하는데도, 나무위키의 오래된 문단(발렌시아 CF
    시절)이나 근거 없는 수치(체중 90kg, 생년월일 2003년 등 - 실제는 66kg,
    2001년생)를 섞어 답하는 사례가 확인됨. 사용자가 "선수는 올림픽 사이트,
    가수/배우는 그래미 사이트 기준으로" 요청해서, 인물 프로필류 질의는
    위키백과/나무위키(+종목별 공식 사이트)로 검색을 제한한다.
    """

    def setUp(self):
        self._original_key = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"
        # 2026-08-26: 샌드박스 셸 환경에 TAVILY_TRUSTED_DOMAINS=""가 미리
        # 설정돼 있어서(다른 테스트 클래스는 각자 pop/restore로 정규화함),
        # 여기서도 동일하게 정규화하지 않으면 뉴스 경로(비-프로필 질의)를
        # 검증하는 테스트가 우연한 셸 상태에 따라 흔들린다.
        self._original_domains = os.environ.get("TAVILY_TRUSTED_DOMAINS")
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)

    def tearDown(self):
        if self._original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original_key
        if self._original_domains is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original_domains

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_athlete_profile_query_uses_all_four_profile_domains(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "이강인", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("그럼 이강인 축구선수에대해 알려줘 지금 소속팀과 프로필 부탁해", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(kwargs["topic"], "general")
        self.assertEqual(
            kwargs["include_domains"],
            [
                "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
                "news.naver.com", "ytn.co.kr", "imnews.imbc.com",
            ],
        )

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_singer_actor_profile_query_includes_grammy(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어느 가수의 프로필을 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(
            kwargs["include_domains"],
            [
                "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
                "news.naver.com", "ytn.co.kr", "imnews.imbc.com",
            ],
        )

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_profile_query_without_category_keyword_still_includes_all_domains(
        self, mock_client_cls
    ):
        # 2026-08-26: "이강인 소속과 프로필을 알려줘"처럼 "선수"/"축구" 같은
        # 직업 카테고리 단어가 전혀 없는 프로필 질의에서 olympics.com이
        # 빠져서 결과가 부실해지는 사례가 반복 확인됨 - 카테고리 추측 없이
        # 항상 4개 도메인 전부 후보에 넣도록 고쳤다.
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "이강인", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("이강인 소속과 프로필을 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(
            kwargs["include_domains"],
            [
                "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
                "news.naver.com", "ytn.co.kr", "imnews.imbc.com",
            ],
        )

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_music_sports_profile_query_combines_wiki_and_trusted_news_domains(
        self, mock_client_cls
    ):
        # 2026-08-27: "링크 목록에 내가 검색한 검색 결과에 사용될 링크 중에
        # ytn이나 mbc 나, 올림픽, 그래미 사이트 검색 링크가 있다면 함께
        # 링크를 추가로 넣어줄 수 있을까? 검색 신뢰도를 높이기 위해서야."
        # 라는 요청에 따라, 음악/체육 프로필 질의(예: "리센느")는 위키/나무위키
        # /올림픽/그래미뿐 아니라 신뢰 뉴스 도메인(네이버뉴스/YTN/MBC)도
        # 같은 include_domains 목록에 함께 담아, Tavily가 실제로 매칭되는
        # 콘텐츠를 찾은 도메인이면 무엇이든 "출처 더보기" 링크로 함께 노출될
        # 수 있도록 한다.
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "리센느", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("리센느 가수 프로필 알려줘. 발매 곡 기준으로", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(
            kwargs["include_domains"],
            [
                "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
                "news.naver.com", "ytn.co.kr", "imnews.imbc.com",
            ],
        )

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_profile_query_falls_back_to_unrestricted_when_empty(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {"results": []},
            {"results": [{"title": "t2", "url": "u2", "content": "c2"}]},
        ]
        mock_client_cls.return_value = mock_client

        results = search_web(
            "lg 트윈스 단장님의 이름과 약력을 안내해줘", max_results=3
        )

        self.assertEqual(
            results, [{"title": "t2", "url": "u2", "content": "c2"}]
        )
        self.assertEqual(mock_client.search.call_count, 2)

        first_kwargs = mock_client.search.call_args_list[0].kwargs
        second_kwargs = mock_client.search.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["topic"], "general")
        self.assertEqual(
            first_kwargs["include_domains"],
            [
                "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
                "news.naver.com", "ytn.co.kr", "imnews.imbc.com",
            ],
        )
        self.assertNotIn("include_domains", second_kwargs)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_stale_wiki_revision_results_are_filtered_out(
        self, mock_client_cls
    ):
        # 2026-08-26: "이강인 소속과 프로필" 검색 결과에 "이강인 (r444 판)",
        # "이강인 (r297 판)"처럼 예전 리비전 스냅샷(발렌시아 CF 시절 등,
        # 현재 소속이 반영 안 됨)이 섞여 들어와 답변이 오래된 정보로
        # 후퇴한 사례가 확인됨 - 이런 스냅샷 결과는 걸러야 한다.
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "이강인 (r444 판) - 나무위키", "url": "u1", "content": "c1"},
                {"title": "이강인 (r297 판) - 나무위키", "url": "u2", "content": "c2"},
                {"title": "이강인 - 나무위키", "url": "u3", "content": "c3"},
            ]
        }
        mock_client_cls.return_value = mock_client

        results = search_web("이강인 소속과 프로필을 알려줘", max_results=3)

        self.assertEqual(
            results,
            [{"title": "이강인 - 나무위키", "url": "u3", "content": "c3"}],
        )

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_all_stale_wiki_revisions_trigger_unrestricted_fallback(
        self, mock_client_cls
    ):
        # 필터링 결과 0건이 되면(전부 예전 리비전이면), 기존 "0건이면 무제한
        # 재시도" 폴백이 그대로 이어받아야 한다.
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {
                "results": [
                    {"title": "이강인 (r444 판)", "url": "u1", "content": "c1"},
                ]
            },
            {"results": [{"title": "이강인 최신", "url": "u2", "content": "c2"}]},
        ]
        mock_client_cls.return_value = mock_client

        results = search_web("이강인 소속과 프로필을 알려줘", max_results=3)

        self.assertEqual(
            results, [{"title": "이강인 최신", "url": "u2", "content": "c2"}]
        )
        self.assertEqual(mock_client.search.call_count, 2)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_non_profile_query_is_unaffected(self, mock_client_cls):
        mock_client = MagicMock()
        # 결과를 비워두면(빈 리스트) 뉴스 경로의 "0건이면 무제한 재시도"
        # 폴백(0008)이 걸려서 두 번째 호출(무제한)이 마지막 call_args가 돼
        # 버리므로, 이 테스트에서 확인하려는 "첫 호출이 뉴스+신뢰 도메인으로
        # 나가는지"를 결과가 있는 상태로 확인한다.
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어제 lg 트윈스 경기 결과 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(kwargs["topic"], "news")
        self.assertEqual(
            kwargs["include_domains"],
            ["news.naver.com", "ytn.co.kr", "imnews.imbc.com"],
        )
        self.assertEqual(mock_client.search.call_count, 1)


class NonMusicSportsProfileDomainsTest(unittest.TestCase):
    """
    2026-08-26: "다른 유튜버를 검색해보니 검색 결과가 음악인으로 잘못 나온다"는
    사용자 리포트가 확인됨 - "유튜버"/"정치인"/"인플루언서"처럼 음악인·체육인이
    아니라는 게 질의에 명시된 경우, grammy.com/olympics.com에 이름이 일부만
    겹치는 무관한 인물 문서가 섞여 들어와 모델이 인물을 혼동한 것으로 보임.
    사용자가 요청한 대로 "언론사 인터뷰 + 위키백과"를 근거로 삼도록 이런
    질의는 grammy/olympics 대신 신뢰 뉴스 도메인을 후보에 넣는다.
    """

    def setUp(self):
        self._original_key = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"
        self._original_domains = os.environ.get("TAVILY_TRUSTED_DOMAINS")
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)

    def tearDown(self):
        if self._original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original_key
        if self._original_domains is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original_domains

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_youtuber_profile_query_excludes_music_and_sports_domains(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "어느 유튜버", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어느 유튜버의 프로필을 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(
            kwargs["include_domains"],
            ["ko.wikipedia.org", "namu.wiki", "news.naver.com", "ytn.co.kr", "imnews.imbc.com"],
        )

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_politician_profile_query_excludes_music_and_sports_domains(
        self, mock_client_cls
    ):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "어느 정치인", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어느 정치인의 약력을 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertNotIn("grammy.com", kwargs["include_domains"])
        self.assertNotIn("olympics.com", kwargs["include_domains"])
        self.assertIn("ko.wikipedia.org", kwargs["include_domains"])
        self.assertIn("namu.wiki", kwargs["include_domains"])

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_athlete_profile_query_still_includes_music_and_sports_domains(
        self, mock_client_cls
    ):
        # 회귀 방지: 음악인/체육인 마커가 있거나 마커가 아예 없는 프로필
        # 질의는 여전히 grammy.com/olympics.com을 포함해야 한다(패치 16).
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "이강인", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("이강인 소속과 프로필을 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertEqual(
            kwargs["include_domains"],
            [
                "ko.wikipedia.org", "namu.wiki", "olympics.com", "grammy.com",
                "news.naver.com", "ytn.co.kr", "imnews.imbc.com",
            ],
        )


class IsRecencyQueryTest(unittest.TestCase):
    """
    2026-08-26: "최근 소식은 오늘 기준 일주일 이내 기사를 기준으로 삼아달라"는
    사용자 요청에 따라, 이 마커 판정 함수가 retrieval_orchestrator.py에서
    검색어 정제(불용구 제거) *이전*의 원문 질의에 대해 호출된다. 정제 이후에는
    "최근 골 소식과 관련해서" 같은 문구 자체가 이미 지워져 있을 수 있어
    정제 후 문자열로 판정하면 항상 False가 나온다 - 그래서 이 함수 자체의
    동작만 독립적으로 고정한다.
    """

    def test_detects_common_recency_markers(self):
        for query in [
            "이강인 최근 소식 알려줘",
            "오늘 삼성 주가를 안내해줘",
            "어제 lg 트윈스 경기 결과 알려줘",
            "지금 이강인 소속팀이 어디야",
            "요즘 이강인 근황이 궁금해",
            "방금 나온 뉴스 알려줘",
            "이강인 최신 이슈가 뭐야",
            "이강인의 현재 소속을 알려줘",
        ]:
            with self.subTest(query=query):
                self.assertTrue(is_recency_query(query))

    def test_does_not_flag_queries_without_recency_markers(self):
        for query in [
            "이강인 소속과 프로필을 알려줘",
            "그럼 이 문서를 3문단으로 요약해줘",
            "LG 트윈스 단장님의 이름과 약력을 안내해줘",
        ]:
            with self.subTest(query=query):
                self.assertFalse(is_recency_query(query))

    def test_empty_query_is_not_recency(self):
        self.assertFalse(is_recency_query(""))


class SearchWebTimeRangeTest(unittest.TestCase):
    """
    2026-08-26: "최근" 소식 요청에 몇 달~몇 년 전 기사까지 섞여 나온 사례가
    확인됨 - search_web()이 time_range를 받으면 Tavily search()에 그대로
    실려 나가는지, 받지 않으면(None) 아예 파라미터를 안 붙이는지(기존 동작
    보존) 둘 다 고정한다.
    """

    def setUp(self):
        self._original_key = os.environ.get("TAVILY_API_KEY")
        os.environ["TAVILY_API_KEY"] = "test-key"
        self._original_domains = os.environ.get("TAVILY_TRUSTED_DOMAINS")
        os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)

    def tearDown(self):
        if self._original_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = self._original_key
        if self._original_domains is None:
            os.environ.pop("TAVILY_TRUSTED_DOMAINS", None)
        else:
            os.environ["TAVILY_TRUSTED_DOMAINS"] = self._original_domains

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_news_query_passes_time_range_through(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어제 lg 트윈스 경기 결과 알려줘", max_results=3, time_range="week")

        _, kwargs = mock_client.search.call_args
        self.assertEqual(kwargs["time_range"], "week")

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_profile_query_passes_time_range_through(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "이강인", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("이강인 소속과 프로필을 알려줘", max_results=3, time_range="week")

        _, kwargs = mock_client.search.call_args
        self.assertEqual(kwargs["time_range"], "week")

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_no_time_range_param_when_not_requested(self, mock_client_cls):
        # 기존 호출부(orchestrator가 time_range를 안 넘기는 경우 등)의 동작을
        # 그대로 보존한다 - time_range를 안 주면 Tavily 호출에 그 키 자체가
        # 없어야 한다(값이 None으로라도 붙으면 Tavily가 이를 어떻게 처리할지
        # 불명확하므로 아예 생략).
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "c"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("어제 lg 트윈스 경기 결과 알려줘", max_results=3)

        _, kwargs = mock_client.search.call_args
        self.assertNotIn("time_range", kwargs)

    @patch("app.services.retrieval.tavily_search.TavilyClient")
    def test_finance_query_ignores_time_range(self, mock_client_cls):
        # 시세류는 topic="finance" 자체가 이미 최신 데이터 소스로 좁혀져
        # 있으므로, 실수로 time_range가 전달돼도 무시한다(추가 제약으로
        # 결과가 0건이 되는 회귀를 막기 위함).
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "t", "url": "u", "content": "261,500원"}]
        }
        mock_client_cls.return_value = mock_client

        search_web("오늘 삼성 주가를 안내해줘", max_results=3, time_range="week")

        _, kwargs = mock_client.search.call_args
        self.assertNotIn("time_range", kwargs)


if __name__ == "__main__":
    unittest.main()
