import unittest
from datetime import datetime, timedelta, timezone

from app.services.retrieval.evidence_selector import (
    select_web_evidence,
)


def _days_ago(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%d")


class EvidenceSelectorTest(unittest.TestCase):

    def test_entity_match_beats_mismatch(self):
        results = [
            {
                "title": "다른 아이돌 해외 활동",
                "url": "https://news.example/a",
                "content": "다른 그룹의 활동",
                "score": 0.90,
            },
            {
                "title": "BTS 경제적 영향",
                "url": "https://news.example/b",
                "content": "BTS의 국가 경제 기여",
                "score": 0.82,
            },
        ]

        selected = select_web_evidence(
            results,
            query="BTS가 국가에 기여한 점",
            intent="RESEARCH",
            entity="BTS",
            limit=1,
        )

        self.assertEqual(
            selected[0]["title"],
            "BTS 경제적 영향",
        )

    def test_research_authority_bonus(self):
        results = [
            {
                "title": "BTS 경제 효과 블로그",
                "url": "https://blog.example/a",
                "content": "BTS 경제 효과",
                "score": 0.85,
            },
            {
                "title": "BTS 문화경제 연구",
                "url": "https://example.go.kr/report",
                "content": "BTS 문화 경제 기여 연구",
                "score": 0.75,
            },
        ]

        selected = select_web_evidence(
            results,
            query="BTS 국가 기여",
            intent="RESEARCH",
            entity="BTS",
            limit=1,
        )

        self.assertIn(
            "go.kr",
            selected[0]["url"],
        )

    def test_duplicate_removed(self):
        results = [
            {
                "title": "같은 기사",
                "url": "https://example.com/a",
                "content": "첫 결과",
                "score": 0.9,
            },
            {
                "title": "같은 기사",
                "url": "https://example.com/b",
                "content": "중복 결과",
                "score": 0.8,
            },
        ]

        selected = select_web_evidence(
            results,
            query="테스트",
            intent="GENERAL",
            entity=None,
            limit=3,
        )

        self.assertEqual(
            len(selected),
            1,
        )

    def test_limit(self):
        results = [
            {
                "title": f"result-{i}",
                "url": f"https://example.com/{i}",
                "content": "내용",
                "score": 1 - i * 0.1,
            }
            for i in range(5)
        ]

        selected = select_web_evidence(
            results,
            query="테스트",
            intent="GENERAL",
            entity=None,
            limit=3,
        )

        self.assertEqual(
            len(selected),
            3,
        )


class FreshnessBonusTest(unittest.TestCase):
    """
    2026-09-02: "이강인 선수에 대해 알려줘"처럼 "최근"/"최신"/"오늘" 같은
    시점 표현이 없는 프로필 질의는 search_plan.py가 freshness="NONE"으로
    분류하고, tavily_search.py의 PROFILE 경로가 소속 변경 같은 최신 사실을
    놓치지 않도록 최근 1주일 뉴스를 보조로 함께 가져오게 고쳤다. 하지만
    여기 점수 계산이 발행일(published_date)을 전혀 보지 않으면, 그렇게
    붙여온 최신 뉴스가 우연히 Tavily score가 높은 오래된 위키 스냅샷에
    밀려 최종 후보에서 제외될 수 있다 - 발행일이 최근이면 소폭 가산점을
    준다.
    """

    def test_recent_published_date_outranks_equal_score_result_without_date(
        self,
    ):
        stale = {
            "title": "이강인 - 나무위키",
            "url": "https://namu.wiki/w/이강인",
            "content": "이강인 프로필",
            "score": 0.5,
        }
        recent_news = {
            "title": "이강인 이적 소식",
            "url": "https://news.naver.com/recent",
            "content": "이강인 새 소속팀 발표",
            "score": 0.5,
            "published_date": _days_ago(3),
        }

        # authority_bonus의 영향을 배제하기 위해 intent="GENERAL"로 확인한다
        # (PROFILE이면 나무위키에 별도 권위 가산점이 붙어 신선도 가산점과
        # 뒤섞인다) - 이 테스트는 신선도 가산점 자체만 고정한다.
        selected = select_web_evidence(
            [stale, recent_news],
            query="이강인",
            intent="GENERAL",
            entity=None,
            limit=2,
        )

        self.assertEqual(selected[0]["url"], recent_news["url"])

    def test_old_published_date_gets_no_bonus(self):
        stale = {
            "title": "이강인 - 나무위키",
            "url": "https://namu.wiki/w/이강인",
            "content": "이강인 프로필",
            "score": 0.5,
        }
        old_news = {
            "title": "이강인 예전 기사",
            "url": "https://news.naver.com/old",
            "content": "이강인 예전 소속팀 소식",
            "score": 0.5,
            "published_date": _days_ago(400),
        }

        selected = select_web_evidence(
            [stale, old_news],
            query="이강인",
            intent="GENERAL",
            entity=None,
            limit=2,
        )

        # 점수가 동일하고 둘 다 가산점이 없으므로(오래된 기사는 신선도
        # 가산점 대상이 아님), 정렬이 안정적이어서 원래 순서(stale이 먼저)가
        # 유지돼야 한다.
        self.assertEqual(selected[0]["url"], stale["url"])

    def test_missing_published_date_field_is_unaffected(self):
        # 기존 테스트 픽스처들처럼 published_date 필드 자체가 없는 결과는
        # 신선도 가산점 도입 이전과 동일하게 동작해야 한다(하위 호환).
        results = [
            {
                "title": "결과1",
                "url": "https://example.com/1",
                "content": "내용1",
                "score": 0.6,
            },
            {
                "title": "결과2",
                "url": "https://example.com/2",
                "content": "내용2",
                "score": 0.4,
            },
        ]

        selected = select_web_evidence(
            results,
            query="테스트",
            intent="GENERAL",
            entity=None,
            limit=2,
        )

        self.assertEqual(selected[0]["url"], "https://example.com/1")

    def test_malformed_published_date_does_not_raise(self):
        item = {
            "title": "결과",
            "url": "https://example.com/1",
            "content": "내용",
            "score": 0.5,
            "published_date": "알 수 없음",
        }

        selected = select_web_evidence(
            [item],
            query="테스트",
            intent="GENERAL",
            entity=None,
            limit=1,
        )

        self.assertEqual(len(selected), 1)


if __name__ == "__main__":
    unittest.main()
